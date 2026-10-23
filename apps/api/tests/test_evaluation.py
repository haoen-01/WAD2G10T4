from __future__ import annotations

import dataclasses
import hashlib
import inspect
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from silverloop import fixtures
from silverloop.evaluation.fold import CONTACT_CAP_WINDOW_DAYS, fold_policy
from silverloop.evaluation.funnel import authored_outcomes
from silverloop.evaluation.ladder import (
    FULL_LADDER,
    GATE_DESCRIPTIONS,
    GATE_NAMES,
    ablated_config,
    make_ladder,
)
from silverloop.evaluation.latent_labels import label_from_latent, label_from_signal
from silverloop.evaluation.metrics import (
    ACTION,
    CONTACT,
    DecisionRecord,
    HardViolation,
    Rate,
    aggregate,
    compute_burden,
    evaluate_violations,
)
from silverloop.evaluation.protocol import ABLATIONS, POLICIES
from silverloop.evaluation.report import to_json_document
from silverloop.evaluation.runner import (
    CAPPED_ARM,
    CORE_SET,
    UNCAPPED_ARM,
    UNIFORM_CONTACT_CAP,
    run_evaluation,
)
from silverloop.evaluation.scenario_spec import (
    GroundTruthState,
    ScenarioSpecError,
    discover_scenarios,
    load_scenario,
)
from silverloop.evaluation.simulation import replay
from silverloop.evaluation.world import (
    INITIAL_LATENT,
    LOW_ACTIVITY_LEVEL,
    LatentCause,
    LatentSpec,
    LatentState,
    advance_latent,
)
from silverloop.evaluation.world_model_probes import (
    RankingCase,
    probe_fact_contribution,
    probe_world_model,
)
from silverloop.models import (
    ActivityCandidate,
    ActivityIntent,
    ActivityLocation,
    ActivityPreferences,
    ActivitySource,
    Decision,
    DimensionPreference,
    FactCategory,
    FactConfidence,
    FactSourceType,
    IndoorOutdoor,
    IntegrationStatus,
    PersonFact,
    PersonWorldModel,
    PolicyGate,
    PreferenceDimension,
    WorldModelQuality,
)
from silverloop.ontology import ActivityType
from silverloop.policy import decide as silverloop_decide
from silverloop.review_threshold import ALLOWED_THRESHOLDS

SCENARIO_DIRECTORY = Path(__file__).parents[3] / "scenarios"
HOLDOUT_DIRECTORY = SCENARIO_DIRECTORY / "holdout"


def make_record(**overrides: object) -> DecisionRecord:
    values: dict[str, object] = {
        "policy": "test-policy",
        "scenario": "synthetic",
        "step": 1,
        "person_id": "mdm-lim",
        "event": "activity_declines",
        "label": GroundTruthState.STABLE,
        "decision": Decision.NO_ACTION,
        "support_priority": 0,
        "rationale": ("Activity remains within the personal range.",),
        "consent_active": True,
        "confidence": 1.0,
        "safe_to_interpret": True,
        "quality_evidence_id": "dq_mdm-lim_2026-08-19_synthetic",
        "interventions_last_7_days": 0,
        "forbidden": (),
    }
    values.update(overrides)
    return DecisionRecord(**values)


# --- Module boundary -------------------------------------------------------------------------


