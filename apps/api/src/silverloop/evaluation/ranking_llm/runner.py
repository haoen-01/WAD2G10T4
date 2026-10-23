"""The `llm_recorded` arm: replay the real `plan_activity_ranking` loop over the benchmark.

Every case runs the production loop -- the same prompt, the same tool surface, the same
guardrail, the same iteration cap, the same five-way degradation -- with `RecordedClient` as the
transport and the deterministic `full` arm order as `fallback_order`. Nothing is monkeypatched
and no shortcut path exists: a recorded run that falls back produces exactly the deterministic
order, which is what makes the deltas below interpretable.

Every interval here is a persona-clustered bootstrap, and every arm comparison is a paired one
over the same cases -- the same test the deterministic benchmark uses, for the same reason: six
cases share one persona's trace, preference store and grade table, so resampling cases would
pretend to six times the evidence this design carries.

Two things this module refuses to do
------------------------------------
*Report a silent zero.* A split with no usable recording is `recorded=False` and prints
"not recorded" for every metric. A case whose request is not in the recording is a
`RecordingMiss`, degrades to `fallback_error`, and is counted in `misses` and in the
fallback histogram -- never averaged in as "the model agreed with the ranker".

*Claim model quality.* See the package docstring. The recordings ship from a scripted stand-in.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from silverloop.activity_search import RankedScore
from silverloop.agent.constants import MAX_ACTIVITY_OPTIONS_RETURNED
from silverloop.agent.guardrail_rules import count_violations_by_rule
from silverloop.agent.planner import ActivityPlanRun, plan_activity_ranking
from silverloop.agent.recorded_client import RecordedClient, Recording, ReplayedCall
from silverloop.agent.tools import PROPOSE_ACTIVITY_ORDER_TOOL_NAME
from silverloop.evaluation.ranking import ablations
from silverloop.evaluation.ranking.dataset import (
    CORE_PERSONAS,
    HOLDOUT_PERSONAS,
    QUERY_TEMPLATES,
    PersonaBrief,
    QueryTemplate,
    dataset_digest,
)
from silverloop.evaluation.ranking.metrics import (
    Delta,
    Rate,
    Stat,
    cluster_bootstrap_stat,
    cluster_paired_delta,
)
from silverloop.evaluation.ranking.runner import (
    CORE_SPLIT,
    HOLDOUT_SPLIT,
    TOP_K,
    CaseResult,
    _case_metrics,
    run_case,
)
from silverloop.evaluation.ranking_llm.harness import ACTIVITY_RECORDINGS, ranking_context
from silverloop.evaluation.ranking_llm.harness import recorded_settings as _recorded_settings

GENERATOR_VERSION = "1.0.0"
LLM_ARM_SEED = 20260913
ARM_LLM_RECORDED = "llm_recorded"

# The metric family the deterministic benchmark already reports per case, kept identical on
# purpose: `_case_metrics` is imported rather than reimplemented so the two arms can never drift
# into measuring subtly different things and be compared anyway.
CASE_METRIC_NAMES: tuple[str, ...] = (
    "ndcg_at_1",
    "hit_rate_at_3",
    "slate_ndcg_at_3",
    "ndcg_at_3",
    "context_rule_conformance_at_3",
    "precision_at_3",
    "mrr",
    "unknown_admitted_at_3",
    "category_entropy_at_3",
)


def _seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def apply_planner_order(
    ranked: list[RankedScore], selected_order: list[str]
) -> tuple[list[RankedScore], list[str]]:
    """What the person would actually be shown, and which shown options the planner dropped.

    Mirrors the write-side of `sql_repository.search_activities` exactly: the planner's own
    order first, then any option it was shown and left out, then the tail below
    `MAX_ACTIVITY_OPTIONS_RETURNED` that it never saw. A dropped option is *demoted*, never
    deleted -- the product records it under `planner_narrowed` in `filtered_out` and the person
    can still reach it. Measuring a deletion the product does not perform would overstate both
    the risk and the effect of narrowing.
    """
    by_id = {item.ranked.candidate.activity_id: item for item in ranked}
    reordered = [by_id[key] for key in selected_order if key in by_id]
    if not reordered:
        return list(ranked), []
    deterministic_ids = [item.ranked.candidate.activity_id for item in ranked]
    shown_ids = set(deterministic_ids[:MAX_ACTIVITY_OPTIONS_RETURNED])
    kept_ids = {item.ranked.candidate.activity_id for item in reordered}
    narrowed = [
        activity_id
        for activity_id in deterministic_ids
        if activity_id in shown_ids and activity_id not in kept_ids
    ]
    tail_shown = [by_id[activity_id] for activity_id in narrowed]
    tail_unseen = [
        item
        for item in ranked
        if item.ranked.candidate.activity_id not in shown_ids
        and item.ranked.candidate.activity_id not in kept_ids
    ]
    return reordered + tail_shown + tail_unseen, narrowed


def agreement_at_k(left: list[str], right: list[str], k: int = TOP_K) -> float:
    """`|top-k ∩ top-k| / k`. A redundancy measure, exactly like `planner_agreed_with_ranker`:
    agreement says the planner added nothing; disagreement says nothing about which was right."""
    if k <= 0:
        return 0.0
    return len(set(left[:k]) & set(right[:k])) / k


def max_promotion(deterministic: list[str], displayed: list[str]) -> int:
    """The largest number of places any option moved *up*. Zero when nothing was promoted.

    This is the number the promotion cap (M-series `bound_planner_order`) is about: how far the
    model can lift an option the deterministic ranker put lower. Reported as an observed maximum,
    never averaged -- a mean promotion would hide the one case that matters.
    """
    positions = {activity_id: index for index, activity_id in enumerate(displayed)}
    best = 0
    for index, activity_id in enumerate(deterministic):
        new_index = positions.get(activity_id)
        if new_index is None:
            continue
        best = max(best, index - new_index)
    return best


@dataclass(frozen=True)
class ArmCaseResult:
    """One benchmark case replayed through the loop."""

    split: str
    persona_id: str
    template: str
    run: ActivityPlanRun
    options_shown: int
    """How many options the model was actually offered (the allow-list, capped)."""
    deterministic_order: list[str]
    displayed_order: list[str]
    narrowed: list[str]
    metrics: dict[str, float]
    deterministic_metrics: dict[str, float]
    calls: list[ReplayedCall]
    misses: int

    @property
    def used_agent(self) -> bool:
        return self.run.used_agent

    @property
    def proposals(self) -> int:
        return sum(
            1 for call in self.run.tool_calls if call.tool_name == PROPOSE_ACTIVITY_ORDER_TOOL_NAME
        )

    @property
    def rejected_proposals(self) -> int:
        return self.run.rejected_proposal_count

    @property
    def narrowing_rate(self) -> float:
        if not self.options_shown:
            return 0.0
        offered = len([key for key in self.run.selected_order if key])
        return max(0.0, 1.0 - offered / self.options_shown)

    @property
    def agreement_at_3(self) -> float:
        return agreement_at_k(self.displayed_order, self.deterministic_order)

    @property
    def max_promotion(self) -> int:
        return max_promotion(self.deterministic_order, self.displayed_order)

    @property
    def total_tokens(self) -> int:
        return sum(call.total_tokens for call in self.calls)

    @property
    def latencies_ms(self) -> list[int]:
        return [call.latency_ms for call in self.calls]


@dataclass(frozen=True)
class LlmSplitResult:
    split: str
    n_cases: int
    recorded_cases: int
    """Cases where every request was answered from the recording. Zero means "not recorded"."""
    misses: int
    metrics: dict[str, Stat]
    deltas: dict[str, Delta]
    agreement_at_3: Stat
    narrowing_rate: Stat
    max_promotion_observed: int
    guardrail_rejection_rate: Rate
    fallback_counts: dict[str, int]
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    tokens_per_run_mean: float | None
    tokens_per_run_p95: int | None
    cases: list[ArmCaseResult] = field(repr=False, default_factory=list)

    @property
    def recorded(self) -> bool:
        """False when nothing in this split replayed -- the report prints "not recorded"."""
        return self.recorded_cases > 0

    def fallback_rate(self, mode: str) -> Rate:
        return Rate(numerator=self.fallback_counts.get(mode, 0), denominator=self.n_cases)


@dataclass(frozen=True)
class LlmArmResult:
    generator_version: str
    seed: int
    dataset_digest: str
    recordings_path: str
    recording_files: list[str]
    recording_entries: int
    recording_banner: str
    recording_is_synthetic: bool
    model: str
    core: LlmSplitResult
    holdout: LlmSplitResult

    @property
    def recorded(self) -> bool:
        return self.core.recorded or self.holdout.recorded


def _percentile(values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile over a small sample. `None` for an empty one -- an empty latency
    sample is "nothing was measured", which must never print as 0 ms."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def run_arm_case(
    split: str,
    persona: PersonaBrief,
    template: QueryTemplate,
    *,
    client: RecordedClient,
    settings: Any,
    case: CaseResult | None = None,
) -> ArmCaseResult:
    """Replay one case. `case` may be supplied to avoid re-running the deterministic benchmark."""
    case = case or run_case(split, persona, template)
    ranked = case.arms[ablations.ARM_FULL]
    context = ranking_context(case, ranked)
    deterministic_order = [item.ranked.candidate.activity_id for item in ranked]

    calls_before = len(client.replayed)
    misses_before = len(client.misses)
    run = plan_activity_ranking(
        context,
        settings=settings,
        fallback_order=list(deterministic_order),
        client_factory=lambda: (client, None),
    )
    calls = list(client.replayed[calls_before:])
    misses = len(client.misses) - misses_before

    displayed, narrowed = apply_planner_order(ranked, run.selected_order)
    return ArmCaseResult(
        split=split,
        persona_id=persona.person_id,
        template=template.name,
        run=run,
        options_shown=len(context.permitted_keys),
        deterministic_order=deterministic_order,
        displayed_order=[item.ranked.candidate.activity_id for item in displayed],
        narrowed=narrowed,
        metrics=_case_metrics(case, displayed),
        deterministic_metrics=_case_metrics(case, ranked),
        calls=calls,
        misses=misses,
    )


def _run_split(
    split: str,
    personas: tuple[PersonaBrief, ...],
    *,
    client: RecordedClient,
    settings: Any,
) -> LlmSplitResult:
    cases = [
        run_arm_case(split, persona, template, client=client, settings=settings)
        for persona in personas
        for template in QUERY_TEMPLATES
    ]

    per_metric: dict[str, list[float]] = {name: [] for name in CASE_METRIC_NAMES}
    per_metric_deterministic: dict[str, list[float]] = {name: [] for name in CASE_METRIC_NAMES}
    for case in cases:
        for name in CASE_METRIC_NAMES:
            per_metric[name].append(case.metrics[name])
            per_metric_deterministic[name].append(case.deterministic_metrics[name])

    # The persona each case came from. Six cases share one persona's trace, preference store and
    # grade table, so they are not six independent observations and the bootstrap must resample
    # personas rather than cases -- decisions section 16, and `metrics.bootstrap_stat`'s own
    # docstring, which puts the per-case interval at ~2.2x too narrow on this design. This arm
    # used the per-case form, which is how three deltas came to be published as excluding zero
    # when the mandated test says they do not.
    clusters = [case.persona_id for case in cases]
    agent_cases = [case for case in cases if case.used_agent]
    agent_clusters = [case.persona_id for case in agent_cases]
    fallback_counts: dict[str, int] = {}
    for case in cases:
        fallback_counts[case.run.mode] = fallback_counts.get(case.run.mode, 0) + 1

    latencies = [latency for case in cases for latency in case.latencies_ms]
    tokens_per_run = [case.total_tokens for case in cases if case.calls]

    return LlmSplitResult(
        split=split,
        n_cases=len(cases),
        recorded_cases=sum(1 for case in cases if case.calls and case.misses == 0),
        misses=sum(case.misses for case in cases),
        metrics={
            name: cluster_bootstrap_stat(values, clusters, seed=_seed(split, "llm", name))
            for name, values in per_metric.items()
        },
        deltas={
            name: cluster_paired_delta(
                per_metric_deterministic[name],
                per_metric[name],
                clusters,
                seed=_seed(split, "llm-delta", name),
            )
            for name in CASE_METRIC_NAMES
        },
        agreement_at_3=cluster_bootstrap_stat(
            [case.agreement_at_3 for case in agent_cases],
            agent_clusters,
            seed=_seed(split, "agreement"),
        ),
        narrowing_rate=cluster_bootstrap_stat(
            [case.narrowing_rate for case in agent_cases],
            agent_clusters,
            seed=_seed(split, "narrowing"),
        ),
        max_promotion_observed=max((case.max_promotion for case in agent_cases), default=0),
        guardrail_rejection_rate=Rate(
            numerator=sum(case.rejected_proposals for case in cases),
            denominator=sum(case.proposals for case in cases),
        ),
        fallback_counts=fallback_counts,
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
        tokens_per_run_mean=(
            round(sum(tokens_per_run) / len(tokens_per_run), 1) if tokens_per_run else None
        ),
        tokens_per_run_p95=_percentile(tokens_per_run, 0.95),
        cases=cases,
    )


def run_llm_evaluation(recordings: Path | None = None) -> LlmArmResult:
    """Run the arm over both splits. A missing or empty recording is reported, never raised."""
    path = Path(recordings) if recordings is not None else ACTIVITY_RECORDINGS
    settings = _recorded_settings(path)
    client = RecordedClient(path, mode="replay")

    banner = ""
    synthetic = True
    files: list[str] = []
    if client.sources:
        first = Recording.load(client.sources[0])
        banner = first.banner
        synthetic = first.synthetic
        files = [file.name for file in client.sources]

    core = _run_split(CORE_SPLIT, CORE_PERSONAS, client=client, settings=settings)
    holdout = _run_split(HOLDOUT_SPLIT, HOLDOUT_PERSONAS, client=client, settings=settings)
    return LlmArmResult(
        generator_version=GENERATOR_VERSION,
        seed=LLM_ARM_SEED,
        dataset_digest=dataset_digest(),
        recordings_path=str(path),
        recording_files=files,
        recording_entries=client.recorded_count,
        recording_banner=banner,
        recording_is_synthetic=synthetic,
        model=settings.llm_model,
        core=core,
        holdout=holdout,
    )


def guardrail_rejections_by_rule(split: LlmSplitResult) -> dict[str, int]:
    """Which guardrail rules actually bound, over every run in the split."""
    counts: dict[str, int] = {}
    for case in split.cases:
        for rule, count in count_violations_by_rule(case.run.guardrail_rejections).items():
            counts[rule] = counts.get(rule, 0) + count
    return counts


__all__ = [
    "ARM_LLM_RECORDED",
    "CASE_METRIC_NAMES",
    "GENERATOR_VERSION",
    "ArmCaseResult",
    "LlmArmResult",
    "LlmSplitResult",
    "agreement_at_k",
    "apply_planner_order",
    "guardrail_rejections_by_rule",
    "max_promotion",
    "run_arm_case",
    "run_llm_evaluation",
]
