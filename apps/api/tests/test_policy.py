from datetime import UTC, datetime

from silverloop.models import (
    ContextSignal,
    DataQualityAssessment,
    Decision,
    PolicyGate,
    SignalSummary,
)
from silverloop.policy import decide


def signal(**overrides: object) -> SignalSummary:
    values: dict[str, object] = {
        "current_steps": 2800,
        "delta_percent": -52,
        "robust_z": -3.2,
        "sustained_low_days": 3,
        "confidence": 0.95,
        "context": ContextSignal(),
        "quality": DataQualityAssessment(
            evidence_id="dq_2026-08-19_synthetic",
            assessed_at=datetime(2026, 8, 19, 12, tzinfo=UTC),
            source="synthetic",
            confidence=1.0,
            safe_to_interpret=True,
            reasons=["Wear-time is sufficient for behavioural interpretation."],
        ),
    }
    values.update(overrides)
    return SignalSummary.model_validate(values)


def test_sustained_decline_requires_human_review() -> None:
    result = decide(signal(), consent_active=True, interventions_last_7_days=0)
    assert result.decision == Decision.COORDINATOR_REVIEW


def test_consent_revocation_blocks_action() -> None:
    result = decide(signal(), consent_active=False, interventions_last_7_days=0)
    assert result.decision == Decision.SUPPRESS


def test_context_and_low_quality_prevent_overreaction() -> None:
    rainy = decide(
        signal(sustained_low_days=1, context=ContextSignal(rainy=True)),
        consent_active=True,
        interventions_last_7_days=0,
    )
    low_wear = decide(signal(confidence=0.1), consent_active=True, interventions_last_7_days=0)
    assert rainy.decision == Decision.NO_ACTION
    assert low_wear.decision == Decision.NO_ACTION


def test_unsafe_quality_is_a_hard_gate_even_with_high_confidence() -> None:
    reasons = ["Tracker wear-time was 7 hours; at least 8 hours is required."]
    unsafe_quality = DataQualityAssessment(
        evidence_id="dq_2026-08-19_synthetic",
        assessed_at=datetime(2026, 8, 19, 12, tzinfo=UTC),
        source="synthetic",
        confidence=0.875,
        safe_to_interpret=False,
        reasons=reasons,
    )

    result = decide(
        signal(confidence=0.95, quality=unsafe_quality),
        consent_active=True,
        interventions_last_7_days=0,
    )

    assert result.decision == Decision.NO_ACTION
    assert result.support_priority == 0
    assert result.rationale == reasons


def test_contact_cap_suppresses_notification() -> None:
    result = decide(
        signal(sustained_low_days=1, delta_percent=-30),
        consent_active=True,
        interventions_last_7_days=2,
    )
    assert result.decision == Decision.SUPPRESS


def test_accepted_cooldown_suppresses_and_says_so_rather_than_borrowing_the_weekly_cap() -> None:
    """The two fatigue guards share a rung, a decision and a support priority, so a `SUPPRESS`
    alone cannot say which one fired. Every consumer that wanted to caption the suppression had to
    reconstruct the ladder from `PersonState`, and the evaluator surface's reconstruction called
    this one "Weekly contact cap reached" -- exactly backwards for a person who was left alone
    *because* they had just taken a suggestion up. `decided_by` puts the answer on the result."""
    cooldown = decide(
        signal(sustained_low_days=1, delta_percent=-30),
        consent_active=True,
        interventions_last_7_days=0,
        days_since_last_accepted=1,
    )
    capped = decide(
        signal(sustained_low_days=1, delta_percent=-30),
        consent_active=True,
        interventions_last_7_days=2,
    )

    assert cooldown.decision == capped.decision == Decision.SUPPRESS
    assert cooldown.support_priority == capped.support_priority
    assert cooldown.decided_by == PolicyGate.ACCEPTED_COOLDOWN
    assert capped.decided_by == PolicyGate.CONTACT_CAP


def test_every_rung_of_the_ladder_names_the_gate_that_decided_it() -> None:
    """One case per guard clause, in ladder order. `decided_by` reports which clause returned,
    never an interpretation of the decision -- which is why `SUPPRESS` appears under two gates and
    `NO_ACTION` under five."""
    unsafe_quality = DataQualityAssessment(
        evidence_id="dq_2026-08-19_synthetic",
        assessed_at=datetime(2026, 8, 19, 12, tzinfo=UTC),
        source="synthetic",
        confidence=0.2,
        safe_to_interpret=False,
        reasons=["Tracker wear-time was 2.1 hours; at least 8 hours is required."],
    )
    cases: list[tuple[PolicyGate, Decision, SignalSummary, bool, int]] = [
        (PolicyGate.CONSENT, Decision.SUPPRESS, signal(), False, 0),
        (PolicyGate.DATA_QUALITY, Decision.NO_ACTION, signal(quality=unsafe_quality), True, 0),
        (PolicyGate.CONFIDENCE, Decision.NO_ACTION, signal(confidence=0.1), True, 0),
        (
            PolicyGate.RAIN_CONTEXT,
            Decision.NO_ACTION,
            signal(sustained_low_days=1, context=ContextSignal(rainy=True)),
            True,
            0,
        ),
        (
            PolicyGate.SMALL_BASELINE,
            Decision.NO_ACTION,
            signal(baseline_median_steps=120),
            True,
            0,
        ),
        (PolicyGate.SEVERITY_PERSISTENCE, Decision.COORDINATOR_REVIEW, signal(), True, 0),
        (
            PolicyGate.SEVERITY_PERSISTENCE,
            Decision.PROGRAMME_SUGGESTION,
            signal(sustained_low_days=2, delta_percent=-30),
            True,
            0,
        ),
        (
            PolicyGate.SEVERITY_PERSISTENCE,
            Decision.GENTLE_NUDGE,
            signal(sustained_low_days=1, delta_percent=-22),
            True,
            0,
        ),
        (
            PolicyGate.CONTACT_CAP,
            Decision.SUPPRESS,
            signal(sustained_low_days=1, delta_percent=-30),
            True,
            2,
        ),
        (
            PolicyGate.WITHIN_RANGE,
            Decision.NO_ACTION,
            signal(sustained_low_days=0, delta_percent=-3),
            True,
            0,
        ),
    ]

    for gate, decision, candidate, consent_active, contacts in cases:
        result = decide(
            candidate,
            consent_active=consent_active,
            interventions_last_7_days=contacts,
        )
        assert (result.decision, result.decided_by) == (decision, gate)
