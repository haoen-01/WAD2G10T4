"""JSON/Markdown artifact generation and staleness checking (D7).

Artifacts are committed to `docs/evaluation/` and contain no generation timestamp -- only
`harness_version`, `seed` and the two `scenario_digest`s (sha256 over sorted YAML bytes) as
provenance -- so that `pnpm evaluate` run twice produces byte-identical output and `--check` does
not spuriously fail on every run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from silverloop.evaluation.funnel import Funnel
from silverloop.evaluation.ladder import GATE_DESCRIPTIONS, GATE_NAMES, GATE_RAIN_CONTEXT
from silverloop.evaluation.latent_labels import LabelAgreement, StepLabels
from silverloop.evaluation.metrics import (
    ACTION,
    DecisionRecord,
    HardViolation,
    PolicyMetrics,
    Rate,
    aggregate,
    coverage,
    evaluate_violations,
)
from silverloop.evaluation.sweep import SweepRow
from silverloop.fixtures import persona_profile
from silverloop.models import Decision

if TYPE_CHECKING:
    from silverloop.evaluation.runner import EvaluationResult

SCHEMA_VERSION = 4
JSON_FILENAME = "policy-comparison.json"
MARKDOWN_FILENAME = "policy-comparison.md"

NOT_CLINICAL_LABEL = "Seeded software-policy simulation; not clinical validation."

ABLATION_REFERENCE_NAME = "silverloop_all_gates"

BUDGET_NOTE = (
    "The headline table is **budget-matched**: the harness applies the identical weekly contact "
    "cap to every policy, converting a would-be contact into `suppress` once the budget is spent. "
    "Without this, the comparison rewarded Care+ for having a cap rather than for choosing "
    "better, and it counted `contact_cap_breach` against `contextual_rule`, which has no cap by "
    "construction -- an exam it was built to fail. The uncapped arm is kept below so the size of "
    "the budget effect stays visible, but it is not the headline and `contact_cap_breach` there "
    "describes behaviour rather than scoring judgement."
)

COVERAGE_NOTE = (
    "**Every rate carries its own coverage, and none carries a confidence interval.** A rate is "
    "printed as `0/19 (0.00%) across 3 scenarios, 2 personas`: the counts are the distinct "
    "scenarios and people the denominator was drawn from. They are there instead of a bootstrap "
    "interval, not as a step towards one. The steps inside a scenario are serially dependent by "
    "construction -- day 3 of a decline exists only because days 1 and 2 did -- and the scenarios "
    "themselves are hand-written from a handful of personas, so resampling them would "
    "manufacture a sampling distribution that the design of this harness does not have. The two "
    "counts answer the question a CI would only appear to answer: how much independent evidence "
    "sits behind the number. Where a rate reads `n/1 scenario`, it is one scripted week's "
    "opinion and must be read as one."
)

LABELLING_RULE = (
    "Ground-truth labels are world state, assigned from the replayed environment by a single "
    "rule applied identically to core and holdout: consent inactive -> `no_consent`; wear-time "
    "below the 8h minimum -> `unusable_data`; a dip under an unrefuted rain explanation -> "
    "`explained_dip`; otherwise, against the person's own ANCHORED median -- what was typical for "
    "them when observation began, not the rolling window -- better than -20% -> `stable`, worse "
    "with fewer than three consecutive valid-wear low days -> `emerging_decline`, three or more "
    "-> `persistent_decline`."
)

LABELLING_ANCHOR_NOTE = (
    'Why the labels anchor. The rule originally read "against the person\'s own median", meaning '
    "the rolling one. That inherits the exact defect the baseline clamp exists to fix: a person "
    "whose activity falls and stays down drags their rolling median down with them, so by roughly "
    "day 17 of a sustained 56% decline the rule would label them `stable` and score any outreach "
    "as unnecessary contact. The ground truth would have marked the fix as a regression. Anchoring "
    "the label to what was typical when observation began is a no-op for every short scenario -- "
    "where the two medians agree -- and is the only reading under which a long decline can be "
    "labelled honestly at all."
)

LABELLING_CAVEAT = (
    "Honest caveat: the rule above shares **three predicates**, not one threshold, with the "
    "ladder it is used to score.\n\n"
    "| Label predicate | Ladder predicate reading the same value | Independent? |\n"
    "|---|---|---|\n"
    "| `unusable_data` = `not signal.quality.safe_to_interpret` | `ladder.py` data-quality gate, "
    "the identical expression | **No** |\n"
    "| `persistent_decline` = `sustained_low_days >= 3` | the escalation gate's "
    "`sustained_low_days >= ESCALATION_DAYS` (= 3) | **No** |\n"
    "| the -20% boundary between `stable` and `emerging_decline` | the nudge rung's own severity "
    "threshold | **No** |\n"
    "| `explained_dip` = rainy and at or past the -20% boundary | the rain gate, which also "
    "requires `sustained_low_days < 2` and so expires after one day | Yes |\n"
    "| `no_consent` = consent inactive | the consent gate | Yes, but it is a fact about "
    "permission, not a judgement either side could get wrong |\n\n"
    'An earlier version of this paragraph claimed the opposite -- that "everything either side '
    'of the boundary (rain, consent, wear-time, persistence, escalation) is independent". '
    "Wear-time and persistence are not, and the consequence is concrete: every "
    "`persistent_decline` step is by construction a step where the escalation predicate already "
    "holds, so M2 and M3 can only be non-zero through a consent, quality or contact-cap "
    "interception. Care+'s `0/19` on both is therefore a narrower claim than it looks. The "
    "`world:` latent labels below are the second, genuinely separate account of the same days "
    "that this table is the argument for."
)

WORLD_LABEL_NOTE = (
    "**Two label columns, and the number that says whether the second one is real.** "
    "`label_authored` is the hand-written `labels:` entry, unchanged. `label_latent` is "
    "`label_from_latent` applied to the scenario's additive `world:` block -- the author's "
    "statement of what the person's day actually was (how much of their own norm they really "
    "did, what drove it, how long it had run, whether the device saw it), written without "
    "reference to any generated number. The latent's cut points -- above 0.80 of the person's "
    "norm is not low; three consecutive low days is persistent -- are definitions of the "
    "fictional world and are tuned to nothing.\n\n"
    "`label_feature_agreement` is the share of steps where `label_latent` matches the "
    "signal-derived rule. **A value of 1.000 would mean the second label source has collapsed "
    "back onto the first and the harness is a tautology again, with extra steps.** It must be "
    "read as a diagnostic with a target below 100%, never as a score to maximise: the two "
    "accounts are supposed to part company where measurement and truth part company, and every "
    "step at which they do is listed below rather than reconciled away.\n\n"
    "What the latent does NOT yet do: it does not generate the observed numbers. The event table "
    "in `simulation.py` is still what the wearable reports, unchanged to the byte, and the "
    "latent is advanced beside it rather than through it (`simulation.replay` moves the world "
    "first, then observes it, and `_observe` carries a seeded noise channel that is off for every "
    "committed artifact). So the two accounts are consistent by authoring, not by construction -- "
    "which is exactly why the agreement rate has to be printed instead of assumed."
)

NOT_MEASURED: tuple[tuple[str, str], ...] = (
    (
        "Device-failure discrimination",
        "There is no `DEVICE_TASK` member in `Decision`; adding one would change the OpenAPI "
        "contract, which is out of scope for this harness.",
    ),
    (
        "Intervention-adaptation rate",
        "Requires `learning.py` and recorded outcomes inside the replay loop, which this "
        "harness does not run.",
    ),
    (
        "Event-to-decision latency",
        "A wall-clock measurement; introducing it would break the harness's determinism.",
    ),
    (
        "Tool-failure recovery",
        "Requires the agent/tool-calling layer, which sits outside the deterministic policy "
        "boundary this harness evaluates.",
    ),
    (
        "Message wording quality",
        "The harness never calls the LLM planner. The comparison is about the policy ladder, so "
        "the planner is excluded to keep every number reproducible from a frozen seed.",
    ),
)

_METRIC_HEADER = (
    "| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | "
    "M3 missed escalation | M4 no-action logging integrity | "
    "M6 unwarranted share of contacts made | M5 violations (steps) |"
)
_METRIC_DIVIDER = "|---|---|---|---|---|---|---|---|"

_RESTRAINT_HEADER = (
    "| Policy | M8 unsupported restraint | M2 missed persistent change | "
    "M7 correct restraint (restates M1) | M9 explanation coverage (logging check) |"
)
_RESTRAINT_DIVIDER = "|---|---|---|---|---|"

RESTRAINT_NOTE = (
    "**Methodology.** M4 (`no_action_logging_integrity`, formerly `audited_no_action`) and M9 "
    "(`restraint_explanation_coverage`) check that a decision carries a rationale and a quality "
    "evidence id -- a property of the logging pipeline, not of whether the silence was correct. "
    "M9 is the identical predicate as M4, just scoped to `NO_ACTION` alone instead of every "
    "`QUIET` decision. Care+'s own ladder populates both fields on every branch, so **M4 and "
    "M9 both read 100% for it in every arm by construction**, regardless of whether any individual "
    "decision was right -- they are logging smoke tests, not correctness scores, and are retained "
    "under that honest label rather than deleted. The baselines' M9 (0% for `fixed_threshold`, "
    "part-way for `contextual_rule`) is not a restraint-quality finding either: it reflects which "
    "of their hardcoded `NO_ACTION` branches happen to include prose in `baselines.py`, not how "
    "sound their silence was.\n\n"
    "**M7 correct restraint** and **M8 unsupported restraint** are the ground-truth-scored "
    "metrics in this family: M7 is `NO_ACTION` / steps where the label says outreach was "
    "unnecessary (`stable`/`explained_dip`, M1's denominator); M8 is `NO_ACTION` / steps where the "
    "label says outreach was required (`persistent_decline`, M2's denominator -- shown beside M8 "
    "below so a reader can see directly whether they diverge; they do exactly when `SUPPRESS` "
    "appears on a `persistent_decline` step, since M2 counts `SUPPRESS` as missed and M8 does "
    "not). `SUPPRESS` never counts toward M7 or M8's numerators -- it means consent or the contact "
    "budget blocked a contact the policy wanted to make, which is a different failure mode from "
    "the policy concluding, in its own rationale, that nothing was wrong -- and "
    "`COORDINATOR_REVIEW` / any `CONTACT` decision is excluded from both by definition (neither is "
    "`NO_ACTION`).\n\n"
    "**M7 is an identity of M1 whenever `SUPPRESS` is absent.** On M1's own denominator, every "
    "step is exactly `ACTION` (M1's numerator), `NO_ACTION` (M7's numerator) or `SUPPRESS`, so "
    "`M7 = 1 - M1 - suppress_share`. M7 only carries information beyond M1 when `SUPPRESS` is "
    "non-zero on `stable`/`explained_dip` steps; on every arm and scenario set this harness has "
    "replayed, no policy `SUPPRESS`es on those steps, so M7 restates M1's complement rather than "
    "measuring something new -- see `docs/adr/0002-replace-audited-no-action.md` for the numbers "
    "this was checked against."
)


def _metric_row(name: str, metrics: PolicyMetrics) -> str:
    return (
        f"| `{name}` | {metrics.sample_size} | {metrics.unnecessary_contact.formatted()} | "
        f"{metrics.missed_persistent_change.formatted()} | "
        f"{metrics.missed_escalation.formatted()} | "
        f"{metrics.no_action_logging_integrity.formatted()} | "
        f"{metrics.unwarranted_contact_share.formatted()} | "
        f"{metrics.violation_total} ({metrics.violating_step_count} step(s)) |"
    )


def _restraint_row(name: str, metrics: PolicyMetrics) -> str:
    return (
        f"| `{name}` | {metrics.unsupported_restraint.formatted()} | "
        f"{metrics.missed_persistent_change.formatted()} | "
        f"{metrics.correct_restraint.formatted()} | "
        f"{metrics.restraint_explanation_coverage.formatted()} |"
    )


def _person_ids(result: EvaluationResult) -> list[str]:
    """Every `person_id` seen in the core replay, in first-seen order. All policies replay the
    identical scenario/person_id sequence (D2), so any one policy's ledger would do; iterating
    all of them is just defensive.
    """
    seen: dict[str, None] = {}
    for records in result.records.values():
        for record in records:
            seen.setdefault(record.person_id, None)
    return list(seen)


def _holdout_person_ids(result: EvaluationResult) -> list[str]:
    arm = result.arms.get("holdout/uncapped")
    if arm is None:
        return []
    seen: dict[str, None] = {}
    for records in arm.records.values():
        for record in records:
            seen.setdefault(record.person_id, None)
    return list(seen)


def _persona_metrics(result: EvaluationResult) -> dict[str, dict[str, PolicyMetrics]]:
    """Per-persona metrics for every policy (F5). `aggregate` already accepts an arbitrary
    `DecisionRecord` iterable; grouping by `person_id` here does not require any change to it.
    """
    return {
        person_id: {
            name: aggregate(
                name,
                result.metrics[name].version,
                [record for record in records if record.person_id == person_id],
            )
            for name, records in result.records.items()
        }
        for person_id in _person_ids(result)
    }


def _rate_document(rate: Rate) -> dict[str, object]:
    return {
        "numerator": rate.numerator,
        "denominator": rate.denominator,
        "rate": rate.rate,
        "scenarios": rate.scenarios,
        "personas": rate.personas,
    }


def _metrics_document(metrics: PolicyMetrics) -> dict[str, object]:
    return {
        "version": metrics.version,
        "sample_size": metrics.sample_size,
        "unnecessary_contact": _rate_document(metrics.unnecessary_contact),
        "missed_persistent_change": _rate_document(metrics.missed_persistent_change),
        "missed_escalation": _rate_document(metrics.missed_escalation),
        "no_action_logging_integrity": _rate_document(metrics.no_action_logging_integrity),
        "correct_restraint": _rate_document(metrics.correct_restraint),
        "unsupported_restraint": _rate_document(metrics.unsupported_restraint),
        "restraint_explanation_coverage": _rate_document(metrics.restraint_explanation_coverage),
        "unwarranted_contact_share": _rate_document(metrics.unwarranted_contact_share),
        "budget_withheld": metrics.budget_withheld,
        "escalates": metrics.escalates,
        "burden": {
            "contacts": metrics.burden.contacts,
            "person_days": metrics.burden.person_days,
            "person_weeks": metrics.burden.person_weeks,
            "contacts_per_person_week": metrics.burden.contacts_per_person_week,
            "max_consecutive_contact_days": metrics.burden.max_consecutive_contact_days,
            "max_consecutive_contact_scenario": (
                metrics.burden.max_consecutive_contact_scenario or None
            ),
            "escalations_per_case": _rate_document(metrics.burden.escalations_per_case),
        },
        "violation_total": metrics.violation_total,
        "violating_step_count": metrics.violating_step_count,
        "violations_by_type": {
            violation.value: count for violation, count in metrics.violations_by_type.items()
        },
        "consent_not_recorded": metrics.consent_not_recorded,
        "contact_volume": metrics.contact_volume,
        "human_review_count": metrics.human_review_count,
        "decision_counts": {
            decision.value: count for decision, count in metrics.decision_counts.items()
        },
    }


def _ledger_entry(record: DecisionRecord) -> dict[str, object]:
    return {
        "scenario": record.scenario,
        "step": record.step,
        "person_id": record.person_id,
        "event": record.event,
        "label": record.label.value,
        "decision": record.decision.value,
        "support_priority": record.support_priority,
        "rationale": list(record.rationale),
        "consent_active": record.consent_active,
        "confidence": round(record.confidence, 4),
        "quality_evidence_id": record.quality_evidence_id,
        "interventions_last_7_days": record.interventions_last_7_days,
        "budget_withheld": record.budget_withheld,
        "violations": [violation.value for violation in evaluate_violations(record)],
    }


def _ablation_delta(result: EvaluationResult, scenario_set: str, policy: str) -> int:
    """How many replayed steps this ablation decided differently from the all-gates-on reference.

    A gate can change decisions without moving any headline rate -- the consent gate does exactly
    that on the core set, because the only step with revoked consent also has unusable wear-time,
    so the data-quality gate catches it either way. Counting changed steps says so out loud
    instead of letting an unchanged M1 imply the gate does nothing.
    """
    arm = result.arms.get(f"{scenario_set}/ablation")
    if arm is None or policy not in arm.records:
        return 0
    reference = arm.records[ABLATION_REFERENCE_NAME]
    candidate = arm.records[policy]
    return sum(
        1
        for left, right in zip(candidate, reference, strict=True)
        if left.decision != right.decision
    )


RAIN_ABLATION_NAME = f"silverloop_no_{GATE_RAIN_CONTEXT}"

CONTEXT_DEPENDENT_RESTRAINT_NOTE = (
    "M10 context-dependent restraint. Denominator: every step Care+ (all gates on) decided "
    "`NO_ACTION`. Numerator: of those, how many become a `CONTACT` or `COORDINATOR_REVIEW` "
    "decision once the rain-context gate alone is switched off (`silverloop_no_rain_context`, the "
    "same ablation arm as the table above). This is the one restraint metric that does not read "
    "the scenario's ground-truth label: it asks how much of Care+'s silence is actually load-"
    "bearing on the rain explanation specifically, as opposed to some other gate (confidence, "
    "persistence, the interpretable-scale floor) that would have kept it quiet regardless. A low "
    "rate here does not mean the rain gate is useless -- it means most of the reference's "
    "`NO_ACTION`s on this set have another sufficient reason to stay quiet, which the ablation "
    "table's `steps changed` / `outreach unblocked` split above already shows directly."
)


def _context_dependent_restraint(result: EvaluationResult, scenario_set: str) -> Rate:
    """M10. See `CONTEXT_DEPENDENT_RESTRAINT_NOTE` for the precise numerator/denominator."""
    arm = result.arms.get(f"{scenario_set}/ablation")
    if arm is None or RAIN_ABLATION_NAME not in arm.records:
        return Rate(numerator=0, denominator=0)
    reference = arm.records[ABLATION_REFERENCE_NAME]
    without_rain_gate = arm.records[RAIN_ABLATION_NAME]
    quiet_steps = [record for record in reference if record.decision == Decision.NO_ACTION]
    without_rain_gate_by_key = {
        (record.scenario, record.step): record for record in without_rain_gate
    }
    numerator = sum(
        1
        for record in quiet_steps
        if without_rain_gate_by_key[(record.scenario, record.step)].decision in ACTION
    )
    scenarios, personas = coverage(quiet_steps)
    return Rate(
        numerator=numerator,
        denominator=len(quiet_steps),
        scenarios=scenarios,
        personas=personas,
    )


def _context_dependent_restraint_section(
    result: EvaluationResult, scenario_set: str, lines: list[str]
) -> None:
    rate = _context_dependent_restraint(result, scenario_set)
    lines.append(f"### Context-dependent restraint -- {scenario_set} set")
    lines.append("")
    lines.append(CONTEXT_DEPENDENT_RESTRAINT_NOTE)
    lines.append("")
    lines.append(f"M10: {rate.formatted()}")
    lines.append("")


def _label_row_document(row: StepLabels) -> dict[str, object]:
    return {
        "scenario_set": row.scenario_set,
        "scenario": row.scenario,
        "step": row.step,
        "person_id": row.person_id,
        "event": row.event,
        "label_authored": row.label_authored.value,
        "label_signal": row.label_signal.value,
        "label_latent": row.label_latent.value if row.label_latent else None,
    }


def _label_agreement_document(agreement: LabelAgreement) -> dict[str, object]:
    return {
        "note": WORLD_LABEL_NOTE,
        "label_feature_agreement": _rate_document(agreement.feature_agreement),
        "authored_vs_signal_agreement": _rate_document(agreement.authored_signal_agreement),
        "scenarios_without_world_block": list(agreement.scenarios_without_world),
        "feature_disagreements": [
            _label_row_document(row) for row in agreement.feature_disagreements()
        ],
        "latent_vs_authored_disagreements": [
            _label_row_document(row) for row in agreement.latent_vs_authored_disagreements()
        ],
        "authored_vs_signal_disagreements": [
            _label_row_document(row) for row in agreement.authored_disagreements()
        ],
        "steps": [_label_row_document(row) for row in agreement.rows],
    }


def _label_agreement_section(result: EvaluationResult, lines: list[str]) -> None:
    agreement = result.label_agreement
    lines.append("### Latent world labels (M24)")
    lines.append("")
    lines.append(WORLD_LABEL_NOTE)
    lines.append("")
    lines.append(f"`label_feature_agreement`: **{agreement.feature_agreement.formatted()}**")
    lines.append("")
    lines.append(
        "`label_authored` vs the signal-derived rule: "
        f"{agreement.authored_signal_agreement.formatted()}. This used to be asserted equal by "
        "`test_documented_ground_truth_rule_reproduces_every_scenario_label`, which is what "
        "pinned every hand-written label to `analytics.py` and `quality.py` for good. The test "
        "now reports this rate and lists any disagreement instead of failing on it."
    )
    lines.append("")

    missing = agreement.scenarios_without_world
    if missing:
        lines.append(
            "Scenarios with no authored `world:` block (no `label_latent`, excluded from the "
            "agreement denominator): " + ", ".join(f"`{name}`" for name in missing) + "."
        )
    else:
        lines.append("Every replayed scenario carries an authored `world:` block.")
    lines.append("")

    disagreements = agreement.feature_disagreements()
    if not disagreements:
        lines.append(
            "**No step disagrees.** At 1.000 the latent labels are not an independent account of "
            "anything; treat every ground-truth-scored metric below as pinned to the signal "
            "pipeline until a scenario is authored that the two rules read differently."
        )
        lines.append("")
        return

    lines.append(
        f"The {len(disagreements)} step(s) where the authored world and the signal-derived rule "
        "disagree -- listed, not reconciled:"
    )
    lines.append("")
    lines.append("| Step | Event | `label_authored` | signal rule | `label_latent` |")
    lines.append("|---|---|---|---|---|")
    for row in disagreements:
        latent = row.label_latent.value if row.label_latent else "n/a"
        lines.append(
            f"| `{row.scenario_set}/{row.scenario}` step {row.step} | `{row.event}` | "
            f"`{row.label_authored.value}` | `{row.label_signal.value}` | `{latent}` |"
        )
    lines.append("")


BURDEN_NOTE = (
    "**What the policy cost, as opposed to whether it was right.** Two policies can reach "
    "identical M1 and M2 and still differ in whether their contacts arrived on four consecutive "
    "mornings or spread across a month, and in whether one coordinator concern cost one "
    "escalation or sixteen. `contact_volume` alone is blind to both, so each burden number "
    "carries its denominator.\n\n"
    "- `contacts_per_person_week` -- contacts over the person-weeks actually replayed. One "
    "replayed step is one of the person's simulated days, so a 9-event scenario is 9 "
    "person-days.\n"
    "- `max_consecutive_contact_days` -- the longest unbroken run of contacted days inside a "
    "single scenario, with the scenario named. Runs never cross a scenario boundary: two "
    "scenarios are two different weeks of two possibly different people.\n"
    "- `escalations_per_case` -- escalation DECISIONS per escalation EPISODE, an episode being a "
    "maximal run of escalations on consecutive simulated days. This is the harness's stand-in "
    "for the product's rule that a case is refreshed rather than duplicated; anything above 1.0 "
    "is the coordinator-side cost of re-raising a concern already raised."
)


def _burden_section(result: EvaluationResult, scenario_set: str, lines: list[str]) -> None:
    arm = result.arms[f"{scenario_set}/capped"]
    lines.append(f"### Burden -- {scenario_set} set, budget-matched")
    lines.append("")
    lines.append(BURDEN_NOTE)
    lines.append("")
    lines.append(
        "| Policy | Contacts per person-week | Longest run of contacted days | "
        "Escalations per case |"
    )
    lines.append("|---|---|---|---|")
    for name, metrics in arm.metrics.items():
        burden = metrics.burden
        run = (
            f"{burden.max_consecutive_contact_days} (`{burden.max_consecutive_contact_scenario}`)"
            if burden.max_consecutive_contact_days
            else "0 (never contacted)"
        )
        lines.append(
            f"| `{name}` | {burden.formatted_contacts_per_person_week()} | {run} | "
            f"{burden.formatted_escalations_per_case()} |"
        )
    lines.append("")


FUNNEL_NOTE = (
    '**`accepted` means "show me more" and nothing else.** The product records that distinction '
    "everywhere; the policy harness was not measuring it at all, so a policy producing twenty "
    "taps and no attendance scored identically to one producing two attendances. Each stage is "
    "`n/d` of the stage BEFORE it, never a share of the top.\n\n"
    "The `outcomes:` block is authored per scenario, one optional entry per event, and says what "
    "the person does IF contacted on that day -- a counterfactual fact about them, in the same "
    "spirit as `world:`, not a record of what any policy did. That is what keeps this from "
    "scoring Care+ against its own output. A step nobody contacted never enters the "
    "denominator, so a quieter policy offers less and is measured on less; a contact made on a "
    "day with no authored outcome is counted separately as an unauthored offer, because an "
    "unauthored day is missing data and treating it as silence would invent a refusal."
)


def _funnel_document(funnel: Funnel) -> dict[str, object]:
    return {
        "offered": funnel.offered,
        "unauthored_offers": funnel.unauthored_offers,
        "scenarios": funnel.scenarios,
        "personas": funnel.personas,
        "responded": _rate_document(funnel.responded),
        "accepted": _rate_document(funnel.accepted),
        "declined": _rate_document(funnel.declined),
        "deferred": _rate_document(funnel.deferred),
        "no_response": _rate_document(funnel.no_response),
        "silence_rate": _rate_document(funnel.silence_rate),
        "followed": _rate_document(funnel.followed),
        "attended": _rate_document(funnel.attended),
        "enjoyment_recorded": _rate_document(funnel.enjoyment_recorded),
        "enjoyed": _rate_document(funnel.enjoyed),
    }


def _funnel_section(result: EvaluationResult, scenario_set: str, lines: list[str]) -> None:
    funnels = result.funnels.get(scenario_set, {})
    authored = result.outcome_scenarios.get(scenario_set, ())
    lines.append(f"### Follow-through funnel -- {scenario_set} set, budget-matched")
    lines.append("")
    if not authored:
        lines.append(
            "No scenario in this set authors an `outcomes:` block, so every stage below would "
            "read `0/0`. The funnel is defined and executable "
            "(`evaluation/funnel.py`); it has no data here, and that is reported rather than "
            "filled in."
        )
        lines.append("")
        return

    in_set = len(result.holdout_names if scenario_set == "holdout" else result.scenario_names)
    lines.append(
        f"{len(authored)} of {in_set} scenario(s) in this set author an `outcomes:` block: "
        + ", ".join(f"`{name}`" for name in authored)
        + ". **These denominators are small on purpose and must be read as such** -- the funnel "
        "is a working measurement over a handful of authored days, not yet a finding about how "
        "people respond to outreach."
    )
    lines.append("")
    lines.append(
        "| Policy | Offered (unauthored) | Coverage | Responded | Accepted | Silence | "
        "Followed up | Attended | Enjoyed |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for name, funnel in funnels.items():
        lines.append(
            f"| `{name}` | {funnel.offered} ({funnel.unauthored_offers}) | "
            f"{funnel.scenarios} scenario(s), {funnel.personas} persona(s) | "
            f"{funnel.responded.formatted()} | {funnel.accepted.formatted()} | "
            f"{funnel.silence_rate.formatted()} | {funnel.followed.formatted()} | "
            f"{funnel.attended.formatted()} | {funnel.enjoyed.formatted()} |"
        )
    lines.append("")


def _sweep_document(rows: tuple[SweepRow, ...]) -> list[dict[str, object]]:
    return [
        {
            "threshold": row.threshold,
            "contact_volume": row.metrics.contact_volume,
            "unnecessary_contact": _rate_document(row.metrics.unnecessary_contact),
            "missed_persistent_change": _rate_document(row.metrics.missed_persistent_change),
            "unwarranted_contact_share": _rate_document(row.metrics.unwarranted_contact_share),
            "contacts_by_person": dict(sorted(row.contacts_by_person.items())),
            "unwarranted_by_person": dict(sorted(row.unwarranted_by_person.items())),
        }
        for row in rows
    ]


def to_json_document(result: EvaluationResult) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "harness_version": result.harness_version,
        "seed": result.seed,
        "headline_arm": "capped",
        "uniform_contact_cap": next(
            (arm.cap for arm in result.arms.values() if arm.arm == "capped"), None
        ),
        "scenario_digest": result.scenario_digest,
        "scenarios": list(result.scenario_names),
        "holdout_digest": result.holdout_digest,
        "holdout_scenarios": list(result.holdout_names),
        "labelling_rule": LABELLING_RULE,
        "labelling_anchor_note": LABELLING_ANCHOR_NOTE,
        "labelling_caveat": LABELLING_CAVEAT,
        "budget_note": BUDGET_NOTE,
        "coverage_note": COVERAGE_NOTE,
        "label_agreement": _label_agreement_document(result.label_agreement),
        "burden_note": BURDEN_NOTE,
        "funnel_note": FUNNEL_NOTE,
        "funnels": {
            scenario_set: {
                "authored_outcome_scenarios": list(result.outcome_scenarios.get(scenario_set, ())),
                "policies": {
                    name: _funnel_document(funnel) for name, funnel in sorted(per_policy.items())
                },
            }
            for scenario_set, per_policy in sorted(result.funnels.items())
        },
        "not_measured": {name: reason for name, reason in NOT_MEASURED},
        "arms": {
            key: {
                "scenario_set": arm.scenario_set,
                "arm": arm.arm,
                "cap": arm.cap,
                "policies": {
                    name: {
                        "metrics": _metrics_document(arm.metrics[name]),
                        "ledger": [_ledger_entry(record) for record in records],
                    }
                    for name, records in arm.records.items()
                },
            }
            for key, arm in sorted(result.arms.items())
            if arm.arm != "ablation"
        },
        "ablations": {
            scenario_set: {
                name: {
                    **_metrics_document(metrics),
                    "steps_changed_vs_reference": _ablation_delta(result, scenario_set, name),
                }
                for name, metrics in sorted(per_policy.items())
            }
            for scenario_set, per_policy in sorted(result.ablations.items())
        },
        "context_dependent_restraint": {
            scenario_set: _rate_document(_context_dependent_restraint(result, scenario_set))
            for scenario_set in sorted(result.ablations)
        },
        "gate_descriptions": dict(sorted(GATE_DESCRIPTIONS.items())),
        "threshold_sweep": {
            scenario_set: _sweep_document(rows)
            for scenario_set, rows in sorted(result.sweep.items())
        },
        # Retained verbatim from schema_version 1 so existing consumers keep working: the core
        # set, uncapped arm.
        "policies": {
            name: {
                "metrics": _metrics_document(result.metrics[name]),
                "ledger": [_ledger_entry(record) for record in records],
            }
            for name, records in result.records.items()
        },
        "personas": {
            person_id: {
                "display_name": persona_profile(person_id).display_name,
                "is_playbook_persona": persona_profile(person_id).is_playbook_persona,
                "notes": persona_profile(person_id).notes,
                "policies": {
                    name: _metrics_document(metrics) for name, metrics in per_policy.items()
                },
            }
            for person_id, per_policy in _persona_metrics(result).items()
        },
    }


def _dumps(document: dict[str, object]) -> str:
    return json.dumps(document, sort_keys=True, indent=2) + "\n"


def _comparison_section(result: EvaluationResult, scenario_set: str, lines: list[str]) -> None:
    capped = result.arms[f"{scenario_set}/capped"]
    uncapped = result.arms[f"{scenario_set}/uncapped"]

    lines.append(f"### Budget-matched (headline) -- uniform weekly cap of {capped.cap}")
    lines.append("")
    lines.append(_METRIC_HEADER)
    lines.append(_METRIC_DIVIDER)
    for name, metrics in capped.metrics.items():
        lines.append(_metric_row(name, metrics))
    lines.append("")
    lines.append(RESTRAINT_NOTE)
    lines.append("")
    lines.append(_RESTRAINT_HEADER)
    lines.append(_RESTRAINT_DIVIDER)
    for name, metrics in capped.metrics.items():
        lines.append(_restraint_row(name, metrics))
    lines.append("")
    lines.append(
        "| Policy | Contacts made | Budget withheld by harness | Escalations | "
        "Can it escalate at all? |"
    )
    lines.append("|---|---|---|---|---|")
    for name, metrics in capped.metrics.items():
        capable = (
            "yes"
            if metrics.escalates
            else "**no -- never emits `coordinator_review`, so M3 is structural, not a judgement "
            "error**"
        )
        lines.append(
            f"| `{name}` | {metrics.contact_volume} | {metrics.budget_withheld} | "
            f"{metrics.human_review_count} | {capable} |"
        )
    lines.append("")

    lines.append("### Uncapped (each policy exactly as written)")
    lines.append("")
    lines.append(
        "`silverloop` caps itself, so its uncapped numbers are its own doing; neither baseline "
        "caps itself at all. That asymmetry is the reason the arm above exists."
    )
    lines.append("")
    lines.append(_METRIC_HEADER)
    lines.append(_METRIC_DIVIDER)
    for name, metrics in uncapped.metrics.items():
        lines.append(_metric_row(name, metrics))
    lines.append("")

    lines.append("### Budget effect (uncapped -> capped)")
    lines.append("")
    lines.append(
        "Read the direction of travel carefully. A baseline's M1 improves under the cap because "
        "the harness silenced it after two contacts, not because it judged better -- and the same "
        "cap makes its M2 (missed persistent change) worse, because an undiscriminating policy "
        "spends its whole budget on quiet days and has nothing left when a real decline arrives. "
        "That trade is the actual finding; the M1 improvement on its own is an artefact of the "
        "budget."
    )
    lines.append("")
    lines.append(
        "| Policy | Contacts uncapped | Contacts capped | Delta | "
        "M6 unwarranted share uncapped | M6 capped |"
    )
    lines.append("|---|---|---|---|---|---|")
    for name in capped.metrics:
        before = uncapped.metrics[name]
        after = capped.metrics[name]
        delta = after.contact_volume - before.contact_volume
        lines.append(
            f"| `{name}` | {before.contact_volume} | {after.contact_volume} | {delta:+d} | "
            f"{before.unwarranted_contact_share.formatted()} | "
            f"{after.unwarranted_contact_share.formatted()} |"
        )
    lines.append("")


def _ablation_section(result: EvaluationResult, scenario_set: str, lines: list[str]) -> None:
    metrics_by_policy = result.ablations.get(scenario_set)
    if not metrics_by_policy:
        return
    reference = metrics_by_policy[ABLATION_REFERENCE_NAME]
    lines.append(f"### Gate ablation -- {scenario_set} set")
    lines.append("")
    lines.append(
        "Each row switches off exactly one gate of a transcription of the ladder that lives inside "
        "the evaluation package (`evaluation/ladder.py`); `policy.py` is never edited or patched. "
        "The reference row is that transcription with every gate ON, and the test suite asserts it "
        "is decision-for-decision identical to `silverloop.policy.decide`, so any delta below is "
        "attributable to the disabled gate. Ablations run harness-uncapped, otherwise switching "
        "off the contact-cap gate would be invisible."
    )
    lines.append("")
    lines.append(
        "| Disabled gate | Steps decided differently | M1 unnecessary contact | "
        "M2 missed persistent change | M8 unsupported restraint | M4 no-action logging integrity | "
        "M6 unwarranted share | Contacts | Escalations | M5 violations | Load-bearing here? |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, metrics in metrics_by_policy.items():
        is_reference = name == ABLATION_REFERENCE_NAME
        gate = "_(reference: all gates on)_" if is_reference else f"`{name[14:]}`"
        changed_steps = _ablation_delta(result, scenario_set, name)
        if is_reference:
            verdict = "--"
        elif changed_steps == 0:
            verdict = "**no -- removing it changes nothing on this set**"
        elif _same_outcome(metrics, reference):
            verdict = "decisions move, no headline metric does"
        else:
            verdict = "yes"
        lines.append(
            f"| {gate} | {'--' if is_reference else changed_steps} | "
            f"{metrics.unnecessary_contact.formatted()} | "
            f"{metrics.missed_persistent_change.formatted()} | "
            f"{metrics.unsupported_restraint.formatted()} | "
            f"{metrics.no_action_logging_integrity.formatted()} | "
            f"{metrics.unwarranted_contact_share.formatted()} | {metrics.contact_volume} | "
            f"{metrics.human_review_count} | {metrics.violation_total} | {verdict} |"
        )
    lines.append("")
    lines.append("Gate meanings:")
    lines.append("")
    for gate in GATE_NAMES:
        lines.append(f"- `{gate}` -- {GATE_DESCRIPTIONS[gate]}")
    lines.append("")
    _context_dependent_restraint_section(result, scenario_set, lines)


def _extra_actions(result: EvaluationResult, scenario_set: str, policy: str) -> int:
    """How many MORE outreach actions this ablation produced than the all-gates-on reference.

    Distinct from `_ablation_delta` on purpose. A gate can change which quiet decision is recorded
    (`SUPPRESS` vs `NO_ACTION`) without ever unblocking an outreach, and only the second is
    evidence that the gate is preventing something. The consent gate is exactly this case on both
    scenario sets, and conflating the two would let a table imply a safety gate had been shown to
    do work it has not been shown to do here.
    """
    arm = result.arms.get(f"{scenario_set}/ablation")
    if arm is None or policy not in arm.metrics:
        return 0

    def actions(name: str) -> int:
        metrics = arm.metrics[name]
        return sum(metrics.decision_counts[decision] for decision in ACTION)

    return actions(policy) - actions(ABLATION_REFERENCE_NAME)


def _gate_verdict_section(result: EvaluationResult, lines: list[str]) -> None:
    """Roll the per-set ablations into one verdict per gate, and say plainly what this evidence
    base can and cannot show. A gate that never changes an outcome, and a gate that changes
    decisions without ever preventing an outreach, are both publishable negative results rather
    than things to leave implicit in a table."""
    sets = [name for name in ("core", "holdout") if name in result.ablations]
    if not sets:
        return
    lines.append("### Verdict per gate")
    lines.append("")
    lines.append(
        "`steps changed` counts replayed steps this ablation decided differently from the "
        "all-gates-on reference. `outreach unblocked` counts how many MORE contacts or "
        "escalations it produced. The two differ, and the difference matters: a gate that only "
        "changes which quiet decision is recorded has not been shown to prevent anything."
    )
    lines.append("")
    columns = [f"steps changed ({name})" for name in sets]
    columns += [f"outreach unblocked ({name})" for name in sets]
    lines.append("| Gate | " + " | ".join(columns) + " | Verdict |")
    lines.append("|---|" + "---|" * (len(columns) + 1))
    inert: list[str] = []
    quiet_only: list[str] = []
    for gate in GATE_NAMES:
        policy = f"silverloop_no_{gate}"
        deltas = [_ablation_delta(result, name, policy) for name in sets]
        unblocked = [_extra_actions(result, name, policy) for name in sets]
        if not any(deltas):
            verdict = "**no measurable effect on any scenario in either set**"
            inert.append(gate)
        elif not any(unblocked):
            verdict = "**changes decisions but never unblocks an outreach here**"
            quiet_only.append(gate)
        elif all(unblocked):
            verdict = "prevents outreach on both sets"
        else:
            covered = [name for name, extra in zip(sets, unblocked, strict=True) if extra]
            verdict = "prevents outreach on " + ", ".join(covered) + " only"
        cells = [str(value) for value in (*deltas, *unblocked)]
        lines.append(f"| `{gate}` | " + " | ".join(cells) + f" | {verdict} |")
    lines.append("")
    if inert or quiet_only:
        named = inert + quiet_only
        lines.append(
            "Neither result means a gate is useless, and neither is a licence to delete a safety "
            "gate. Both mean the gate is **masked** on this evidence base: some other gate "
            "independently blocks every step that would have exercised it. Gates in that position "
            "here: " + ", ".join(f"`{gate}`" for gate in named) + "."
        )
        lines.append("")
    if quiet_only:
        lines.append(
            "The `consent` case is worth stating outright, because it is the most safety-critical "
            "gate in the ladder and this run does **not** demonstrate it working. In "
            "`04_consent_revoked` the revocation day also has zero wear-time, so the data-quality "
            "gate would block outreach anyway; in `holdout/h03_consent_revoked_mid_decline` the "
            "post-revocation day has good data, but the contact budget is already spent, so the "
            "contact cap blocks it instead. Removing the consent gate therefore only downgrades "
            "`suppress` to `no_action` -- it never produces an unconsented contact on these "
            "scenarios. Closing that gap needs a scenario with revoked consent, good wear-time and "
            "an unspent budget. Until one exists, the consent gate's protection is asserted by "
            "`policy.py` and by `test_policy.py`, not evidenced by this comparison."
        )
        lines.append("")


def _same_outcome(candidate: PolicyMetrics, reference: PolicyMetrics) -> bool:
    return (
        candidate.decision_counts == reference.decision_counts
        and candidate.violation_total == reference.violation_total
    )


def _sweep_section(result: EvaluationResult, scenario_set: str, lines: list[str]) -> None:
    rows = result.sweep.get(scenario_set)
    if not rows:
        return
    lines.append(f"### Universal-threshold sensitivity -- {scenario_set} set")
    lines.append("")
    lines.append(
        "`fixed_threshold` acts when `steps < 3000`, and Mr Ravi's seeded baseline is ~2,400 "
        "steps a day, so he fails that line by construction. Reporting only that would beg the "
        "question, so the threshold is swept instead. If any single cut point left Mr Ravi alone "
        'AND still caught a real decline, the "personal baseline beats a universal threshold" '
        "claim would be false; the per-person columns are where to check. Uncapped on purpose -- "
        "a budget would truncate over-contacting at low thresholds and hide it."
    )
    lines.append("")
    people = sorted({person for row in rows for person in row.contacts_by_person})
    header = (
        "| Threshold (steps) | Contacts | M1 unnecessary contact | M2 missed persistent change | "
        + " | ".join(f"contacts: `{person}`" for person in people)
        + " |"
    )
    lines.append(header)
    lines.append("|---|---|---|---|" + "---|" * len(people))
    for row in rows:
        per_person = " | ".join(
            f"{row.contacts_by_person.get(person, 0)}"
            f" ({row.unwarranted_by_person.get(person, 0)} unwarranted)"
            for person in people
        )
        lines.append(
            f"| {row.threshold} | {row.metrics.contact_volume} | "
            f"{row.metrics.unnecessary_contact.formatted()} | "
            f"{row.metrics.missed_persistent_change.formatted()} | {per_person} |"
        )
    lines.append("")


def to_markdown(result: EvaluationResult) -> str:
    core_capped = result.arms["core/capped"]
    sample_size = next(iter(core_capped.metrics.values())).sample_size if core_capped.metrics else 0
    person_ids = _person_ids(result)
    persona_metrics = _persona_metrics(result)
    lines: list[str] = []
    lines.append("# Care+ policy comparison")
    lines.append("")
    lines.append(f"**{NOT_CLINICAL_LABEL}**")
    lines.append("")
    lines.append(
        f"This run replays {len(result.scenario_names)} core scenario(s) "
        f"({sample_size} decision steps, {len(person_ids)} persona(s)) and "
        f"{len(result.holdout_names)} holdout scenario(s) through three policies folded over an "
        "identical, decision-independent environment stream. Core and holdout are reported "
        "separately and are never pooled. Rates are always printed as `n/d (rate)`; a bare "
        "percentage over a small sample would be dishonest."
    )
    lines.append("")
    lines.append(
        f"Harness version: `{result.harness_version}` · Seed: `{result.seed}` · "
        f"Core digest: `{result.scenario_digest[:16]}…` · "
        f"Holdout digest: `{(result.holdout_digest or 'n/a')[:16]}…`"
    )
    lines.append("")
    lines.append(
        "The harness never calls the LLM planner; every number here is reproducible from the "
        "frozen seed alone."
    )
    lines.append("")
    lines.append(BUDGET_NOTE)
    lines.append("")
    lines.append(COVERAGE_NOTE)
    lines.append("")

    lines.append("## Ground truth")
    lines.append("")
    lines.append(LABELLING_RULE)
    lines.append("")
    lines.append(LABELLING_ANCHOR_NOTE)
    lines.append("")
    lines.append(LABELLING_CAVEAT)
    lines.append("")
    _label_agreement_section(result, lines)

    lines.append("## Core set")
    lines.append("")
    lines.append(
        f"The {len(result.scenario_names)} scenarios Care+'s thresholds were developed "
        "against. Treat these as in-sample."
    )
    lines.append("")
    _comparison_section(result, "core", lines)

    if result.has_holdout:
        lines.append("## Holdout set")
        lines.append("")
        lines.append(
            f"{len(result.holdout_names)} scenarios added after the policy was frozen. No "
            "threshold in `policy.py`, `analytics.py` or `quality.py` was changed, tuned or "
            "re-checked against them; the labels were assigned by the rule above from the "
            "replayed world state, before the decisions were looked at. Personas covered: "
            + ", ".join(f"`{person}`" for person in _holdout_person_ids(result))
            + "."
        )
        lines.append("")
        _comparison_section(result, "holdout", lines)

        lines.append("### Core vs holdout, budget-matched")
        lines.append("")
        lines.append(
            "| Policy | M1 core | M1 holdout | M6 core | M6 holdout | M7 core | M7 holdout | "
            "M8 core | M8 holdout |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        core_metrics = result.arms["core/capped"].metrics
        hold_metrics = result.arms["holdout/capped"].metrics
        for name in core_metrics:
            core_m = core_metrics[name]
            hold_m = hold_metrics[name]
            lines.append(
                f"| `{name}` | {core_m.unnecessary_contact.formatted()} | "
                f"{hold_m.unnecessary_contact.formatted()} | "
                f"{core_m.unwarranted_contact_share.formatted()} | "
                f"{hold_m.unwarranted_contact_share.formatted()} | "
                f"{core_m.correct_restraint.formatted()} | "
                f"{hold_m.correct_restraint.formatted()} | "
                f"{core_m.unsupported_restraint.formatted()} | "
                f"{hold_m.unsupported_restraint.formatted()} |"
            )
        lines.append("")

    lines.append("## Ablation: which of Care+'s own gates is load-bearing?")
    lines.append("")
    _ablation_section(result, "core", lines)
    if result.has_holdout:
        _ablation_section(result, "holdout", lines)
    _gate_verdict_section(result, lines)

    lines.append("## Threshold sensitivity")
    lines.append("")
    _sweep_section(result, "core", lines)
    if result.has_holdout:
        _sweep_section(result, "holdout", lines)

    lines.append("## Per-persona comparison (core set, uncapped arm)")
    lines.append("")
    lines.append(
        "Same metrics as above, scored separately for each seeded persona -- the population-wide "
        "table can hide a discriminator that only shows up for one person's own baseline (see "
        "`mr-ravi`, playbook demo purpose: defeat a universal step threshold). Read this table "
        "next to the threshold sweep, not on its own."
    )
    lines.append("")
    for person_id in person_ids:
        profile = persona_profile(person_id)
        label = "playbook persona" if profile.is_playbook_persona else "SYNTHETIC, not playbook"
        lines.append(f"### {profile.display_name} (`{person_id}`, {label})")
        lines.append("")
        if profile.notes:
            lines.append(profile.notes)
            lines.append("")
        lines.append(_METRIC_HEADER)
        lines.append(_METRIC_DIVIDER)
        for name, metrics in persona_metrics[person_id].items():
            lines.append(_metric_row(name, metrics))
        lines.append("")

    lines.append("## Hard violations by type (M5 breakdown)")
    lines.append("")
    lines.append(
        "Budget-matched arm first. `contact_cap_breach` is structurally zero there for every "
        "policy, because the harness enforces the budget -- which is exactly why the uncapped "
        "column beside it must not be read as a judgement score."
    )
    lines.append("")
    violation_columns = list(HardViolation)
    lines.append("| Policy | Arm | " + " | ".join(v.value for v in violation_columns) + " |")
    lines.append("|---|---|" + "---|" * len(violation_columns))
    for arm_name in ("capped", "uncapped"):
        arm = result.arms[f"core/{arm_name}"]
        for name, metrics in arm.metrics.items():
            counts = " | ".join(str(metrics.violations_by_type[v]) for v in violation_columns)
            lines.append(f"| `{name}` | {arm_name} | {counts} |")
    lines.append("")

    lines.append("## Burden")
    lines.append("")
    _burden_section(result, "core", lines)
    if result.has_holdout:
        _burden_section(result, "holdout", lines)

    lines.append("## Follow-through")
    lines.append("")
    lines.append(FUNNEL_NOTE)
    lines.append("")
    _funnel_section(result, "core", lines)
    if result.has_holdout:
        _funnel_section(result, "holdout", lines)

    lines.append("## Context (core set)")
    lines.append("")
    decision_columns = list(Decision)
    lines.append(
        "| Policy | Arm | Contact volume | Human review count | "
        + " | ".join(d.value for d in decision_columns)
        + " |"
    )
    lines.append("|---|---|---|---|" + "---|" * len(decision_columns))
    for arm_name in ("capped", "uncapped"):
        arm = result.arms[f"core/{arm_name}"]
        for name, metrics in arm.metrics.items():
            counts = " | ".join(str(metrics.decision_counts[d]) for d in decision_columns)
            lines.append(
                f"| `{name}` | {arm_name} | {metrics.contact_volume} | "
                f"{metrics.human_review_count} | {counts} |"
            )
    lines.append("")

    lines.append("## Soft counters (reported, not gated)")
    lines.append("")
    lines.append("| Policy | consent_not_recorded (core, budget-matched) |")
    lines.append("|---|---|")
    for name, metrics in result.arms["core/capped"].metrics.items():
        lines.append(f"| `{name}` | {metrics.consent_not_recorded} |")
    lines.append("")

    lines.append("## Not measured, and why")
    lines.append("")
    for name, reason in NOT_MEASURED:
        lines.append(f"- **{name}**: {reason}")
    lines.append("")

    return "\n".join(lines) + "\n"


def write_artifacts(result: EvaluationResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / JSON_FILENAME).write_text(_dumps(to_json_document(result)), encoding="utf-8")
    (out_dir / MARKDOWN_FILENAME).write_text(to_markdown(result), encoding="utf-8")


def check_artifacts(result: EvaluationResult, out_dir: Path) -> bool:
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
