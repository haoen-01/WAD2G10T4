"""JSON/Markdown artifact generation and staleness checking for the ranking benchmark (E1),
mirroring `silverloop.evaluation.report`'s determinism discipline: no generation timestamp, only
`generator_version`, `seed`, `dataset_digest` and `weights_digest` as provenance, so `pnpm
evaluate` run twice produces byte-identical output and `--check` never spuriously fails.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from silverloop.activity_search import DECLINE_COOLDOWN_DAYS, RANKING_WEIGHTS
from silverloop.evaluation.ranking import ablations
from silverloop.evaluation.ranking.dataset import (
    CATALOGUE,
    CORE_PERSONAS,
    HOLDOUT_PERSONAS,
    QUERY_TEMPLATES,
)
from silverloop.evaluation.ranking.metrics import Delta, Rate, Stat
from silverloop.evaluation.ranking.runner import (
    HEADLINE_METRIC,
    INFERRED_ONLY_STRATUM,
    REFERENCE_LINES,
    STATED_STRATUM,
)

if TYPE_CHECKING:
    from silverloop.evaluation.ranking.runner import (
        ArmEffect,
        PersonaSummary,
        RankingEvaluationResult,
        SplitResult,
        StratumResult,
    )

SCHEMA_VERSION = 1
JSON_FILENAME = "ranking-evaluation.json"
MARKDOWN_FILENAME = "ranking-evaluation.md"

NOT_USER_TRUTH = (
    "NOT_USER_TRUTH: every persona, listing and observation trace in this benchmark is a "
    "synthetic design artefact authored for this evaluation. No row here is, or is derived from, "
    "a real senior's data, preferences or history. Graded relevance is assigned by a documented "
    "rule applied to an authored persona BRIEF the ranker never sees (see `dataset.py`'s module "
    "docstring); it is a labelling convention, not a fact about anyone."
)

METHODOLOGY = (
    "Each of the 6 query templates is run against every persona in the split, producing one "
    "'case'. The ranker sees only an OBSERVATION TRACE (declines with reasons, enjoyment reports, "
    "interest taps, occasional stated preferences) folded through the production "
    "`apply_decline`/`apply_enjoyment`/`ActivityEngagement`; graded relevance (0-3) is assigned "
    "from the persona's separate, richer BRIEF (hard constraints, stated tastes, stated avoids, "
    "decline history) that the ranker never receives. "
    "Two metrics that were true by construction are no longer reported here at all: "
    "`constraint_satisfaction@3` was `1.0 if top else 0.0` (because "
    "`filter_candidates` removes every hard-constraint violation before anything is graded or "
    "ranked) and `series_duplication_rate@3` was 0.0000 (because `_dedupe_series` always runs). "
    "Both are now unit tests on `activity_search` itself, where a regression would actually fail "
    "something. The headline family is `NDCG@1`, `HitRate@3 (rel=3)` and `slate_ndcg@3`, whose "
    "ideal is computed under the product's own one-per-category slate rule so a within-margin "
    "variety swap is not scored as a loss; graded `NDCG@3` is kept in the technical table. `P@3` "
    "and `MRR` count a grade-3 TASTE MATCH as relevant, not the neutral grade 2: 77.8% of the "
    "core kept pool grades >=2, so the old `P@3 (rel>=2)` measured pool composition. "
    "`context_rule_conformance@3` is a SEPARATE metric from `NDCG@3` (relevance), not a variant "
    "of it: relevance asks whether a listing suits what the persona asked for and has liked "
    "before, graded from a persona brief that is never told about the weather; "
    "`context_rule_conformance@3` asks whether the ranker's top-3 matches a declared rain/"
    "environment rule (`context_labels.py`). That rule intentionally restates the SAME premise "
    "`activity_search.py`'s own `context` factor encodes, so this metric is an implementation-"
    "conformance check -- it shows the factor is wired and behaves as declared -- NOT an "
    "independent judgement of whether that rule is a good idea, and its `no_context` delta must "
    "not be read as evidence for or against the rain nudge itself. "
    "See docs/adr/0003-relevance-vs-context-appropriateness.md."
)


ABLATION_METHODOLOGY = (
    "Two kinds of arm, and the difference matters. A **factor arm** (`factor:<name>`) zeroes "
    "exactly one `ScoreFactor`'s weighted CONTRIBUTION to `total`, leaves every factor VALUE -- "
    "and therefore the hard filter, the tier and the environment-aware rain rule -- exactly as "
    "production computed it, re-sorts on the adjusted totals and re-runs the production "
    "post-scoring passes (`activity_search.postprocess`). Its delta is attributable to that "
    "factor's weight alone. An **input arm** (`input:*`) changes one argument instead; that is "
    'closer to "what if we never had this data", but an input rarely touches exactly one '
    "factor, so each one prints the list of factors it can move. A `no_preference_dim:<D>` arm "
    "drops one learned dimension, which is the only way to separate an axis the ranker reads more "
    "than once. Every arm is compared to its OWN baseline, printed in its header: an arm that "
    "runs with the diversity swap off is compared to `no_diversity`, never to `full`, because a "
    "comparison to `full` folds the swap's own delta into the factor's."
)


def weights_digest() -> str:
    document = {
        "weights": dict(sorted(RANKING_WEIGHTS.items())),
        "decline_cooldown_days": DECLINE_COOLDOWN_DAYS,
    }
    encoded = json.dumps(document, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stat_document(stat: Stat) -> dict[str, object]:
    return {
        "mean": stat.mean,
        "ci_low": stat.ci_low,
        "ci_high": stat.ci_high,
        "n": stat.n,
        "n_clusters": stat.n_clusters,
    }


def _arm_effect_document(effect: ArmEffect) -> dict[str, object]:
    return {
        "baseline": effect.baseline,
        "n_cases": effect.n_cases,
        "scores_changed_cases": effect.scores_changed_cases,
        "order_changed_cases": effect.order_changed_cases,
        "masked": effect.masked,
        "touches": list(ablations.ARM_SPECS[effect.arm].touches),
        "diversity": ablations.ARM_SPECS[effect.arm].diversity,
    }


def _delta_document(delta: Delta) -> dict[str, object]:
    return {
        "mean": delta.mean,
        "ci_low": delta.ci_low,
        "ci_high": delta.ci_high,
        "exercised": delta.exercised,
        "n": delta.n,
        "n_clusters": delta.n_clusters,
        "excludes_zero": delta.excludes_zero,
    }


def _persona_document(summary: PersonaSummary) -> dict[str, object]:
    return {
        "person_id": summary.person_id,
        "n_cases": summary.n_cases,
        "stated": summary.stated,
        "ndcg_at_3": summary.ndcg_at_3,
        "random_ndcg_at_3": summary.random_ndcg_at_3,
        "lift_over_random": summary.lift_over_random,
    }


def _stratum_document(stratum: StratumResult) -> dict[str, object]:
    return {
        "personas": list(stratum.persona_ids),
        "metrics": {name: _stat_document(stat) for name, stat in sorted(stratum.metrics.items())},
        "reference_random": {
            name: _stat_document(stat) for name, stat in sorted(stratum.reference_random.items())
        },
        "lift_over_random": _delta_document(stratum.lift_over_random),
    }


def _rate_document(rate: Rate) -> dict[str, object]:
    return {"numerator": rate.numerator, "denominator": rate.denominator, "rate": rate.rate}


def _split_document(split: SplitResult) -> dict[str, object]:
    return {
        "n_cases": split.n_cases,
        "n_personas": split.n_personas,
        "metrics": {name: _stat_document(stat) for name, stat in sorted(split.metrics.items())},
        "metrics_persona_clustered": {
            name: _stat_document(stat) for name, stat in sorted(split.metrics_clustered.items())
        },
        "reference_lines": {
            line: {name: _stat_document(stat) for name, stat in sorted(stats.items())}
            for line, stats in sorted(split.reference_all.items())
        },
        "discriminable_cases": split.discriminable_cases,
        "metrics_discriminable_persona_clustered": {
            name: _stat_document(stat) for name, stat in sorted(split.metrics_discriminable.items())
        },
        "reference_lines_discriminable_persona_clustered": {
            line: {name: _stat_document(stat) for name, stat in sorted(stats.items())}
            for line, stats in sorted(split.reference_discriminable.items())
        },
        "lift_over_reference_discriminable": {
            line: _delta_document(delta)
            for line, delta in sorted(split.lifts_discriminable.items())
        },
        "reference_lines_persona_clustered": {
            line: {name: _stat_document(stat) for name, stat in sorted(stats.items())}
            for line, stats in sorted(split.reference_clustered.items())
        },
        "lift_over_reference_persona_clustered": {
            line: _delta_document(delta) for line, delta in sorted(split.lifts.items())
        },
        "learning_curve": [
            {
                "arm": point.arm,
                "trace_events": point.trace_events,
                "ndcg_at_1": point.ndcg_at_1,
                "hit_rate_at_3": point.hit_rate_at_3,
                "ndcg_at_3": point.ndcg_at_3,
                "lift_over_random": _delta_document(point.lift_over_random),
            }
            for point in split.learning_curve
        ],
        "cases_to_beat_random": split.cases_to_beat_random,
        "max_trace_events": split.max_trace_events,
        "per_persona": [_persona_document(summary) for summary in split.per_persona],
        "strata": {stratum.name: _stratum_document(stratum) for stratum in split.strata},
        "personalisation_divergence": _stat_document(split.personalisation_divergence),
        "reasons_grounded_rate": _rate_document(split.reasons_grounded),
        "reasons_grounded_rate_macro": _stat_document(split.reasons_grounded_stat),
        "catalogue_filler_reason_lines": split.catalogue_filler_count,
        "ablations": {
            arm: {name: _delta_document(delta) for name, delta in sorted(deltas.items())}
            for arm, deltas in sorted(split.ablation_deltas.items())
        },
        "arm_effects": {
            arm: _arm_effect_document(effect) for arm, effect in sorted(split.arm_effects.items())
        },
        "ablations_persona_clustered": {
            arm: {name: _delta_document(delta) for name, delta in sorted(deltas.items())}
            for arm, deltas in sorted(split.ablation_deltas_clustered.items())
        },
    }


def to_json_document(result: RankingEvaluationResult) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": result.generator_version,
        "seed": result.seed,
        "dataset_digest": result.dataset_digest,
        "holdout_digest": result.holdout_digest,
        "holdout_frozen": result.holdout_frozen,
        "weights_digest": weights_digest(),
        "not_user_truth": NOT_USER_TRUTH,
        "methodology": METHODOLOGY,
        "dataset_summary": {
            "catalogue_size": len(CATALOGUE),
            "core_personas": len(CORE_PERSONAS),
            "holdout_personas": len(HOLDOUT_PERSONAS),
            "query_templates": [template.name for template in QUERY_TEMPLATES],
        },
        "splits": {
            "core": _split_document(result.core),
            "holdout": _split_document(result.holdout),
        },
    }


def _dumps(document: dict[str, object]) -> str:
    return json.dumps(document, sort_keys=True, indent=2) + "\n"


_METRIC_LABELS: dict[str, str] = {
    "ndcg_at_1": "NDCG@1 (is the best thing first)",
    "hit_rate_at_3": "HitRate@3 (rel=3; is a taste match anywhere in the slate)",
    "slate_ndcg_at_3": "slate_ndcg@3 (ideal under the one-per-category rule)",
    "ndcg_at_3": "NDCG@3",
    "context_rule_conformance_at_3": (
        "context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the "
        "ranker's own premise -- NOT independent validation, see METHODOLOGY)"
    ),
    "precision_at_3": "P@3 (taste match)",
    "mrr": "MRR (rel=3)",
    "unknown_admitted_at_3": "unknown_admitted@3",
    "category_entropy_at_3": "category_entropy@3",
}
_CASE_METRIC_ORDER = tuple(_METRIC_LABELS)
_REFERENCE_METRIC_ORDER = (
    "ndcg_at_1",
    "hit_rate_at_3",
    "slate_ndcg_at_3",
    "ndcg_at_3",
    "precision_at_3",
    "mrr",
)
_REFERENCE_LINE_LABELS: dict[str, str] = {
    "random": "random (20 draws)",
    "catalogue_order": "catalogue-order",
    "intent_filter_static": "intent_filter+static",
    "oracle": "oracle",
}


def _counts(stat: Stat | Delta) -> str:
    if stat.n_clusters:
        return f"n={stat.n}, n_clusters={stat.n_clusters}"
    return f"n={stat.n}"


def _fmt(stat: Stat) -> str:
    return f"{stat.mean:.4f} [{stat.ci_low:.4f}, {stat.ci_high:.4f}] ({_counts(stat)})"


def _fmt_delta(delta: Delta) -> str:
    if not delta.exercised:
        return "this dataset does not exercise the factor"
    return f"{delta.mean:+.4f} [{delta.ci_low:+.4f}, {delta.ci_high:+.4f}]"


def _fmt_lift(delta: Delta) -> str:
    verdict = "excludes 0" if delta.excludes_zero else "**includes 0**"
    return f"{_fmt_delta(delta)} ({_counts(delta)}; {verdict})"


def _lift_section(split: SplitResult, lines: list[str]) -> None:
    lines.append(
        "**Headline lift, paired and persona-clustered.** Both arms are measured on the same "
        "cases with the same grade table and the same kept pool, so the difference is paired; and "
        "six cases share one persona, so personas -- not cases -- are what is resampled. Comparing "
        "two marginal CIs instead is the wrong test."
    )
    lines.append("")
    lines.append(f"| `full` minus | {_METRIC_LABELS[HEADLINE_METRIC]} delta |")
    lines.append("|---|---|")
    for line in REFERENCE_LINES:
        lines.append(f"| `{line}` | {_fmt_lift(split.lifts[line])} |")
    lines.append("")
    lines.append("| Stratum | personas | `full` | `random` | lift |")
    lines.append("|---|---|---|---|---|")
    for stratum in split.strata:
        names = ", ".join(f"`{person_id}`" for person_id in stratum.persona_ids) or "--"
        lines.append(
            f"| `{stratum.name}` | {names} | "
            f"{_fmt(stratum.metrics[HEADLINE_METRIC])} | "
            f"{_fmt(stratum.reference_random[HEADLINE_METRIC])} | "
            f"{_fmt_lift(stratum.lift_over_random)} |"
        )
    lines.append("")
    inferred = next(s for s in split.strata if s.name == INFERRED_ONLY_STRATUM)
    lines.append(
        f"**The number to quote is the `{INFERRED_ONLY_STRATUM}` one: "
        f"{_fmt_lift(inferred.lift_over_random)}.** A `{STATED_STRATUM}` persona hands the ranker, "
        "verbatim, one of the exact `(dimension, value)` pairs the grader reads from her brief, so "
        'her cases measure "obey what the person just told you" rather than "infer taste from '
        'behaviour". Both are real product behaviour; only the second is what this benchmark '
        "claims to measure. `eval-mr-koh` states the same SOCIAL fact from the opposite pole "
        "(`solo` stated against a `social` hard avoid) and is counted as inferred-only here -- on "
        "the wider reading the stated stratum is one persona larger."
    )
    lines.append("")


def _reference_table(
    metrics: dict[str, Stat], reference: dict[str, dict[str, Stat]], lines: list[str]
) -> None:
    header = " | ".join(_REFERENCE_LINE_LABELS[line] for line in REFERENCE_LINES)
    lines.append(f"| Metric | full | {header} |")
    lines.append("|---|---|" + "---|" * len(REFERENCE_LINES))
    for name in _REFERENCE_METRIC_ORDER:
        cells = " | ".join(_fmt(reference[line][name]) for line in REFERENCE_LINES)
        lines.append(f"| {_METRIC_LABELS[name]} | {_fmt(metrics[name])} | {cells} |")
    lines.append("")


def _learning_curve_section(split: SplitResult, lines: list[str]) -> None:
    lines.append(
        "**Learning curve.** The same persona, catalogue, query and grade table at every point; "
        "the only thing that varies is how many observation-trace events the ranker has been "
        "given. `cold_start` is the day a person signs up -- no learned preference and no "
        "engagement history, so only `intent`, `context` and `friction` are doing anything."
    )
    lines.append("")
    lines.append("| Arm | trace events | NDCG@1 | HitRate@3 | NDCG@3 | lift over random |")
    lines.append("|---|---|---|---|---|---|")
    for point in split.learning_curve:
        events = "all" if point.trace_events < 0 else str(point.trace_events)
        lines.append(
            f"| `{point.arm}` | {events} | {point.ndcg_at_1:.4f} | {point.hit_rate_at_3:.4f} | "
            f"{point.ndcg_at_3:.4f} | {_fmt_lift(point.lift_over_random)} |"
        )
    lines.append("")
    if split.cases_to_beat_random is None:
        verdict = (
            "**`cases_to_beat_random`: never.** No prefix length on this split reaches a paired, "
            "persona-clustered CI over the random floor that excludes zero -- including the full "
            "trace."
        )
    else:
        verdict = (
            f"**`cases_to_beat_random`: {split.cases_to_beat_random}.** That many "
            "observation-trace events are needed before the paired, persona-clustered CI over "
            "the random floor excludes zero."
        )
    lines.append(verdict)
    lines.append("")
    lines.append(
        f"The longest trace in this split is {split.max_trace_events} event(s), so every prefix "
        f"length above that is the full trace under another name and the curve is flat there by "
        "construction -- not evidence that more evidence would not help. `first_signal` and "
        "`trace_prefix:1` are the same manipulation under two names and must agree exactly."
    )
    lines.append("")


def _per_persona_section(split: SplitResult, lines: list[str]) -> None:
    lines.append("**Per persona.** A macro mean hides its own worst case; these are the cases.")
    lines.append("")
    lines.append("| Persona | cases | stated? | full NDCG@3 | random NDCG@3 | lift |")
    lines.append("|---|---|---|---|---|---|")
    for summary in split.per_persona:
        lines.append(
            f"| `{summary.person_id}` | {summary.n_cases} | "
            f"{'yes' if summary.stated else 'no'} | {summary.ndcg_at_3:.4f} | "
            f"{summary.random_ndcg_at_3:.4f} | {summary.lift_over_random:+.4f} |"
        )
    lines.append("")
    below = [s.person_id for s in split.per_persona if s.lift_over_random < 0]
    if below:
        lines.append(
            f"{len(below)} of {split.n_personas} personas score BELOW a random shuffle here: "
            + ", ".join(f"`{person_id}`" for person_id in below)
            + "."
        )
        lines.append("")


def _headline_section(split_name: str, split: SplitResult, lines: list[str]) -> None:
    lines.append(f"### {split_name} set ({split.n_cases} cases, {split.n_personas} personas)")
    lines.append("")
    _lift_section(split, lines)
    _per_persona_section(split, lines)
    _learning_curve_section(split, lines)
    _reference_table(split.metrics, split.reference_all, lines)
    lines.append(
        "The same rows with the CI resampled over PERSONAS rather than cases. Six cases share one "
        "persona's trace, preference store and grade table, so the per-case interval above is "
        "roughly 2.2x too narrow; this is the honest width."
    )
    lines.append("")
    _reference_table(split.metrics_clustered, split.reference_clustered, lines)
    lines.append(
        f"**Discriminable cases: {split.discriminable_cases}/{split.n_cases}.** A case counts "
        "here when its ordering can change the headline metric at all -- when the best and the "
        "worst ordering of its kept pool score differently, which on this dataset is exactly the "
        "cases whose kept candidates do not all carry the same grade. The rest score identically "
        "under every ordering and drag the headline toward the pool's own composition. This "
        f'stratum used to be defined as "holds a grade-3 AND something graded <=1", a much '
        "narrower rule justified by the same sentence: on core that dropped 21 of the 51 cases "
        "whose ordering demonstrably matters, on holdout 14 of 24, and it took whole personas out "
        "of the headline with them. The same rows over the discriminable cases only, "
        "persona-clustered:"
    )
    lines.append("")
    if split.discriminable_cases == split.n_cases:
        lines.append(
            "**Every case in this split is discriminable, so this stratum is the split and the "
            "table below restates the persona-clustered one above.** Any difference between the "
            "two numbers would be a bug, not a finding."
        )
        lines.append("")
    _reference_table(split.metrics_discriminable, split.reference_discriminable, lines)
    lines.append(f"| `full` minus (discriminable only) | {_METRIC_LABELS[HEADLINE_METRIC]} delta |")
    lines.append("|---|---|")
    for line in REFERENCE_LINES:
        lines.append(f"| `{line}` | {_fmt_lift(split.lifts_discriminable[line])} |")
    lines.append("")
    lines.append("| Metric | value (per-case CI) | value (persona-clustered CI) |")
    lines.append("|---|---|---|")
    for name in _CASE_METRIC_ORDER:
        if name in _REFERENCE_METRIC_ORDER:
            continue
        lines.append(
            f"| {_METRIC_LABELS[name]} | {_fmt(split.metrics[name])} | "
            f"{_fmt(split.metrics_clustered[name])} |"
        )
    lines.append(
        f"| personalisation_divergence (clustered by unordered persona PAIR) | -- | "
        f"{_fmt(split.personalisation_divergence)} |"
    )
    lines.append(f"| reasons_grounded_rate (pooled) | {split.reasons_grounded.formatted()} | -- |")
    lines.append(
        f"| reasons_grounded_rate (macro-averaged per case, bootstrap CI) | "
        f"{_fmt(split.reasons_grounded_stat)} | -- |"
    )
    lines.append(
        f"| catalogue filler reason lines (not counted above) | "
        f"{split.catalogue_filler_count} | -- |"
    )
    lines.append("")


def _fmt_arm_delta(delta: Delta, effect: ArmEffect) -> str:
    """A zero delta reads as one of three different findings, and the artifact names which."""
    if delta.exercised:
        return _fmt_delta(delta)
    if effect.scores_changed_cases == 0:
        return "this dataset does not exercise the factor"
    if effect.order_changed_cases == 0:
        return (
            f"masked by the tier sort (`intent` + `repetition`): the arm moved a weighted "
            f"contribution on {effect.scores_changed_cases}/{effect.n_cases} case(s) and the "
            f"ranked order never changed"
        )
    return (
        f"masked by this metric: the order changed on {effect.order_changed_cases}/"
        f"{effect.n_cases} case(s) without moving this number"
    )


def _ablation_section(split_name: str, split: SplitResult, lines: list[str]) -> None:
    lines.append(
        f"### Ablations -- {split_name} set (paired delta vs each arm's own baseline; "
        f"{split.n_cases} cases from {split.n_personas} personas)"
    )
    lines.append("")
    for arm in ablations.ABLATION_ARMS:
        if arm == ablations.ARM_FULL:
            continue
        spec = ablations.ARM_SPECS[arm]
        effect = split.arm_effects[arm]
        deltas = split.ablation_deltas[arm]
        clustered = split.ablation_deltas_clustered[arm]
        touches = ", ".join(f"`{name}`" for name in spec.touches) or "no scoring factor"
        lines.append(f"**`{arm}`** -- measured against `{spec.baseline}`; touches {touches}.")
        lines.append("")
        lines.append(spec.description)
        lines.append("")
        lines.append("| Metric | delta (per-case CI) | delta (persona-clustered CI) |")
        lines.append("|---|---|---|")
        for name in _CASE_METRIC_ORDER:
            lines.append(
                f"| {_METRIC_LABELS[name]} | {_fmt_arm_delta(deltas[name], effect)} | "
                f"{_fmt_arm_delta(clustered[name], effect)} |"
            )
        lines.append("")


def to_markdown(result: RankingEvaluationResult) -> str:
    lines: list[str] = []
    lines.append("# Care+ activity-ranking evaluation")
    lines.append("")
    lines.append(f"**{NOT_USER_TRUTH}**")
    lines.append("")
    lines.append(METHODOLOGY)
    lines.append("")
    lines.append(
        f"Generator version: `{result.generator_version}` · Seed: `{result.seed}` · "
        f"Dataset digest: `{result.dataset_digest[:16]}…` · "
        f"Weights digest: `{weights_digest()[:16]}…` · "
        f"Holdout digest: `{result.holdout_digest[:16]}…` · "
        f"holdout_frozen: `{str(result.holdout_frozen).lower()}`"
    )
    lines.append("")
    lines.append(
        f"Catalogue: {len(CATALOGUE)} listings · {len(CORE_PERSONAS)} core / "
        f"{len(HOLDOUT_PERSONAS)} holdout personas · {len(QUERY_TEMPLATES)} query templates."
    )
    lines.append("")
    lines.append(
        "Core and holdout are reported separately and never pooled: holdout personas were never "
        "consulted while any ranking factor, weight or this dataset's own design was built. "
        "`holdout_frozen` says whether those four persona briefs still hash to the digest they "
        "were frozen at (`dataset.HOLDOUT_FROZEN_DIGEST`); a change to them is not forbidden, it "
        "is visible, and a genuine change belongs in a new set rather than under these numbers."
    )
    lines.append("")

    lines.append("## Headline: full ranker vs reference lines")
    lines.append("")
    _headline_section("Core", result.core, lines)
    _headline_section("Holdout", result.holdout, lines)

    lines.append("## Ablations: which factor is load-bearing on this dataset?")
    lines.append("")
    lines.append(ABLATION_METHODOLOGY)
    lines.append("")
    _ablation_section("Core", result.core, lines)
    _ablation_section("Holdout", result.holdout, lines)

    return "\n".join(lines) + "\n"


def write_artifacts(result: RankingEvaluationResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / JSON_FILENAME).write_text(_dumps(to_json_document(result)), encoding="utf-8")
    (out_dir / MARKDOWN_FILENAME).write_text(to_markdown(result), encoding="utf-8")


def check_artifacts(result: RankingEvaluationResult, out_dir: Path) -> bool:
    json_path = out_dir / JSON_FILENAME
    markdown_path = out_dir / MARKDOWN_FILENAME
    if not json_path.exists() or not markdown_path.exists():
        return False
    expected_json = _dumps(to_json_document(result))
    expected_markdown = to_markdown(result)
    return (
        json_path.read_text(encoding="utf-8") == expected_json
        and markdown_path.read_text(encoding="utf-8") == expected_markdown
    )