def test_evaluation_imports_no_database_or_llm_module() -> None:
    """The harness must be reproducible from a frozen seed alone, which means it may never reach
    the LLM planner -- an `LLM_API_KEY` is present in `.env` and must stay unused here. Importing
    `silverloop.agent` or `silverloop.config` is the only way it could, so the boundary is
    asserted at import time rather than trusted to discipline.
    """
    script = (
        "import sys; import silverloop.evaluation; "
        "forbidden = {'silverloop.sql_repository', 'silverloop.db_models', "
        "'silverloop.main', 'silverloop.config', 'silverloop.agent', "
        "'silverloop.agent.planner', 'anthropic', 'openai', 'boto3'}; "
        "loaded = forbidden & set(sys.modules); "
        "assert not loaded, loaded; "
        "print('OK')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1] / "src",
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout


# --- Baselines structurally denied the personal baseline --------------------------------------


def test_baselines_never_see_personal_baseline() -> None:
    result = run_evaluation(SCENARIO_DIRECTORY)
    for policy_name in ("fixed_threshold", "contextual_rule"):
        assert result.records[policy_name], "expected non-empty ledger"

    # blind_view zeroes delta_percent/robust_z on the *view* the policy sees; verify by
    # reconstructing the view directly from each replayed step rather than trusting the ledger,
    # since DecisionRecord does not carry the full SignalSummary.
    for scenario_path in sorted(SCENARIO_DIRECTORY.glob("*.yaml")):
        scenario = load_scenario(scenario_path)
        steps = replay(scenario)
        for entry in POLICIES:
            if entry.name == "silverloop":
                continue
            for step in steps:
                window = [*step.history, step.metric]
                view = entry.view(step.signal, window)
                assert view.delta_percent == 0.0
                assert view.robust_z == 0.0


# --- The gate ------------------------------------------------------------------------------


def test_silverloop_has_zero_hard_violations() -> None:
    result = run_evaluation(SCENARIO_DIRECTORY)
    assert result.metrics["silverloop"].violation_total == 0
    assert result.metrics["silverloop"].violating_step_count == 0


def test_fixed_threshold_violates_on_consent_and_quality() -> None:
    """The counter-case: if this ever passes clean, fixed_threshold has been accidentally made
    safe and the whole comparison is void.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    assert result.metrics["fixed_threshold"].violation_total > 0
    consent_revoked_records = [
        record
        for record in result.records["fixed_threshold"]
        if record.scenario == "04_consent_revoked"
    ]
    assert consent_revoked_records
    violations = evaluate_violations(consent_revoked_records[0])
    assert HardViolation.UNCONSENTED_OUTREACH in violations
    low_wear_records = [
        record for record in result.records["fixed_threshold"] if record.scenario == "03_low_wear"
    ]
    assert HardViolation.UNSAFE_DATA_ACTION in evaluate_violations(low_wear_records[0])


def test_contextual_rule_breaches_contact_cap_on_scenario_07() -> None:
    """Pins the discriminating finding that `contextual_rule` has NO contact-cap check at all,
    unlike `silverloop`.

    On the original seven scenarios (mdm-lim only), every `activity_declines` chain's first
    metric is exactly 3400 steps -- above `contextual_rule`'s own 3000-step threshold -- so under
    the harness's own strict per-policy, per-scenario contact accounting (D2), `contextual_rule`
    never naturally accumulates two prior contacts before a third contact-eligible step in any of
    those seven scenarios. That is a fact about mdm-lim's particular fixture, not about the
    mechanism -- F5's `mr-tan` and `mdm-devi` personas (scenarios 09/10) give the same mechanism
    real fixtures to fire on; see `test_contact_cap_breach_fires_for_baseline_policies_only`.

    This test isolates the mechanism directly: replay scenario 07's real, decision-independent
    step 4 (the exact point at which Care+'s own weekly cap correctly returns SUPPRESS),
    feed `contextual_rule` an `interventions_last_7_days` of 2 (the value Care+'s own fold
    reaches at that point), and show `contextual_rule` returns a CONTACT decision anyway -- and
    that the metrics layer correctly flags it as a hard `CONTACT_CAP_BREACH`.
    """
    scenario = load_scenario(SCENARIO_DIRECTORY / "07_contact_cap.yaml")
    steps = replay(scenario)
    step4 = steps[3]
    contextual_rule = next(entry for entry in POLICIES if entry.name == "contextual_rule")

    view_signal = contextual_rule.view(step4.signal, [*step4.history, step4.metric])
    result = contextual_rule.decide(
        view_signal, consent_active=step4.consent_active, interventions_last_7_days=2
    )
    assert result.decision in CONTACT

    record = make_record(
        policy="contextual_rule",
        scenario=scenario.name,
        step=step4.step,
        event=step4.event,
        label=step4.label,
        decision=result.decision,
        support_priority=result.support_priority,
        rationale=tuple(result.rationale),
        consent_active=step4.consent_active,
        confidence=view_signal.confidence,
        safe_to_interpret=step4.signal.quality.safe_to_interpret,
        quality_evidence_id=step4.signal.quality.evidence_id,
        interventions_last_7_days=2,
    )
    assert HardViolation.CONTACT_CAP_BREACH in evaluate_violations(record)


def test_contact_cap_breach_fires_for_baseline_policies_only() -> None:
    """F5: `mr-tan` (scenario 09) and `mdm-devi` (scenario 10) give real fixtures to the
    contact-cap-breach mechanism `test_contextual_rule_breaches_contact_cap_on_scenario_07`
    isolates -- both baseline policies contact three times in a row with no weekly cap of their
    own, so `contact_cap_breach` must be non-zero for `fixed_threshold` and `contextual_rule`.

    `silverloop` must never breach its own cap: this is the safety-critical half of the
    invariant, and it must hold regardless of how many scenarios are added.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    breaches = {
        name: metrics.violations_by_type[HardViolation.CONTACT_CAP_BREACH]
        for name, metrics in result.metrics.items()
    }
    assert breaches["silverloop"] == 0
    assert breaches["fixed_threshold"] > 0
    assert breaches["contextual_rule"] > 0


# --- Determinism -----------------------------------------------------------------------------


def test_run_is_deterministic() -> None:
    first = to_json_document(run_evaluation(SCENARIO_DIRECTORY))
    second = to_json_document(run_evaluation(SCENARIO_DIRECTORY))
    assert first == second


# --- Per-predicate hard-violation tests ------------------------------------------------------


def test_unconsented_outreach_predicate() -> None:
    record = make_record(consent_active=False, decision=Decision.GENTLE_NUDGE, rationale=("x",))
    assert HardViolation.UNCONSENTED_OUTREACH in evaluate_violations(record)


def test_unconsented_outreach_does_not_fire_on_quiet_decisions() -> None:
    record = make_record(consent_active=False, decision=Decision.SUPPRESS, rationale=())
    assert HardViolation.UNCONSENTED_OUTREACH not in evaluate_violations(record)


def test_unsafe_data_action_predicate() -> None:
    record = make_record(
        safe_to_interpret=False, decision=Decision.PROGRAMME_SUGGESTION, rationale=("x",)
    )
    assert HardViolation.UNSAFE_DATA_ACTION in evaluate_violations(record)


def test_low_confidence_action_predicate() -> None:
    record = make_record(confidence=0.1, decision=Decision.COORDINATOR_REVIEW, rationale=("x",))
    assert HardViolation.LOW_CONFIDENCE_ACTION in evaluate_violations(record)


def test_low_confidence_action_does_not_fire_at_boundary() -> None:
    record = make_record(confidence=0.45, decision=Decision.COORDINATOR_REVIEW, rationale=("x",))
    assert HardViolation.LOW_CONFIDENCE_ACTION not in evaluate_violations(record)


def test_unexplained_action_predicate() -> None:
    record = make_record(decision=Decision.GENTLE_NUDGE, rationale=())
    assert HardViolation.UNEXPLAINED_ACTION in evaluate_violations(record)


def test_contact_cap_breach_predicate() -> None:
    record = make_record(
        decision=Decision.GENTLE_NUDGE, interventions_last_7_days=2, rationale=("x",)
    )
    assert HardViolation.CONTACT_CAP_BREACH in evaluate_violations(record)


def test_contact_cap_breach_does_not_fire_below_cap() -> None:
    record = make_record(
        decision=Decision.GENTLE_NUDGE, interventions_last_7_days=1, rationale=("x",)
    )
    assert HardViolation.CONTACT_CAP_BREACH not in evaluate_violations(record)


def test_contact_cap_breach_does_not_fire_on_escalation() -> None:
    record = make_record(
        decision=Decision.COORDINATOR_REVIEW, interventions_last_7_days=5, rationale=("x",)
    )
    assert HardViolation.CONTACT_CAP_BREACH not in evaluate_violations(record)


def test_forbidden_action_predicate() -> None:
    record = make_record(decision=Decision.GENTLE_NUDGE, forbidden=("gentle_nudge",))
    assert HardViolation.FORBIDDEN_ACTION in evaluate_violations(record)


def test_forbidden_action_does_not_fire_for_other_decisions() -> None:
    record = make_record(decision=Decision.NO_ACTION, forbidden=("gentle_nudge",))
    assert HardViolation.FORBIDDEN_ACTION not in evaluate_violations(record)


def test_multi_fire_violation_counts_are_distinguished() -> None:
    """Revoked consent + unsafe data + low confidence + empty rationale on ONE decision must
    report `violation_total == 4` and `violating_step_count == 1`, so "4 violations from 1
    decision" is never misread as four bad decisions.
    """
    record = make_record(
        consent_active=False,
        safe_to_interpret=False,
        confidence=0.1,
        decision=Decision.GENTLE_NUDGE,
        rationale=(),
    )
    violations = evaluate_violations(record)
    assert len(violations) == 4
    assert set(violations) == {
        HardViolation.UNCONSENTED_OUTREACH,
        HardViolation.UNSAFE_DATA_ACTION,
        HardViolation.LOW_CONFIDENCE_ACTION,
        HardViolation.UNEXPLAINED_ACTION,
    }

    metrics = aggregate("test", "v1", [record])
    assert metrics.violation_total == 4
    assert metrics.violating_step_count == 1


# --- Metric denominators ----------------------------------------------------------------------


def test_m1_denominator_is_stable_and_explained_dip_only() -> None:
    records = [
        make_record(label=GroundTruthState.STABLE, decision=Decision.GENTLE_NUDGE),
        make_record(label=GroundTruthState.EXPLAINED_DIP, decision=Decision.NO_ACTION),
        make_record(label=GroundTruthState.PERSISTENT_DECLINE, decision=Decision.GENTLE_NUDGE),
        make_record(label=GroundTruthState.EMERGING_DECLINE, decision=Decision.GENTLE_NUDGE),
    ]
    metrics = aggregate("test", "v1", records)
    assert metrics.unnecessary_contact.denominator == 2
    assert metrics.unnecessary_contact.numerator == 1


def test_m2_and_m3_denominator_is_persistent_decline_only() -> None:
    records = [
        make_record(label=GroundTruthState.PERSISTENT_DECLINE, decision=Decision.SUPPRESS),
        make_record(label=GroundTruthState.EMERGING_DECLINE, decision=Decision.NO_ACTION),
        make_record(label=GroundTruthState.STABLE, decision=Decision.NO_ACTION),
    ]
    metrics = aggregate("test", "v1", records)
    assert metrics.missed_persistent_change.denominator == 1
    assert metrics.missed_persistent_change.numerator == 1  # SUPPRESS counts as missed
    assert metrics.missed_escalation.denominator == 1
    assert metrics.missed_escalation.numerator == 1


def test_m2_suppress_counts_as_missed() -> None:
    records = [make_record(label=GroundTruthState.PERSISTENT_DECLINE, decision=Decision.SUPPRESS)]
    metrics = aggregate("test", "v1", records)
    assert metrics.missed_persistent_change.numerator == 1


def test_null_rate_when_denominator_is_zero() -> None:
    records = [make_record(label=GroundTruthState.EMERGING_DECLINE, decision=Decision.NO_ACTION)]
    metrics = aggregate("test", "v1", records)
    assert metrics.unnecessary_contact.denominator == 0
    assert metrics.unnecessary_contact.rate is None
    assert metrics.missed_persistent_change.denominator == 0
    assert metrics.missed_persistent_change.rate is None


def test_m4_no_action_logging_integrity_requires_rationale_and_evidence() -> None:
    """M4 (renamed from `audited_no_action`) is a logging-integrity check: it says nothing about
    whether the silence was correct, only whether the pipeline wrote down why. See M7/M8 below for
    the ground-truth-based correctness metrics."""
    audited = make_record(
        decision=Decision.NO_ACTION,
        rationale=("Activity remains within the personal range.",),
        quality_evidence_id="dq_mdm-lim_2026-08-19_synthetic",
    )
    unaudited = make_record(decision=Decision.NO_ACTION, rationale=(), quality_evidence_id="")
    metrics = aggregate("test", "v1", [audited, unaudited])
    assert metrics.no_action_logging_integrity.numerator == 1
    assert metrics.no_action_logging_integrity.denominator == 2


def test_m7_correct_restraint_excludes_suppress_and_is_scored_against_ground_truth() -> None:
    """M7's denominator is `stable`/`explained_dip` steps (the same set M1 uses); its numerator
    is `NO_ACTION` specifically. A `SUPPRESS` on one of those steps means consent or the contact
    budget blocked a contact the policy wanted to make -- not evidence of correct judgement -- so
    it must NOT count toward the numerator even though it is quiet.
    """
    correct = make_record(label=GroundTruthState.STABLE, decision=Decision.NO_ACTION)
    blocked = make_record(label=GroundTruthState.EXPLAINED_DIP, decision=Decision.SUPPRESS)
    wrong_contact = make_record(label=GroundTruthState.STABLE, decision=Decision.GENTLE_NUDGE)
    irrelevant = make_record(label=GroundTruthState.PERSISTENT_DECLINE, decision=Decision.NO_ACTION)
    metrics = aggregate("test", "v1", [correct, blocked, wrong_contact, irrelevant])
    assert metrics.correct_restraint.denominator == 3
    assert metrics.correct_restraint.numerator == 1


def test_m8_unsupported_restraint_excludes_suppress_and_escalation() -> None:
    """M8's denominator is `persistent_decline` steps (the same set M2/M3 use); its numerator is
    `NO_ACTION` specifically -- a policy presenting reasoned inaction when help was warranted.
    `SUPPRESS` (already captured by M2) and `COORDINATOR_REVIEW` (a correct escalation) must not
    inflate this number."""
    unsupported = make_record(
        label=GroundTruthState.PERSISTENT_DECLINE, decision=Decision.NO_ACTION
    )
    withheld = make_record(label=GroundTruthState.PERSISTENT_DECLINE, decision=Decision.SUPPRESS)
    escalated = make_record(
        label=GroundTruthState.PERSISTENT_DECLINE, decision=Decision.COORDINATOR_REVIEW
    )
    metrics = aggregate("test", "v1", [unsupported, withheld, escalated])
    assert metrics.unsupported_restraint.denominator == 3
    assert metrics.unsupported_restraint.numerator == 1


def test_m9_restraint_explanation_coverage_excludes_suppress() -> None:
    """M9's denominator is `NO_ACTION` only; `SUPPRESS`'s rationale explains a consent/budget
    block, not a judgement of restraint, so it must not appear in the denominator at all."""
    explained = make_record(
        decision=Decision.NO_ACTION,
        rationale=("Activity remains within the personal range.",),
        quality_evidence_id="dq_mdm-lim_2026-08-19_synthetic",
    )
    unexplained = make_record(decision=Decision.NO_ACTION, rationale=(), quality_evidence_id="")
    suppressed = make_record(
        decision=Decision.SUPPRESS,
        rationale=(),
        quality_evidence_id="",
    )
    metrics = aggregate("test", "v1", [explained, unexplained, suppressed])
    assert metrics.restraint_explanation_coverage.denominator == 2
    assert metrics.restraint_explanation_coverage.numerator == 1


def test_m9_is_m4s_predicate_rescoped_to_no_action_not_an_independent_finding() -> None:
    """Pins the overclaim finding: M9 is `_has_evidence_backed_rationale` again -- the identical
    predicate M4 uses -- merely re-scoped from `QUIET` to `NO_ACTION`. A policy whose `NO_ACTION`
    branches always attach a rationale (like `silverloop.policy.decide`) reads 100% on M9 for the
    same structural reason it reads 100% on M4, not because ground truth was consulted.
    """
    always_explained = [
        make_record(
            decision=Decision.NO_ACTION,
            rationale=("Activity remains within the personal range.",),
            quality_evidence_id="dq_mdm-lim_2026-08-19_synthetic",
            label=label,
        )
        for label in (GroundTruthState.STABLE, GroundTruthState.PERSISTENT_DECLINE)
    ]
    metrics = aggregate("test", "v1", always_explained)
    assert metrics.restraint_explanation_coverage.rate == 1.0
    assert metrics.no_action_logging_integrity.rate == 1.0
    # The 100% is unrelated to whether either decision was actually correct: one of these two
    # records is a `NO_ACTION` on a `persistent_decline` step, which M8 scores as unsupported
    # restraint (0% correct) in the very same aggregate.
    assert metrics.unsupported_restraint.numerator == 1


def test_m7_is_an_identity_of_m1_when_suppress_never_appears() -> None:
    """Pins the overclaim finding: on M1's own denominator, `correct_restraint.rate` (M7) equals
    `1 - unnecessary_contact.rate` (M1) whenever no policy `SUPPRESS`es a `stable`/`explained_dip`
    step -- true of every arm this harness has ever replayed. M7 is not independent evidence in
    that case; it is the same fact under a different name.
    """
    records = [
        make_record(label=GroundTruthState.STABLE, decision=Decision.NO_ACTION),
        make_record(label=GroundTruthState.STABLE, decision=Decision.GENTLE_NUDGE),
        make_record(label=GroundTruthState.EXPLAINED_DIP, decision=Decision.NO_ACTION),
        make_record(label=GroundTruthState.EXPLAINED_DIP, decision=Decision.NO_ACTION),
    ]
    metrics = aggregate("test", "v1", records)
    assert metrics.correct_restraint.rate == pytest.approx(1 - metrics.unnecessary_contact.rate)


def test_m7_diverges_from_m1_only_when_suppress_appears_on_no_intervention_steps() -> None:
    """The one case where M7 is NOT reducible to `1 - M1`: a `SUPPRESS` on a
    `stable`/`explained_dip` step counts against neither M1's nor M7's numerator, so the identity
    becomes `M7 = 1 - M1 - suppress_share` and M7 now carries information M1 alone does not.
    """
    records = [
        make_record(label=GroundTruthState.STABLE, decision=Decision.NO_ACTION),
        make_record(label=GroundTruthState.STABLE, decision=Decision.SUPPRESS),
        make_record(label=GroundTruthState.STABLE, decision=Decision.GENTLE_NUDGE),
        make_record(label=GroundTruthState.STABLE, decision=Decision.SUPPRESS),
    ]
    metrics = aggregate("test", "v1", records)
    suppress_share = 2 / 4
    assert metrics.correct_restraint.rate == pytest.approx(
        1 - metrics.unnecessary_contact.rate - suppress_share
    )
    assert metrics.correct_restraint.rate != pytest.approx(1 - metrics.unnecessary_contact.rate)


def test_m7_and_m8_report_n_over_a_when_denominator_is_zero() -> None:
    records = [make_record(label=GroundTruthState.EMERGING_DECLINE, decision=Decision.NO_ACTION)]
    metrics = aggregate("test", "v1", records)
    assert metrics.correct_restraint.denominator == 0
    assert metrics.correct_restraint.rate is None
    assert metrics.unsupported_restraint.denominator == 0
    assert metrics.unsupported_restraint.rate is None


# --- Scenario spec validation ------------------------------------------------------------------


def test_scenario_spec_rejects_label_count_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "events:\n  - recovery\n  - recovery\nlabels:\n  - stable\nexpected_decisions: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ScenarioSpecError):
        load_scenario(path)


def test_scenario_spec_rejects_unknown_label(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "events:\n  - recovery\nlabels:\n  - definitely_not_a_real_label\nexpected_decisions: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ScenarioSpecError):
        load_scenario(path)


def test_scenario_spec_rejects_decision_name_as_label(tmp_path: Path) -> None:
    """Anti-circularity guard (D4): a `Decision` member name must never validate as a label."""
    path = tmp_path / "bad.yaml"
    path.write_text(
        "events:\n  - recovery\nlabels:\n  - no_action\nexpected_decisions: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ScenarioSpecError):
        load_scenario(path)


# --- Ladder transcription equivalence (guards every ablation number) ---------------------------


def test_full_ladder_is_identical_to_the_real_policy() -> None:
    """`evaluation/ladder.py` transcribes the ladder so gates can be switched off one at a time
    WITHOUT editing or monkeypatching `policy.py`. Every ablation number is only meaningful if the
    transcription is faithful, so this folds both over every replayed step of every scenario in
    both sets, at every contact count the fold can reach, and asserts full `PolicyResult` equality
    -- decision, support priority and rationale.

    The review block is folded too: every one of the fourteen allowed review thresholds, with no
    shadow date and with the step's own day as one, over each step and a floor-deep variant of it,
    so the personal-threshold, floor and shadow rungs (and their templated rationale) are all
    compared. The default call shape -- no threshold
    arguments at all -- is kept as its own case, since that is the shape the harness uses.

    If this fails, `policy.py` changed and `ladder.py` did not. Fix `ladder.py`.
    """
    reference = make_ladder(FULL_LADDER)
    checked = 0
    gates_seen: set[PolicyGate | None] = set()
    for directory in (SCENARIO_DIRECTORY, HOLDOUT_DIRECTORY):
        for scenario in discover_scenarios(directory):
            for step in replay(scenario):
                for contacts in range(4):
                    expected = silverloop_decide(
                        step.signal,
                        consent_active=step.consent_active,
                        interventions_last_7_days=contacts,
                    )
                    actual = reference(
                        step.signal,
                        consent_active=step.consent_active,
                        interventions_last_7_days=contacts,
                    )
                    assert actual == expected, (scenario.name, step.step, contacts)
                    checked += 1
                    # The scenarios never fall 60% for three days, so each step is also folded
                    # as a floor-deep variant -- otherwise the floor rung would go uncompared.
                    floor_deep = step.signal.model_copy(
                        update={
                            "delta_percent": -62.0,
                            "sustained_low_days": max(3, step.signal.sustained_low_days),
                        }
                    )
                    for signal in (step.signal, floor_deep):
                        for threshold in ALLOWED_THRESHOLDS:
                            for shadow_since in (None, step.metric.day):
                                expected = silverloop_decide(
                                    signal,
                                    consent_active=step.consent_active,
                                    interventions_last_7_days=contacts,
                                    review_threshold=threshold,
                                    shadow_review_since=shadow_since,
                                )
                                actual = reference(
                                    signal,
                                    consent_active=step.consent_active,
                                    interventions_last_7_days=contacts,
                                    review_threshold=threshold,
                                    shadow_review_since=shadow_since,
                                )
                                assert actual == expected, (
                                    scenario.name,
                                    step.step,
                                    contacts,
                                    threshold,
                                    shadow_since,
                                )
                                gates_seen.add(expected.decided_by)
                                checked += 1
    assert checked > 0
    # The fold must actually reach the new rungs, or it proves nothing about them.
    assert {
        PolicyGate.SEVERITY_PERSISTENCE,
        PolicyGate.REVIEW_FLOOR,
        PolicyGate.SHADOW_CHECK,
    } <= gates_seen


def test_every_gate_has_an_ablation_and_a_description() -> None:
    assert {entry.name for entry in ABLATIONS} == {f"silverloop_no_{gate}" for gate in GATE_NAMES}
    assert set(GATE_DESCRIPTIONS) == set(GATE_NAMES)


def test_ablating_a_gate_changes_only_the_steps_that_gate_governs() -> None:
    """A one-gate ablation must differ from the reference only on steps the gate governs. The
    consent ablation is the cleanest case: it may only change decisions on steps where consent is
    inactive.
    """
    scenario = load_scenario(HOLDOUT_DIRECTORY / "h03_consent_revoked_mid_decline.yaml")
    reference = make_ladder(FULL_LADDER)
    ablated = make_ladder(ablated_config("consent"))
    for step in replay(scenario):
        if not step.consent_active:
            continue
        expected = reference(
            step.signal, consent_active=step.consent_active, interventions_last_7_days=0
        )
        actual = ablated(
            step.signal, consent_active=step.consent_active, interventions_last_7_days=0
        )
        assert actual == expected, step.step


# --- Budget-matched comparison ------------------------------------------------------------------


def test_capped_arm_holds_every_policy_to_the_same_budget() -> None:
    """The whole point of the capped arm: no policy may exceed the uniform weekly cap inside
    any rolling `CONTACT_CAP_WINDOW_DAYS` window of any scenario, so contact volumes are
    comparable by construction.

    Per rolling window, not per scenario. The cap is a *weekly* budget -- the same one
    `policy.py` applies to Care+, counted in the person's simulated days -- and an 18-day
    scenario such as `14_baseline_drift` legitimately allows a policy up to two contacts in each
    of its weeks. Asserting one budget for the whole scenario would hold the baselines to a
    stricter rule than Care+ holds itself to, which is the asymmetry this arm exists to
    remove.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    replayed = {
        scenario.name: replay(scenario)
        for scenario in [
            *discover_scenarios(SCENARIO_DIRECTORY),
            *discover_scenarios(HOLDOUT_DIRECTORY),
        ]
    }
    for key, arm in result.arms.items():
        if arm.arm != CAPPED_ARM:
            continue
        for policy, records in arm.records.items():
            contact_days: dict[str, list] = {}
            for record in records:
                if record.decision in CONTACT:
                    day = replayed[record.scenario][record.step - 1].metric.day
                    contact_days.setdefault(record.scenario, []).append(day)
            for scenario_name, days in contact_days.items():
                for day in days:
                    window_start = day - timedelta(days=CONTACT_CAP_WINDOW_DAYS - 1)
                    in_window = sum(1 for other in days if window_start <= other <= day)
                    assert in_window <= UNIFORM_CONTACT_CAP, (key, policy, scenario_name, days)


def test_contact_cap_breach_cannot_fire_in_the_capped_arm() -> None:
    """`CONTACT_CAP_BREACH` counted against a policy that has no cap of its own is grading it on
    an exam it was built to fail. In the budget-matched arm the harness enforces the budget, so the
    violation is structurally impossible for every policy -- which is what makes the remaining
    violations in that arm meaningful.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    for arm in result.arms.values():
        if arm.arm != CAPPED_ARM:
            continue
        for policy, metrics in arm.metrics.items():
            assert metrics.violations_by_type[HardViolation.CONTACT_CAP_BREACH] == 0, policy


def test_harness_cap_is_a_no_op_for_silverloop() -> None:
    """Care+ caps itself, so the harness's uniform cap must never bind for it. If this fails,
    the two arms are not comparable for Care+ and the "same budget" claim is false.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    for scenario_set in ("core", "holdout"):
        capped = result.arms[f"{scenario_set}/{CAPPED_ARM}"].records["silverloop"]
        uncapped = result.arms[f"{scenario_set}/{UNCAPPED_ARM}"].records["silverloop"]
        assert [record.decision for record in capped] == [record.decision for record in uncapped], (
            scenario_set
        )
        assert all(not record.budget_withheld for record in capped), scenario_set


def test_uncapped_baselines_actually_spend_more_than_the_budget() -> None:
    """The counter-case to the test above: if the harness cap never bound for anyone, the two arms
    would be identical and the budget-matched comparison would be measuring nothing.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    capped = result.arms[f"core/{CAPPED_ARM}"].metrics
    for policy in ("fixed_threshold", "contextual_rule"):
        assert capped[policy].budget_withheld > 0, policy


def test_unwarranted_contact_share_is_scored_over_contacts_made() -> None:
    """M6's denominator is the contacts a policy actually made, not the steps it could have acted
    on. It is only comparable across policies at a matched budget, hence the arm.
    """
    records = [
        make_record(decision=Decision.GENTLE_NUDGE, label=GroundTruthState.STABLE),
        make_record(decision=Decision.GENTLE_NUDGE, label=GroundTruthState.EMERGING_DECLINE),
        make_record(decision=Decision.COORDINATOR_REVIEW, label=GroundTruthState.STABLE),
        make_record(decision=Decision.NO_ACTION, label=GroundTruthState.STABLE),
    ]
    metrics = aggregate("test", "v1", records)
    assert metrics.unwarranted_contact_share.denominator == 2
    assert metrics.unwarranted_contact_share.numerator == 1


def test_policies_that_never_escalate_are_flagged() -> None:
    """A policy with no escalation branch scores M3 = 100% by construction. The report must be
    able to say "it cannot escalate at all" rather than presenting that as a judgement error.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    metrics = result.arms[f"core/{CAPPED_ARM}"].metrics
    assert metrics["silverloop"].escalates
    assert not metrics["fixed_threshold"].escalates
    assert not metrics["contextual_rule"].escalates


# --- Holdout separation -------------------------------------------------------------------------


def test_holdout_is_loaded_and_never_pooled_with_core() -> None:
    result = run_evaluation(SCENARIO_DIRECTORY)
    assert result.has_holdout
    assert len(result.holdout_names) == 5
    assert not set(result.scenario_names) & set(result.holdout_names)
    assert result.holdout_digest
    assert result.holdout_digest != result.scenario_digest
    core = result.arms[f"core/{CAPPED_ARM}"].records["silverloop"]
    holdout = result.arms[f"holdout/{CAPPED_ARM}"].records["silverloop"]
    assert {record.scenario for record in core}.isdisjoint({record.scenario for record in holdout})


def test_core_scenario_discovery_does_not_reach_into_holdout() -> None:
    """`discover_scenarios` globs non-recursively; if that ever changed, the holdout would silently
    be pooled into the core set and the separation claim would be false.
    """
    core = {scenario.name for scenario in discover_scenarios(SCENARIO_DIRECTORY)}
    holdout = {scenario.name for scenario in discover_scenarios(HOLDOUT_DIRECTORY)}
    assert core.isdisjoint(holdout)
    assert all(name.startswith("h0") for name in holdout)


def test_holdout_labels_are_world_state_not_decisions() -> None:
    for scenario in discover_scenarios(HOLDOUT_DIRECTORY):
        assert len(scenario.labels) == len(scenario.events)
        for label in scenario.labels:
            assert isinstance(label, GroundTruthState)


# --- Metamorphic properties ---------------------------------------------------------------------


def test_metamorphic_irrelevant_persona_attributes_do_not_change_any_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Change something that must not matter -- display name and preferred language -- and every
    decision in every scenario, for every policy and every arm, must be unchanged.

    This is a property over the whole pipeline, not a single case: it renames every persona and
    swaps every language, then re-runs the entire evaluation. The numeric fixture parameters
    (`seed_offset`, `baseline_steps`, ...) are untouched, so the replayed world is identical.
    """
    before = run_evaluation(SCENARIO_DIRECTORY)

    renamed = {
        person_id: dataclasses.replace(
            profile,
            display_name=f"Renamed {person_id}",
            preferred_language="Interlingua",
        )
        for person_id, profile in fixtures.DEMO_PERSONAS.items()
    }
    monkeypatch.setattr(fixtures, "DEMO_PERSONAS", renamed)

    after = run_evaluation(SCENARIO_DIRECTORY)

    for key, arm in before.arms.items():
        for policy, records in arm.records.items():
            other = after.arms[key].records[policy]
            assert [record.decision for record in records] == [
                record.decision for record in other
            ], (key, policy)
            assert [record.rationale for record in records] == [
                record.rationale for record in other
            ], (key, policy)


def test_metamorphic_rain_suppresses_a_single_day_dip() -> None:
    """Change something that must matter, and assert the direction. Adding rain to a single-day
    dip must move the decision strictly towards LESS intrusion, never towards more.
    """
    scenario = load_scenario(SCENARIO_DIRECTORY / "05_sustained_decline.yaml")
    step = replay(scenario)[0]
    assert step.signal.sustained_low_days < 2
    assert not step.signal.context.rainy

    dry = silverloop_decide(step.signal, consent_active=True, interventions_last_7_days=0)
    rainy_signal = step.signal.model_copy(
        update={"context": step.signal.context.model_copy(update={"rainy": True})}
    )
    wet = silverloop_decide(rainy_signal, consent_active=True, interventions_last_7_days=0)

    assert dry.decision in ACTION
    assert wet.decision == Decision.NO_ACTION
    assert wet.support_priority < dry.support_priority


def test_metamorphic_rain_does_not_excuse_a_persisting_dip() -> None:
    """The other half of the property, and the one that stops the rain gate becoming a blanket
    excuse: once the dip has persisted two valid-wear days, adding rain must NOT change the
    decision at all.
    """
    scenario = load_scenario(SCENARIO_DIRECTORY / "05_sustained_decline.yaml")
    step = replay(scenario)[1]
    assert step.signal.sustained_low_days >= 2
    assert not step.signal.context.rainy

    dry = silverloop_decide(step.signal, consent_active=True, interventions_last_7_days=0)
    rainy_signal = step.signal.model_copy(
        update={"context": step.signal.context.model_copy(update={"rainy": True})}
    )
    wet = silverloop_decide(rainy_signal, consent_active=True, interventions_last_7_days=0)
    assert wet == dry


def test_metamorphic_revoking_consent_never_increases_intrusion() -> None:
    """A property, not a case: for every replayed step in both sets, flipping consent from active
    to inactive must never produce a MORE intrusive decision.
    """
    intrusion = {
        Decision.SUPPRESS: 0,
        Decision.NO_ACTION: 0,
        Decision.GENTLE_NUDGE: 1,
        Decision.PROGRAMME_SUGGESTION: 2,
        Decision.COORDINATOR_REVIEW: 3,
    }
    for directory in (SCENARIO_DIRECTORY, HOLDOUT_DIRECTORY):
        for scenario in discover_scenarios(directory):
            for step in replay(scenario):
                for contacts in range(3):
                    consented = silverloop_decide(
                        step.signal, consent_active=True, interventions_last_7_days=contacts
                    )
                    revoked = silverloop_decide(
                        step.signal, consent_active=False, interventions_last_7_days=contacts
                    )
                    assert intrusion[revoked.decision] <= intrusion[consented.decision]


# --- Threshold sensitivity ------------------------------------------------------------------------


def test_no_universal_threshold_is_simultaneously_quiet_and_sensitive() -> None:
    """The claim "a personal baseline beats a universal step threshold" is only worth making if it
    survives sweeping the threshold. This asserts the sweep's actual shape: every cut point either
    contacts Mr Ravi without cause (his ~2,400-step baseline is normal FOR HIM) or misses a genuine
    persistent decline. If some threshold ever satisfied both, this test fails and the claim must be
    withdrawn rather than the threshold quietly re-picked.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    rows = result.sweep["core"]
    assert rows
    for row in rows:
        quiet_for_ravi = row.unwarranted_by_person.get("mr-ravi", 0) == 0
        catches_declines = row.metrics.missed_persistent_change.numerator == 0
        assert not (quiet_for_ravi and catches_declines), row.threshold

    silverloop = result.arms[f"core/{CAPPED_ARM}"].records["silverloop"]
    ravi_contacts = sum(
        1 for record in silverloop if record.person_id == "mr-ravi" and record.decision in CONTACT
    )
    assert ravi_contacts == 0


def test_sweep_is_scored_on_the_same_replayed_environment() -> None:
    """Every sweep row must cover the same number of steps as the headline comparison, otherwise
    the sweep and the comparison are not talking about the same run.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    expected = result.arms[f"core/{UNCAPPED_ARM}"].metrics["fixed_threshold"].sample_size
    for row in result.sweep["core"]:
        assert row.metrics.sample_size == expected, row.threshold


# --- Determinism of the extended harness ----------------------------------------------------------


def test_extended_run_is_deterministic_across_every_arm() -> None:
    first = run_evaluation(SCENARIO_DIRECTORY)
    second = run_evaluation(SCENARIO_DIRECTORY)
    assert set(first.arms) == set(second.arms)
    for key, arm in first.arms.items():
        for policy, records in arm.records.items():
            assert [record.decision for record in records] == [
                record.decision for record in second.arms[key].records[policy]
            ], (key, policy)


def test_removing_the_contact_cap_unblocks_outreach_on_both_sets() -> None:
    """The ablation machinery works: switching off a gate that is genuinely load-bearing changes
    the decisions. Kept in the unit suite because it is a statement about the harness, true of any
    scenario set, and independent of what any particular scenario happens to contain.

    The HOLDOUT-SPECIFIC half of this test moved out, deliberately -- see
    `test_holdout_specific_numbers_live_in_the_artifact_not_in_this_suite` below.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    for scenario_set in ("core", "holdout"):
        metrics = result.ablations[scenario_set]
        uncapped = sum(metrics["silverloop_no_contact_cap"].decision_counts[d] for d in ACTION)
        reference = sum(metrics["silverloop_all_gates"].decision_counts[d] for d in ACTION)
        assert uncapped > reference, scenario_set


def test_consent_gate_is_still_masked_on_the_core_set() -> None:
    """The uncomfortable negative result, on the set whose scenarios were written alongside the
    policy: every consent-revoked core step is independently blocked by data quality (zero
    wear-time in `04_consent_revoked`), so the comparison does not evidence that consent prevents
    contact. That is a gap in the evidence rather than a win, and it is worth pinning: a passing
    ablation on one set is not evidence on the other.

    The holdout counterpart of this assertion -- that removing the gate there DOES yield one extra
    outreach -- used to sit beside it, and is now the artifact's job (see below).
    """
    result = run_evaluation(SCENARIO_DIRECTORY)

    def actions(scenario_set: str, name: str) -> int:
        counts = result.ablations[scenario_set][name].decision_counts
        return sum(counts[decision] for decision in ACTION)

    assert actions("core", "silverloop_no_consent") == actions("core", "silverloop_all_gates")


def test_holdout_specific_numbers_live_in_the_artifact_not_in_this_suite() -> None:
    """R14: holdout-specific numbers do not belong in the unit suite.

    A unit test asserting "removing the consent gate yields exactly one more outreach on holdout"
    turns the held-out set into a regression fixture for the production signal pipeline: the number
    it pins is a property of five scenarios nobody may tune against, so the only way to change
    analytics or quality is to edit the assertion -- and an assertion that is edited whenever it
    fails is not evidence. The published artifact is where those numbers belong: it carries every
    ablation's decision counts for BOTH sets, and `python -m silverloop.evaluation <dir> --out
    docs/evaluation --check` (run by `pnpm verify` and CI) fails byte-for-byte on any drift, with
    the diff naming exactly which number moved and by how much.

    This test therefore asserts only that the numbers ARE in the artifact and that the harness
    still produces them -- not what they are.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    document = to_json_document(result)
    holdout_ablations = document["ablations"]["holdout"]
    for arm in ("silverloop_all_gates", "silverloop_no_consent", "silverloop_no_contact_cap"):
        assert arm in holdout_ablations, arm
        assert holdout_ablations[arm]["decision_counts"], arm
    assert result.has_holdout


# --- E2: the documented ground-truth label rule, executed against every replayed step ---------


def test_documented_ground_truth_rule_agreement_is_reported_not_asserted() -> None:
    """E2, relaxed by E1 (M24). `docs/evaluation/policy-comparison.md`'s "Ground truth" rule is
    still executable -- it lives in `latent_labels.label_from_signal` now, rather than being
    duplicated here -- and it is still run against every step of both sets. What changed is the
    verdict.

    This test used to assert `derived == authored` for every step, which made CI forbid any
    authored label from disagreeing with a rule built out of `analytics.py` and `quality.py`.
    Functionally that pinned the whole label set, holdout included, to the production signal
    pipeline: a future change to either module would either break this test or force another
    holdout label edit. So the equality is gone. The rate is REPORTED, the disagreements are
    LISTED, and what is asserted is only that the rule is total (it produces a label for every
    replayed step) and that the artifact publishes the same number a reader can recompute.

    The independent check on the labels is now `label_feature_agreement` against the authored
    `world:` blocks, in `test_label_agreement_is_reported_below_one_and_lists_its_disagreements`.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    agreement = result.label_agreement.authored_signal_agreement
    disagreements = result.label_agreement.authored_disagreements()

    total_steps = sum(
        len(scenario.events)
        for directory in (SCENARIO_DIRECTORY, HOLDOUT_DIRECTORY)
        for scenario in discover_scenarios(directory)
    )
    assert agreement.denominator == total_steps, "the rule must produce a label for every step"
    assert len(disagreements) == agreement.denominator - agreement.numerator

    # Reported, never gated. Printed so a disagreeing step is visible in the test log rather than
    # only in the artifact.
    print(f"authored vs signal-derived label agreement: {agreement.formatted()}")
    for row in disagreements:
        print(f"  disagreement: {row.describe()}")

    published = to_json_document(result)["label_agreement"]
    assert isinstance(published, dict)
    assert published["authored_vs_signal_agreement"]["numerator"] == agreement.numerator
    assert published["authored_vs_signal_agreement"]["denominator"] == agreement.denominator


# --- Rate coverage: counts instead of a confidence interval -----------------------------------


def test_rate_formats_scenario_and_persona_coverage() -> None:
    """The policy comparison deliberately carries no bootstrap (`report.COVERAGE_NOTE`): with
    serially dependent steps from a handful of scripted personas, a CI would manufacture a
    sampling distribution the design does not have. Two counts say the same honest thing.
    """
    assert (
        Rate(numerator=0, denominator=19, scenarios=3, personas=2).formatted()
        == "0/19 (0.00%) across 3 scenarios, 2 personas"
    )
    assert (
        Rate(numerator=1, denominator=1, scenarios=1, personas=1).formatted()
        == "1/1 (100.00%) across 1 scenario, 1 persona"
    )
    # A hand-assembled Rate with no provenance says nothing rather than claiming zero coverage.
    assert Rate(numerator=0, denominator=0).formatted() == "0/0 (n/a)"


def test_policy_rates_count_the_scenarios_and_personas_behind_the_denominator() -> None:
    result = run_evaluation(SCENARIO_DIRECTORY)
    arm = result.arms[f"{CORE_SET}/{CAPPED_ARM}"]
    metrics = arm.metrics["silverloop"]
    records = arm.records["silverloop"]

    quiet_worthy = {GroundTruthState.STABLE, GroundTruthState.EXPLAINED_DIP}
    cases = (
        (metrics.unnecessary_contact, quiet_worthy),
        (metrics.missed_persistent_change, {GroundTruthState.PERSISTENT_DECLINE}),
    )
    for rate, labels in cases:
        contributing = [record for record in records if record.label in labels]
        assert rate.denominator == len(contributing)
        assert rate.scenarios == len({record.scenario for record in contributing})
        assert rate.personas == len({record.person_id for record in contributing})
        # The counts are a floor on the evidence, never larger than the denominator itself.
        assert 0 < rate.scenarios <= rate.denominator
        assert 0 < rate.personas <= rate.scenarios


def test_policy_comparison_carries_no_confidence_interval() -> None:
    """E's "what NOT to build" item 3, pinned: no policy-harness rate may grow a CI. If one is
    ever added, this test is the place the decision has to be re-argued.
    """
    document = to_json_document(run_evaluation(SCENARIO_DIRECTORY))
    rate_keys: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "numerator" in node and "denominator" in node:
                rate_keys.update(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    assert rate_keys == {"numerator", "denominator", "rate", "scenarios", "personas"}


# --- M24: the authored latent world, and the labels derived from it ---------------------------

#: sha256 over every scenario's name and its `labels:` entries, in load order. The `world:` blocks
#: are ADDITIVE: they add a second account of each day and must never disturb the first. This
#: digest was computed from the committed blobs BEFORE any `world:` block existed and is
#: reproduced by the working tree afterwards, which is the whole claim.
AUTHORED_LABEL_DIGEST = "bf9a81cc2cecd51a0c7c4fecd751e87c212557d62430c07d4d909860d10b66ae"


def _authored_label_digest() -> str:
    hasher = hashlib.sha256()
    for directory in (SCENARIO_DIRECTORY, HOLDOUT_DIRECTORY):
        for scenario in discover_scenarios(directory):
            hasher.update(scenario.name.encode("utf-8"))
            for label in scenario.labels:
                hasher.update(b"\x00")
                hasher.update(label.value.encode("utf-8"))
    return hasher.hexdigest()


def test_authored_scenario_labels_are_untouched_by_the_world_blocks() -> None:
    """The one thing the latent world was not allowed to do is edit a hand-authored label. This
    fails the moment anybody changes, reorders or drops one -- in either scenario set.
    """
    assert _authored_label_digest() == AUTHORED_LABEL_DIGEST


def test_every_replayed_scenario_carries_an_authored_world_block() -> None:
    """Reported as a list rather than a bare count, so a scenario that loses its block says which
    one it was. A missing block is legal (the latent is then `None` and the scenario drops out of
    the agreement denominator); it is simply never silent.
    """
    missing = [
        scenario.name
        for directory in (SCENARIO_DIRECTORY, HOLDOUT_DIRECTORY)
        for scenario in discover_scenarios(directory)
        if scenario.world is None
    ]
    assert missing == [], f"scenarios with no authored world block: {missing}"


def test_world_block_is_optional_and_its_absence_leaves_the_replay_untouched() -> None:
    """The block is additive in the strongest sense: stripping it changes `latent` to `None` and
    nothing else. If authoring a world could move a metric, every `expected_decisions` entry in
    `scenarios/` would silently be scoring a different environment.
    """
    scenario = load_scenario(SCENARIO_DIRECTORY / "05_sustained_decline.yaml")
    assert scenario.world is not None

    with_world = replay(scenario)
    without_world = replay(dataclasses.replace(scenario, world=None))

    assert [step.latent for step in without_world] == [None, None, None]
    assert all(step.latent is not None for step in with_world)
    for left, right in zip(with_world, without_world, strict=True):
        assert left.metric == right.metric
        assert left.label == right.label
        assert left.consent_active == right.consent_active
        assert left.signal == right.signal


def test_latent_labels_are_not_a_function_of_the_signal_summary() -> None:
    """E1's fix, stated as a property: two replays whose `SignalSummary` is identical to the byte
    must still be able to carry different ground truth, because the truth is what the author
    scripted and the signal is only a measurement of it. Same events, same seed, same numbers --
    one world where the weather caused the dip, one where a change in routine did.
    """
    base = load_scenario(SCENARIO_DIRECTORY / "02_rain_context.yaml")
    rained = dataclasses.replace(
        base, world=(LatentSpec(cause=LatentCause.WEATHER, true_activity_level=0.58),)
    )
    withdrew = dataclasses.replace(
        base, world=(LatentSpec(cause=LatentCause.ROUTINE_CHANGE, true_activity_level=0.58),)
    )

    rained_steps = replay(rained)
    withdrew_steps = replay(withdrew)

    # The measurement is identical...
    assert rained_steps[0].signal == withdrew_steps[0].signal
    assert rained_steps[0].metric == withdrew_steps[0].metric
    # ...and the signal-derived rule therefore cannot tell them apart.
    assert label_from_signal(rained_steps[0].signal, True) == label_from_signal(
        withdrew_steps[0].signal, True
    )
    # ...but the authored worlds do.
    assert rained_steps[0].latent is not None
    assert withdrew_steps[0].latent is not None
    assert label_from_latent(rained_steps[0].latent, True) == GroundTruthState.EXPLAINED_DIP
    assert label_from_latent(withdrew_steps[0].latent, True) == GroundTruthState.EMERGING_DECLINE


def test_observation_noise_moves_the_measurement_but_never_the_latent_label() -> None:
    """The converse property: one authored world observed twice through different noise draws
    must label identically, because the truth does not move when the instrument does. This is the
    only exercise the seeded observation channel gets -- it is off (`sigma=0`) for every committed
    artifact, since turning it on would move `expected_decisions` entries this track does not own.
    """
    scenario = load_scenario(SCENARIO_DIRECTORY / "05_sustained_decline.yaml")
    quiet = replay(scenario)
    noisy = replay(scenario, observation_sigma=0.25)

    assert [step.metric.steps for step in quiet] != [step.metric.steps for step in noisy]
    assert [step.latent for step in quiet] == [step.latent for step in noisy]
    for left, right in zip(quiet, noisy, strict=True):
        assert left.latent is not None
        assert right.latent is not None
        assert label_from_latent(left.latent, left.consent_active) == label_from_latent(
            right.latent, right.consent_active
        )

    # Seeded, so the noisy replay is itself reproducible.
    assert [step.metric.steps for step in replay(scenario, observation_sigma=0.25)] == [
        step.metric.steps for step in noisy
    ]


def test_fold_policy_never_reads_the_latent() -> None:
    """Ground truth must not reach a policy: letting a decision see `latent` would hand the
    candidate the answer sheet. Pinned twice -- the fold's source never mentions the attribute,
    and replacing every latent with its opposite leaves every `DecisionRecord` identical.
    """
    assert "latent" not in inspect.getsource(fold_policy)
    assert "latent" not in {field.name for field in dataclasses.fields(DecisionRecord)}

    scenario = load_scenario(SCENARIO_DIRECTORY / "05_sustained_decline.yaml")
    entry = next(item for item in POLICIES if item.name == "silverloop")

    steps = replay(scenario)
    before = fold_policy(entry, scenario, steps)

    contradiction = LatentState(
        true_activity_level=0.01,
        cause=LatentCause.ILLNESS_LIKE,
        days_low=99,
        observable=False,
    )
    for step in steps:
        step.latent = contradiction
    after = fold_policy(entry, scenario, steps)

    assert before == after


def test_label_agreement_is_reported_below_one_and_lists_its_disagreements() -> None:
    """`label_feature_agreement` is a diagnostic with a target BELOW 100%, never a score to
    maximise: at 1.000 the second label source has collapsed onto the first and the harness is
    the tautology E1 described, with extra steps. Assert it is a real rate over every step and
    that the disagreements are enumerable -- never that it equals a particular number, which
    would turn an honest disagreement back into a CI failure.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    agreement = result.label_agreement.feature_agreement

    total_steps = sum(
        len(scenario.events)
        for directory in (SCENARIO_DIRECTORY, HOLDOUT_DIRECTORY)
        for scenario in discover_scenarios(directory)
    )
    assert agreement.denominator == total_steps
    assert agreement.scenarios == 20
    assert agreement.personas == 5
    assert agreement.rate is not None
    assert agreement.rate < 1.0, (
        "the authored world agrees with the signal-derived rule on every step; the second label "
        "source is not independent of the first"
    )

    disagreements = result.label_agreement.feature_disagreements()
    assert len(disagreements) == agreement.denominator - agreement.numerator
    for row in disagreements:
        assert row.label_latent is not None
        assert row.label_latent != row.label_signal
        assert row.describe()


def test_authored_world_levels_point_the_same_way_as_the_observed_delta() -> None:
    """The latent is authored, not derived -- but an author who writes a world that contradicts
    the numbers their own scenario generates has written a bug, not a finding. Direction only:
    a day the world calls above-norm must not be measured below the person's anchored median, and
    vice versa. Magnitudes are deliberately unconstrained, which is what leaves room for the three
    real disagreements the agreement rate reports.
    """
    mismatches: list[str] = []
    for directory in (SCENARIO_DIRECTORY, HOLDOUT_DIRECTORY):
        for scenario in discover_scenarios(directory):
            for step in replay(scenario):
                latent = step.latent
                if latent is None or not latent.observable or not step.consent_active:
                    continue
                if abs(latent.true_activity_level - 1.0) < 0.02:
                    continue
                world_is_up = latent.true_activity_level > 1.0
                measured_is_up = step.signal.reference_delta_percent > 0
                if world_is_up != measured_is_up:
                    mismatches.append(
                        f"{scenario.name}:{step.step} true_level="
                        f"{latent.true_activity_level} delta="
                        f"{step.signal.reference_delta_percent}"
                    )
    assert not mismatches, "\n".join(mismatches)


def test_world_block_validation_rejects_malformed_entries(tmp_path: Path) -> None:
    base = {
        "name": "world validation",
        "events": ["recovery"],
        "labels": ["stable"],
    }
    bad_worlds = (
        ([{"cause": "nonsense", "true_level": 1.0}], "unknown cause"),
        ([{"true_level": 1.0}], "missing required key"),
        ([{"cause": "none"}], "missing required key"),
        ([{"cause": "none", "true_level": "high"}], "must be a number"),
        ([{"cause": "none", "true_level": 42}], "must lie in"),
        ([{"cause": "none", "true_level": 1.0, "days_low": -1}], "must not be negative"),
        ([{"cause": "none", "true_level": 1.0, "observable": "yes"}], "must be a boolean"),
        ([{"cause": "none", "true_level": 1.0, "tru_level": 1.0}], "unknown world key"),
        ([], "exactly one entry per event"),
        ("not-a-list", "must be a list"),
    )
    for index, (world, expected) in enumerate(bad_worlds):
        path = tmp_path / f"bad_{index}.yaml"
        path.write_text(yaml.safe_dump({**base, "world": world}), encoding="utf-8")
        with pytest.raises(ScenarioSpecError, match=expected):
            load_scenario(path)


def test_latent_label_rule_is_ordered_consent_then_device_then_cause() -> None:
    """The authored order, pinned so a future edit to `label_from_latent` is a deliberate change
    to the definition of the world rather than an accident. A real decline continuing underneath
    a revoked consent or a dead device still labels `no_consent`/`unusable_data`: the harness can
    now say "something was happening and we were right not to look", which is a stronger and more
    honest claim than "nothing was happening".
    """
    real_decline = LatentState(
        true_activity_level=0.30,
        cause=LatentCause.ILLNESS_LIKE,
        days_low=9,
        observable=True,
    )
    assert label_from_latent(real_decline, False) == GroundTruthState.NO_CONSENT
    unseen = dataclasses.replace(real_decline, observable=False)
    assert label_from_latent(unseen, True) == GroundTruthState.UNUSABLE_DATA

    # Weather explains a dip however deep and however long, with no one-day expiry -- which is
    # precisely where the authored world parts company with Care+'s rain gate.
    rained_out = dataclasses.replace(real_decline, cause=LatentCause.WEATHER)
    assert label_from_latent(rained_out, True) == GroundTruthState.EXPLAINED_DIP

    # A holiday is a cause, never an excuse (the product boundary 13_public_holiday states).
    holiday_dip = LatentState(
        true_activity_level=0.75,
        cause=LatentCause.HOLIDAY,
        days_low=1,
        observable=True,
    )
    assert label_from_latent(holiday_dip, True) == GroundTruthState.EMERGING_DECLINE

    at_the_low_boundary = dataclasses.replace(holiday_dip, true_activity_level=LOW_ACTIVITY_LEVEL)
    just_above_it = dataclasses.replace(holiday_dip, true_activity_level=LOW_ACTIVITY_LEVEL + 0.01)
    assert label_from_latent(at_the_low_boundary, True) == GroundTruthState.EMERGING_DECLINE
    assert label_from_latent(just_above_it, True) == GroundTruthState.STABLE


def test_advance_latent_continues_and_resets_the_low_run() -> None:
    """`days_low` is derived from the previous day's world, never from a metric, and an author may
    always override it. The reset is what makes `07_contact_cap` step 4 read `days_low: 1` rather
    than 3 after an intervening normal day.
    """
    low = LatentSpec(cause=LatentCause.ROUTINE_CHANGE, true_activity_level=0.52)
    normal = LatentSpec(cause=LatentCause.NONE, true_activity_level=1.05)

    first = advance_latent("activity_declines", INITIAL_LATENT, low)
    second = advance_latent("activity_declines", first, low)
    reset = advance_latent("recovery", second, normal)
    fourth = advance_latent("activity_declines", reset, low)

    assert [state.days_low for state in (first, second, reset, fourth)] == [1, 2, 0, 1]

    # `observable` defaults from the event, and an author may say otherwise.
    assert advance_latent("low_wear", INITIAL_LATENT, normal).observable is False
    assert advance_latent("consent_revoked", INITIAL_LATENT, normal).observable is False
    assert advance_latent("recovery", INITIAL_LATENT, normal).observable is True
    override = LatentSpec(
        cause=LatentCause.ROUTINE_CHANGE, true_activity_level=0.52, observable=False
    )
    assert advance_latent("activity_declines", INITIAL_LATENT, override).observable is False
    pinned = LatentSpec(cause=LatentCause.ROUTINE_CHANGE, true_activity_level=0.52, days_low=7)
    assert advance_latent("activity_declines", INITIAL_LATENT, pinned).days_low == 7


# --- M38: burden, and the follow-through funnel ------------------------------------------------


def test_burden_counts_contacts_against_a_printed_person_week_denominator() -> None:
    """`contact_volume` is a bare count: "Care+ makes 16 contacts" is unreadable without
    knowing over how many of the person's days. One replayed step is one simulated day.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    arm = result.arms[f"{CORE_SET}/{CAPPED_ARM}"]
    for name, metrics in arm.metrics.items():
        burden = metrics.burden
        assert burden.person_days == len(arm.records[name])
        assert burden.contacts == metrics.contact_volume
        assert burden.contacts_per_person_week == pytest.approx(
            burden.contacts * 7 / burden.person_days, abs=1e-4
        )
        assert "person-weeks" in burden.formatted_contacts_per_person_week()

    # An empty ledger reports honestly rather than dividing by zero.
    empty = compute_burden([])
    assert empty.contacts_per_person_week is None
    assert empty.max_consecutive_contact_days == 0
    assert empty.formatted_escalations_per_case() == "0/0 (no escalation episode)"


def test_max_consecutive_contact_days_never_spans_two_scenarios() -> None:
    """Two scenarios are two different weeks of two possibly different people, so the last step
    of one and the first of the next are not consecutive days of anybody's life.
    """
    contacts = [
        make_record(scenario="a", step=1, decision=Decision.GENTLE_NUDGE),
        make_record(scenario="a", step=2, decision=Decision.PROGRAMME_SUGGESTION),
        make_record(scenario="b", step=1, decision=Decision.GENTLE_NUDGE),
        make_record(scenario="b", step=2, decision=Decision.GENTLE_NUDGE),
        make_record(scenario="b", step=3, decision=Decision.GENTLE_NUDGE),
    ]
    burden = compute_burden(contacts)
    assert burden.max_consecutive_contact_days == 3
    assert burden.max_consecutive_contact_scenario == "b"

    # A quiet day in the middle breaks the run.
    broken = [
        make_record(scenario="c", step=1, decision=Decision.GENTLE_NUDGE),
        make_record(scenario="c", step=2, decision=Decision.NO_ACTION),
        make_record(scenario="c", step=3, decision=Decision.GENTLE_NUDGE),
    ]
    assert compute_burden(broken).max_consecutive_contact_days == 1


def test_escalations_per_case_counts_repeat_escalations_of_one_concern() -> None:
    """The coordinator-side burden `14_baseline_drift` was built to expose: eighteen declining
    days are ONE concern, and the product refreshes a case rather than duplicating it, but the
    ladder still emits a `coordinator_review` on each of them. Anything above 1.0 per case is
    that cost, and it is a burden number rather than a correctness one -- none of M1-M9 can see it.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    silverloop = result.arms[f"{CORE_SET}/{CAPPED_ARM}"].metrics["silverloop"]
    per_case = silverloop.burden.escalations_per_case

    assert per_case.denominator > 0
    assert per_case.numerator == silverloop.human_review_count
    assert per_case.numerator / per_case.denominator > 1.0, (
        "expected at least one concern re-escalated on consecutive days"
    )
    assert "per case" in silverloop.burden.formatted_escalations_per_case()
    # A ratio above 1 must never render as a percentage.
    assert "%" not in silverloop.burden.formatted_escalations_per_case()


def test_funnel_separates_a_tap_from_an_attendance() -> None:
    """`accepted` means "show me more". A funnel that collapses it into success is optimising
    engagement, which is the failure mode this product exists to avoid.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    funnel = result.funnels[CORE_SET]["silverloop"]

    assert funnel.offered > 0
    assert funnel.accepted.numerator > funnel.attended.numerator, (
        "expected at least one tap that did not become an attendance"
    )
    assert funnel.no_response.denominator == funnel.offered
    assert funnel.followed.denominator == funnel.accepted.numerator
    assert funnel.attended.denominator == funnel.followed.numerator
    assert funnel.enjoyed.denominator == funnel.enjoyment_recorded.numerator
    assert funnel.silence_rate is funnel.no_response


def test_funnel_excludes_contacts_on_days_the_scenario_does_not_author() -> None:
    """An unauthored day is missing data. Counting it as silence would invent a refusal and make
    every policy look more ignored the more scenarios go unauthored.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    for name, funnel in result.funnels[CORE_SET].items():
        metrics = result.arms[f"{CORE_SET}/{CAPPED_ARM}"].metrics[name]
        assert funnel.offered + funnel.unauthored_offers == metrics.contact_volume
        assert funnel.unauthored_offers > 0


def test_funnel_is_policy_dependent_because_a_quieter_policy_offers_less() -> None:
    """The authored outcomes are a fact about the person; which of those days became an offer is
    a fact about the policy. So the denominators legitimately differ between policies, and the
    `n/d` is what makes that readable instead of misleading.
    """
    result = run_evaluation(SCENARIO_DIRECTORY)
    offered = {name: funnel.offered for name, funnel in result.funnels[CORE_SET].items()}
    assert len(set(offered.values())) > 1, offered


def test_scenarios_without_an_outcomes_block_report_an_empty_funnel() -> None:
    result = run_evaluation(SCENARIO_DIRECTORY)
    assert result.outcome_scenarios[CORE_SET] == (
        "05_sustained_decline",
        "15_contact_cap_counts_simulated_days",
    )
    # The holdout authors none, and says so with zeros rather than being omitted.
    assert result.outcome_scenarios["holdout"] == ()
    for funnel in result.funnels["holdout"].values():
        assert funnel.offered == 0
        assert funnel.responded.rate is None


def test_outcome_block_rejects_an_impossible_history(tmp_path: Path) -> None:
    """Enjoyment requires an attending follow-through, follow-through requires acceptance, and an
    administrative closure is never a reply. Authoring a funnel that cannot have happened is a
    mistake caught at load time, not a row in the artifact.
    """
    base = {
        "name": "outcome validation",
        "events": ["activity_declines"],
        "labels": ["emerging_decline"],
    }
    bad = (
        ([{"response": "activity_recovered"}], "administrative closure"),
        ([{"response": "declined", "follow_through": "completed"}], "only meaningful after"),
        (
            [{"response": "accepted", "follow_through": "unable", "enjoyment": "enjoyed"}],
            "requires an attending follow_through",
        ),
        ([{"response": "accepted", "enjoyment": "enjoyed"}], "requires an attending"),
        ([{"response": "shrug"}], "unknown response"),
        ([{"follow_through": "completed"}], "missing required key"),
        ([{"response": "accepted", "reponse": "accepted"}], "unknown outcome key"),
        ([], "exactly one entry per event"),
    )
    for index, (outcomes, expected) in enumerate(bad):
        path = tmp_path / f"bad_outcome_{index}.yaml"
        path.write_text(yaml.safe_dump({**base, "outcomes": outcomes}), encoding="utf-8")
        with pytest.raises(ScenarioSpecError, match=expected):
            load_scenario(path)


def test_outcome_block_accepts_a_null_day(tmp_path: Path) -> None:
    path = tmp_path / "nulls.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "partial authoring",
                "events": ["activity_declines", "recovery"],
                "labels": ["emerging_decline", "stable"],
                "outcomes": [{"response": "declined"}, None],
            }
        ),
        encoding="utf-8",
    )
    scenario = load_scenario(path)
    assert scenario.outcomes is not None
    assert scenario.outcomes[1] is None
    assert authored_outcomes(scenario.name, scenario.outcomes).keys() == {(scenario.name, 1)}


# --- M38: world-model probes -------------------------------------------------------------------


def _fact(key: str, value: str, *, source_type: FactSourceType, source: str) -> PersonFact:
    return PersonFact(
        key=key,
        category=FactCategory.ACTIVITY_PREFERENCE,
        statement=f"{key} is {value}",
        value=value,
        source_type=source_type,
        source=source,
        confidence=FactConfidence.MEDIUM,
        evidence_count=2,
    )


def _model(facts: list[PersonFact]) -> PersonWorldModel:
    return PersonWorldModel(
        person_id="mdm-lim",
        as_of_day=date(2026, 9, 13),
        facts=facts,
        quality=WorldModelQuality(
            facts=len(facts),
            explicit=sum(1 for f in facts if f.source_type == FactSourceType.EXPLICIT),
            inferred=sum(1 for f in facts if f.source_type == FactSourceType.INFERRED),
        ),
    )


def test_world_model_probe_counts_corrections_and_rejections_across_snapshots() -> None:
    """`corrected` and `rejected` are TRANSITIONS. Neither is visible in a single snapshot, which
    is why the probe takes a sequence: a model that shows a person nothing but its current state
    can never show them the moment it was put right.
    """
    inferred = _fact("distance", "far", source_type=FactSourceType.INFERRED, source="inferred")
    corrected = _fact(
        "distance",
        "near",
        source_type=FactSourceType.EXPLICIT,
        source="dimension_preference:senior_statement",
    )
    drifted = _fact("timing", "morning", source_type=FactSourceType.INFERRED, source="inferred")
    drifted_again = _fact(
        "timing", "afternoon", source_type=FactSourceType.INFERRED, source="inferred"
    )

    probe = probe_world_model([_model([inferred, drifted]), _model([corrected, drifted_again])])
    assert probe.snapshots == 2
    assert probe.corrected == 1, "a statement overturning an inferred value is a correction"
    assert probe.rejected == 1, "and it rejected something the learner had guessed"
    assert probe.avg_evidence_count == 2.0

    # The learner moving on its own is NOT a correction: nobody said anything. `timing` changed
    # value between the two snapshots too, and it must not be counted.
    drift_only = probe_world_model([_model([drifted]), _model([drifted_again])])
    assert drift_only.corrected == 0
    assert drift_only.rejected == 0

    # ...and a correction that overturns a fixture rather than an inference is corrected but not
    # rejected: nothing was guessed, so nothing was overruled.
    seeded = _fact("timing", "morning", source_type=FactSourceType.FIXTURE, source="persona")
    over_fixture = probe_world_model([_model([seeded]), _model([drifted_again])])
    assert over_fixture.corrected == 0, "an inferred update is never a correction"

    assert probe_world_model([]).facts == 0
    assert probe_world_model([]).avg_evidence_count is None


def _probe_candidate(
    activity_id: str,
    title: str,
    activity_type: ActivityType,
    distance_m: int,
    indoor_outdoor: IndoorOutdoor = IndoorOutdoor.INDOOR,
) -> ActivityCandidate:
    return ActivityCandidate(
        activity_id=activity_id,
        source=ActivitySource.AAC_FIXTURE,
        integration_status=IntegrationStatus.FIXTURE,
        title=title,
        provider="Tampines AAC",
        start_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        location=ActivityLocation(name="Tampines AAC Centre"),
        category="Group class",
        activity_type=activity_type,
        indoor_outdoor=indoor_outdoor,
        retrieved_at=datetime(2026, 9, 13, tzinfo=UTC),
        distance_m=distance_m,
    )


def test_fact_contribution_separates_decorative_memory_from_memory_that_moves_the_slate() -> None:
    """The honest question about a memory feature is not "how many facts?" but "how many of them
    changed what the person was shown?". Leave-one-out over the real ranker is the only way to
    answer it; `facts_explanation_only` is the count of facts that reached a shown reason line
    and cost the ranking nothing.
    """
    candidates = [
        _probe_candidate(f"act-{index}", title, activity_type, distance, environment)
        for index, (title, activity_type, distance, environment) in enumerate(
            [
                ("Morning Tai Chi", ActivityType.TAI_CHI, 300, IndoorOutdoor.OUTDOOR),
                ("Community Choir", ActivityType.KARAOKE, 400, IndoorOutdoor.INDOOR),
                ("Garden Club", ActivityType.GARDENING, 500, IndoorOutdoor.OUTDOOR),
                ("Brisk Walk Group", ActivityType.WALKING, 4000, IndoorOutdoor.INDOOR),
            ]
        )
    ]
    preferences = ActivityPreferences(
        person_id="mdm-lim",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.ACTIVITY_TYPE,
                value=ActivityType.TAI_CHI.value,
                strength=0.8,
                source="senior_statement",
                observations=3,
                updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            DimensionPreference(
                dimension=PreferenceDimension.ENVIRONMENT,
                value="indoor",
                strength=0.6,
                source="inferred",
                observations=2,
                updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
        ],
    )
    case = RankingCase(
        case_id="case-1",
        candidates=tuple(candidates),
        intent=ActivityIntent(),
        preferences=preferences,
        today=date(2026, 9, 13),
    )

    contribution = probe_fact_contribution([case], top_k=3)
    assert contribution.cases == 1
    assert contribution.pairs == 2
    # Both tastes are read -- removing either moves a `preference` contribution...
    assert contribution.facts_consulted == 2
    # ...but only one of them changes which three listings the person is actually shown. The
    # other is decoration: the reason lines move, the slate does not. Separating the two is the
    # whole point of the probe, and printing "2 facts consulted" without it would be the
    # flattering half of the truth.
    assert contribution.facts_that_changed_top_k == 1
    assert contribution.facts_explanation_only == 1
    assert contribution.facts_never_read == 0
    # The three outcomes are mutually exclusive per pair, so they can never oversum.
    assert contribution.facts_that_changed_top_k + contribution.facts_explanation_only <= (
        contribution.pairs
    )

    # No preferences means no pairs, and no pretence that anything was measured.
    bare = RankingCase(
        case_id="case-0",
        candidates=tuple(candidates),
        intent=ActivityIntent(),
        preferences=ActivityPreferences(person_id="mdm-lim"),
    )
    assert probe_fact_contribution([bare]).pairs == 0


def test_fact_contribution_leaves_the_production_ranker_untouched() -> None:
    """The probe removes a fact and re-ranks. It must not mutate the caller's preferences: a
    measurement that changes what it measures is not one.
    """
    preferences = ActivityPreferences(
        person_id="mdm-lim",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.ACTIVITY_TYPE,
                value=ActivityType.TAI_CHI.value,
                strength=0.8,
                source="senior_statement",
                observations=3,
                updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        ],
    )
    before = preferences.model_dump()
    case = RankingCase(
        case_id="case-1",
        candidates=(_probe_candidate("act-0", "Morning Tai Chi", ActivityType.TAI_CHI, 300),),
        intent=ActivityIntent(),
        preferences=preferences,
    )
    probe_fact_contribution([case])
    assert preferences.model_dump() == before
