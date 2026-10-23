"""Artifacts for the `llm_recorded` arm: `docs/evaluation/ranking-llm.{json,md}`.

Same determinism discipline as `evaluation/ranking/report.py`: no timestamps, no absolute paths
(an absolute recording path would make the artifact machine-dependent and `--check` would fail on
every other machine), only version, seed and digests as provenance -- so the generator run twice
produces byte-identical output.

Two things this report will not do:

* print a metric for a split that has no usable recording. It prints `not recorded`, with the
  miss count, so a missing fixture can never be read as "the model agreed with the ranker";
* print a number from the recording without saying where it came from. Latency and token columns
  carry SYNTHETIC in their own label whenever the recording declares itself synthetic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from silverloop.evaluation.ranking.dataset import CORE_PERSONAS, HOLDOUT_PERSONAS, QUERY_TEMPLATES
from silverloop.evaluation.ranking.metrics import Delta, Rate, Stat
from silverloop.evaluation.ranking.report import weights_digest
from silverloop.evaluation.ranking_llm.runner import (
    ARM_LLM_RECORDED,
    CASE_METRIC_NAMES,
    guardrail_rejections_by_rule,
)
from silverloop.evaluation.ranking_llm.scripted_model import (
    MIN_OFFERED,
    NARROWING_FROM_POSITION,
)

if TYPE_CHECKING:
    from silverloop.evaluation.ranking_llm.runner import LlmArmResult, LlmSplitResult

SCHEMA_VERSION = 1
JSON_FILENAME = "ranking-llm.json"
MARKDOWN_FILENAME = "ranking-llm.md"

NOT_RECORDED = "not recorded"

NOT_USER_TRUTH = (
    "NOT_USER_TRUTH: every persona, listing and observation trace behind this arm is the same "
    "synthetic design artefact the deterministic ranking benchmark uses. No row here is, or is "
    "derived from, a real senior's data."
)

NOT_A_MODEL = (
    "NOT_A_MODEL: the recordings replayed here were produced by "
    "`silverloop.evaluation.ranking_llm.scripted_model`, a deterministic rule-based stand-in -- "
    "NOT by a language model. Rule A varies the categories of the first three options; rule B "
    f"drops options from position {NARROWING_FROM_POSITION} onward that repeat a category "
    f"already offered, never going below {MIN_OFFERED}. Nothing in this report is evidence "
    "about any model's quality, and no delta below should be quoted as one. What it IS evidence "
    "for: the planner loop, its allow-list guardrail, its narrowing bound and its five "
    "degradation modes run end to end offline over every benchmark case, and the metric family "
    "below can tell a reordering from the deterministic order instead of reporting structural "
    "zeros. Re-record against a provider (`synthesise.py --inner anthropic --model ...`) and "
    "every number here becomes a statement about that model, with no code change."
)

METHODOLOGY = (
    "Each case is one (persona, query template) pair from the ranking benchmark, replayed "
    "through the production `agent.planner.plan_activity_ranking` loop with "
    "`agent.recorded_client.RecordedClient` as the transport and the deterministic `full` arm's "
    "order as `fallback_order`. The displayed order is assembled exactly as "
    "`sql_repository.search_activities` assembles it: the planner's order, then any option it "
    "was shown and left out, then the tail it never saw -- narrowing demotes, it never deletes. "
    "Relevance grades, splits and the metric family are the deterministic benchmark's own, "
    "unchanged (`_case_metrics` is imported, not reimplemented), so the deltas are paired and "
    "comparable. A request with no recorded answer raises `RecordingMiss`, degrades to "
    "`fallback_error` and is counted as a miss -- it is never silently averaged in. "
    "`planner_agreement@3` is a redundancy measure, not a quality one: agreement says the "
    "planner added nothing, disagreement says nothing about which order was better. "
    "Every interval below is a PERSONA-CLUSTERED bootstrap and every delta is paired over the "
    "same cases, so `n_clusters` is printed beside `n` everywhere: `n` is how many numbers were "
    "averaged, `n_clusters` is how many independent things they came from. This arm used to "
    "resample cases i.i.d., which on a design where six cases share one persona's trace, "
    "preference store and grade table is roughly 2.2x too narrow, and it let small deltas read "
    "as excluding zero that the clustered test does not support. Which deltas clear zero is read "
    "from the tables below on each regeneration, never restated here: it moves with the "
    "deterministic order the stand-in is compared against, and an earlier version of this "
    "paragraph that named three of them went stale for exactly that reason."
)

_METRIC_LABELS: dict[str, str] = {
    "ndcg_at_1": "NDCG@1",
    "hit_rate_at_3": "HitRate@3 (rel=3)",
    "slate_ndcg_at_3": "slate_ndcg@3",
    "ndcg_at_3": "NDCG@3",
    "context_rule_conformance_at_3": "context_rule_conformance@3",
    "precision_at_3": "P@3 (taste match)",
    "mrr": "MRR",
    "unknown_admitted_at_3": "unknown_admitted@3",
    "category_entropy_at_3": "category_entropy@3",
}


def recording_digest(result: LlmArmResult) -> str:
    """Digest of which requests the recording can answer -- machine-independent, unlike its path.

    Changes the moment a fixture is regenerated, added to or removed, so a stale artifact is
    caught by `--check` rather than by someone noticing a number moved.
    """
    document = {
        "files": sorted(result.recording_files),
        "entries": result.recording_entries,
        "model": result.model,
        "synthetic": result.recording_is_synthetic,
    }
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode("utf-8")).hexdigest()


def _stat_document(stat: Stat) -> dict[str, Any]:
    return {
        "mean": stat.mean,
        "ci_low": stat.ci_low,
        "ci_high": stat.ci_high,
        "n": stat.n,
        "n_clusters": stat.n_clusters,
    }


def _delta_document(delta: Delta) -> dict[str, Any]:
    return {
        "mean": delta.mean,
        "ci_low": delta.ci_low,
        "ci_high": delta.ci_high,
        "exercised": delta.exercised,
        "n": delta.n,
        "n_clusters": delta.n_clusters,
        # Stated rather than left to a reader comparing two rounded bounds by eye. Read it as
        # "this interval does not contain zero", never as a p-value.
        "excludes_zero": delta.excludes_zero,
    }


def _rate_document(rate: Rate) -> dict[str, Any]:
    return {"numerator": rate.numerator, "denominator": rate.denominator, "rate": rate.rate}


def _split_document(split: LlmSplitResult, *, synthetic_cost: bool) -> dict[str, Any]:
    base: dict[str, Any] = {
        "n_cases": split.n_cases,
        "recorded_cases": split.recorded_cases,
        "recording_misses": split.misses,
        "status": "recorded" if split.recorded else NOT_RECORDED,
    }
    if not split.recorded:
        # Explicitly null, never zero. A reader (or a chart) must not be able to plot this.
        base.update(
            {
                "metrics": None,
                "deltas_vs_deterministic": None,
                "arm_metrics": None,
                "cost": None,
                "guardrail_rejections_by_rule": None,
            }
        )
        return base

    base.update(
        {
            "metrics": {
                name: _stat_document(split.metrics[name]) for name in sorted(CASE_METRIC_NAMES)
            },
            "deltas_vs_deterministic": {
                name: _delta_document(split.deltas[name]) for name in sorted(CASE_METRIC_NAMES)
            },
            "arm_metrics": {
                "planner_agreement_at_3": _stat_document(split.agreement_at_3),
                "narrowing_rate": _stat_document(split.narrowing_rate),
                "max_promotion_observed": split.max_promotion_observed,
                "guardrail_rejection_rate": _rate_document(split.guardrail_rejection_rate),
                "fallback_rate_by_mode": {
                    mode: _rate_document(split.fallback_rate(mode))
                    for mode in sorted(split.fallback_counts)
                },
            },
            "cost": {
                "is_synthetic": synthetic_cost,
                "latency_p50_ms": split.latency_p50_ms,
                "latency_p95_ms": split.latency_p95_ms,
                "tokens_per_run_mean": split.tokens_per_run_mean,
                "tokens_per_run_p95": split.tokens_per_run_p95,
            },
            "guardrail_rejections_by_rule": dict(
                sorted(guardrail_rejections_by_rule(split).items())
            ),
        }
    )
    return base


def to_json_document(result: LlmArmResult) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "arm": ARM_LLM_RECORDED,
        "generator_version": result.generator_version,
        "seed": result.seed,
        "dataset_digest": result.dataset_digest,
        "weights_digest": weights_digest(),
        "recording_digest": recording_digest(result),
        "not_user_truth": NOT_USER_TRUTH,
        "not_a_model": NOT_A_MODEL,
        "methodology": METHODOLOGY,
        "recording": {
            # Deliberately no absolute path: it would differ per machine and break `--check`.
            "files": sorted(result.recording_files),
            "entries": result.recording_entries,
            "synthetic": result.recording_is_synthetic,
            "model": result.model,
            "banner": result.recording_banner,
        },
        "dataset_summary": {
            "core_personas": len(CORE_PERSONAS),
            "holdout_personas": len(HOLDOUT_PERSONAS),
            "query_templates": [template.name for template in QUERY_TEMPLATES],
        },
        "splits": {
            "core": _split_document(result.core, synthetic_cost=result.recording_is_synthetic),
            "holdout": _split_document(
                result.holdout, synthetic_cost=result.recording_is_synthetic
            ),
        },
    }


def _dumps(document: dict[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, indent=2) + "\n"


def _counts(value: Stat | Delta) -> str:
    """`n` is how many numbers were averaged; `n_clusters` is how many independent things they
    came from. Both, always -- the second is the one that says what the interval is worth."""
    return f"n={value.n}, n_clusters={value.n_clusters}"


def _fmt(stat: Stat) -> str:
    return f"{stat.mean:.4f} [{stat.ci_low:.4f}, {stat.ci_high:.4f}] ({_counts(stat)})"


def _fmt_delta(delta: Delta) -> str:
    if not delta.exercised:
        return "identical on every case"
    verdict = "excludes 0" if delta.excludes_zero else "**includes 0**"
    return (
        f"{delta.mean:+.4f} [{delta.ci_low:+.4f}, {delta.ci_high:+.4f}] "
        f"({_counts(delta)}; {verdict})"
    )


def _fmt_optional(value: object, suffix: str = "") -> str:
    return NOT_RECORDED if value is None else f"{value}{suffix}"


def _split_section(name: str, split: LlmSplitResult, *, synthetic: bool, lines: list[str]) -> None:
    lines.append(f"### {name} set ({split.n_cases} cases)")
    lines.append("")
    lines.append(
        f"Recorded: {split.recorded_cases}/{split.n_cases} cases · recording misses: {split.misses}"
    )
    lines.append("")
    if not split.recorded:
        lines.append(
            f"**{NOT_RECORDED}** -- no request in this split was answered from the recording, so "
            "every metric below would be the deterministic order restated. Nothing is printed "
            "rather than zeros. Regenerate with "
            "`python -m silverloop.evaluation.ranking_llm.synthesise`."
        )
        lines.append("")
        return

    lines.append(f"| Metric | `{ARM_LLM_RECORDED}` | delta vs deterministic `full` |")
    lines.append("|---|---|---|")
    for metric in CASE_METRIC_NAMES:
        lines.append(
            f"| {_METRIC_LABELS[metric]} | {_fmt(split.metrics[metric])} | "
            f"{_fmt_delta(split.deltas[metric])} |"
        )
    lines.append("")

    lines.append("| Arm metric | value |")
    lines.append("|---|---|")
    lines.append(f"| planner_agreement@3 (agent-mode runs) | {_fmt(split.agreement_at_3)} |")
    lines.append(f"| narrowing_rate (agent-mode runs) | {_fmt(split.narrowing_rate)} |")
    lines.append(f"| max_promotion_observed | {split.max_promotion_observed} place(s) |")
    lines.append(
        f"| guardrail_rejection_rate | {split.guardrail_rejection_rate.formatted()} "
        "(rejected proposals / proposals) |"
    )
    for mode in sorted(split.fallback_counts):
        lines.append(f"| fallback_rate[`{mode}`] | {split.fallback_rate(mode).formatted()} |")
    lines.append("")
    lines.append(
        "`agent` is listed among the modes and is not a fallback: every run has exactly one "
        "mode and the modes sum to the case count, so no fallback rate can be quoted without "
        "its denominator."
    )
    lines.append("")

    label = " (SYNTHETIC -- see NOT_A_MODEL)" if synthetic else ""
    lines.append(f"| Cost{label} | value |")
    lines.append("|---|---|")
    lines.append(f"| latency p50 | {_fmt_optional(split.latency_p50_ms, ' ms')} |")
    lines.append(f"| latency p95 | {_fmt_optional(split.latency_p95_ms, ' ms')} |")
    lines.append(f"| tokens per run (mean) | {_fmt_optional(split.tokens_per_run_mean)} |")
    lines.append(f"| tokens per run (p95) | {_fmt_optional(split.tokens_per_run_p95)} |")
    lines.append("")
    lines.append("Cost figures are reported, never asserted: no test gates on them.")
    lines.append("")

    rules = guardrail_rejections_by_rule(split)
    lines.append("| Guardrail rule | rejections |")
    lines.append("|---|---|")
    if rules:
        for rule, count in sorted(rules.items()):
            lines.append(f"| `{rule}` | {count} |")
    else:
        lines.append("| (none bound on this split) | 0 |")
    lines.append("")


def to_markdown(result: LlmArmResult) -> str:
    lines: list[str] = []
    lines.append("# Care+ recorded-LLM ranking arm (`llm_recorded`)")
    lines.append("")
    lines.append(f"**{NOT_A_MODEL}**")
    lines.append("")
    lines.append(f"**{NOT_USER_TRUTH}**")
    lines.append("")
    lines.append(METHODOLOGY)
    lines.append("")
    lines.append(
        f"Generator version: `{result.generator_version}` · Seed: `{result.seed}` · "
        f"Dataset digest: `{result.dataset_digest[:16]}…` · "
        f"Weights digest: `{weights_digest()[:16]}…` · "
        f"Recording digest: `{recording_digest(result)[:16]}…`"
    )
    lines.append("")
    if result.recording_entries:
        lines.append(
            f"Recording: {result.recording_entries} entries across "
            f"{', '.join(f'`{name}`' for name in sorted(result.recording_files))} · "
            f"model `{result.model}` · "
            f"{'synthetic' if result.recording_is_synthetic else 'live provider'}."
        )
    else:
        lines.append(
            f"Recording: **{NOT_RECORDED}** -- no fixture was found. Every split below says so."
        )
    lines.append("")
    _split_section("Core", result.core, synthetic=result.recording_is_synthetic, lines=lines)
    _split_section("Holdout", result.holdout, synthetic=result.recording_is_synthetic, lines=lines)
    return "\n".join(lines) + "\n"


def write_artifacts(result: LlmArmResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / JSON_FILENAME).write_text(_dumps(to_json_document(result)), encoding="utf-8")
    (out_dir / MARKDOWN_FILENAME).write_text(to_markdown(result), encoding="utf-8")


def check_artifacts(result: LlmArmResult, out_dir: Path) -> bool:
    json_path = out_dir / JSON_FILENAME
    markdown_path = out_dir / MARKDOWN_FILENAME
    if not json_path.exists() or not markdown_path.exists():
        return False
    return json_path.read_text(encoding="utf-8") == _dumps(
        to_json_document(result)
    ) and markdown_path.read_text(encoding="utf-8") == to_markdown(result)


__all__ = [
    "JSON_FILENAME",
    "MARKDOWN_FILENAME",
    "NOT_A_MODEL",
    "NOT_RECORDED",
    "SCHEMA_VERSION",
    "check_artifacts",
    "recording_digest",
    "to_json_document",
    "to_markdown",
    "write_artifacts",
]
