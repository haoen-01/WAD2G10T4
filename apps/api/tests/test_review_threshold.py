"""The pure review-threshold rules: grid, policy rungs, live resolution, guardrail, fixed rule
and senior notice.

Every guardrail rule is pinned twice -- once passing, once failing with its fixed violation
string -- because the violation strings are read back to the calibrator, and a silently weakened
rule would only show up as a looser setting for a real person.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from silverloop.models import (
    CaseStatus,
    ContextSignal,
    DataQualityAssessment,
    Decision,
    HumanAction,
    OverrideReason,
    PolicyGate,
    ReviewThresholdCause,
    ReviewThresholdDecisionKind,
    ReviewThresholdNoticeKind,
    ReviewThresholdOutputKind,
    ReviewThresholdRejectionReason,
    ReviewThresholdRevertTrigger,
    ReviewThresholdValue,
    SignalSummary,
)
from silverloop.policy import decide
from silverloop.review_threshold import (
    ABSOLUTE_REVIEW_FLOOR,
    ALLOWED_THRESHOLDS,
    COOLDOWN_DAYS,
    DEFAULT_REVIEW_THRESHOLD,
    FIXED_RULE_DATA_DOUBT,
    FIXED_RULE_KNOWN_CONTEXT,
    FIXED_RULE_NO_REASON,
    FIXED_RULE_NOTHING_LEFT,
    FIXED_RULE_ROUND_ENDED,
    FIXED_RULE_WAITS_FOR_SECOND,
    LOOSENED_EXPIRY_DAYS,
    MAX_PERSISTENCE_DAYS,
    MAX_SEVERITY_PCT,
    MIN_PERSISTENCE_DAYS,
    MIN_SEVERITY_PCT,
    SENIOR_NOTICE_DAYS,
    SENIOR_NOTICE_LATER,
    SENIOR_NOTICE_SOONER,
    VIOLATION_CAUSE_REQUIRED,
    VIOLATION_CITATIONS,
    VIOLATION_COOLDOWN,
    VIOLATION_LOOSEN_CAUSE,
    VIOLATION_LOOSEN_REASON,
    VIOLATION_NOT_ONE_STEP,
    VIOLATION_OFF_GRID,
    VIOLATION_REPEATED_VALUE,
    FalseAlarmRef,
    FixedRuleOutput,
    ReviewThreshold,
    ThresholdDecisionFact,
    ThresholdVerdict,
    blocked_threshold_values,
    cooldown_until,
    fixed_rule_output,
    fixed_rule_tightening,
    has_expiry_clock,
    is_false_alarm,
    resolve_live_threshold,
    reverted_away_values,
    review_threshold_bounds,
    senior_notice_for,
    senior_notice_if_approved,
    validate_threshold_structure,
)

DAY = date(2026, 9, 1)
AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)

# Copied from `apps/e2e/tests/product-loop.spec.ts` (`SENIOR_SHELL_VOCABULARY`, flag `i`).
SENIOR_SHELL_VOCABULARY = re.compile(
    r"\b(?:stable|watch|review|\d+%|\d+ steps|time\(s\)|of \d+|anchor|they|their)\b",
    re.IGNORECASE,
)


def _signal(
    *,
    delta_percent: float,
    sustained_low_days: int,
    safe: bool = True,
    confidence: float = 0.95,
    baseline: float = 6000.0,
) -> SignalSummary:
    return SignalSummary(
        current_steps=int(baseline * (1 + delta_percent / 100)),
        delta_percent=delta_percent,
        baseline_median_steps=baseline,
        robust_z=-3.0,
        sustained_low_days=sustained_low_days,
        confidence=confidence,
        context=ContextSignal(),
        quality=DataQualityAssessment(
            evidence_id="dq_test",
            assessed_at=AT,
            source="synthetic",
            confidence=1.0,
            safe_to_interpret=safe,
            reasons=["Wear-time is sufficient for behavioural interpretation."],
        ),
    )


def _fact(
    decision_id: str,
    kind: ReviewThresholdDecisionKind,
    *,
    previous: ReviewThreshold,
    after: ReviewThreshold | None,
    decided_on: date,
    effective_from: date | None = None,
    trigger: ReviewThresholdRevertTrigger | None = None,
    ends: str | None = None,
    affects: str | None = None,
) -> ThresholdDecisionFact:
    return ThresholdDecisionFact(
        decision_id=decision_id,
        kind=kind,
        previous=previous,
        after=after,
        decided_on_day=decided_on,
        effective_from_day=effective_from or decided_on + timedelta(days=1),
        decided_at=datetime.combine(decided_on, datetime.min.time(), tzinfo=UTC),
        revert_trigger=trigger,
        ends_approval_id=ends,
        affects_decision_id=affects,
    )


T40_3 = DEFAULT_REVIEW_THRESHOLD
T40_4 = ReviewThreshold(40, 4)
T40_5 = ReviewThreshold(40, 5)
T45_3 = ReviewThreshold(45, 3)
T35_3 = ReviewThreshold(35, 3)


# ── Grid and bounds ───────────────────────────────────────────────────────────────────────────


def test_the_grid_is_exactly_fourteen_points_and_holds_the_default_but_not_the_floor() -> None:
    assert len(ALLOWED_THRESHOLDS) == 14
    assert len(set(ALLOWED_THRESHOLDS)) == 14
    assert {t.severity_pct for t in ALLOWED_THRESHOLDS} == {30, 35, 40, 45, 50, 55}
    assert {t.persistence_days for t in ALLOWED_THRESHOLDS} == {3, 4, 5}
    # No mixed settings: below the default's severity, only the default's three days.
    assert {t for t in ALLOWED_THRESHOLDS if t.severity_pct < 40} == {
        ReviewThreshold(30, 3),
        ReviewThreshold(35, 3),
    }
    for threshold in ALLOWED_THRESHOLDS:
        comparable = threshold == DEFAULT_REVIEW_THRESHOLD or threshold.looser_than(
            DEFAULT_REVIEW_THRESHOLD
        ) != threshold.stricter_than(DEFAULT_REVIEW_THRESHOLD)
        assert comparable, threshold
    assert (DEFAULT_REVIEW_THRESHOLD.severity_pct, DEFAULT_REVIEW_THRESHOLD.persistence_days) == (
        40,
        3,
    )
    assert DEFAULT_REVIEW_THRESHOLD.is_allowed
    assert (ABSOLUTE_REVIEW_FLOOR.severity_pct, ABSOLUTE_REVIEW_FLOOR.persistence_days) == (60, 3)
    assert not ABSOLUTE_REVIEW_FLOOR.is_allowed


def test_the_contract_bounds_agree_with_the_constants() -> None:
    """`models.py` repeats the grid as field bounds (it cannot import this module)."""
    for threshold in ALLOWED_THRESHOLDS:
        assert ReviewThreshold.from_value(threshold.as_value()) == threshold
    for severity, persistence in ((25, 3), (60, 3), (32, 3), (40, 2), (40, 6), (35, 4), (30, 5)):
        with pytest.raises(ValidationError):
            ReviewThresholdValue(severity_pct=severity, persistence_days=persistence)
    bounds = review_threshold_bounds()
    assert bounds.minimum.severity_pct == MIN_SEVERITY_PCT
    assert bounds.maximum.severity_pct == MAX_SEVERITY_PCT
    assert bounds.minimum.persistence_days == MIN_PERSISTENCE_DAYS
    assert bounds.maximum.persistence_days == MAX_PERSISTENCE_DAYS
    assert (bounds.floor.severity_pct, bounds.floor.persistence_days) == (60, 3)
    assert bounds.expiry_days == LOOSENED_EXPIRY_DAYS
    assert bounds.cooldown_days == COOLDOWN_DAYS


def test_fires_looser_and_stricter() -> None:
    assert T40_3.fires(40.0, 3)
    assert not T40_3.fires(39.9, 3)
    assert not T40_3.fires(80.0, 2)
    assert T40_4.looser_than(T40_3) and not T40_4.stricter_than(T40_3)
    assert T35_3.stricter_than(T40_3) and not T35_3.looser_than(T40_3)
    assert not T40_3.looser_than(T40_3) and not T40_3.stricter_than(T40_3)


# ── Policy rungs ──────────────────────────────────────────────────────────────────────────────


def test_default_rung_rationale_is_byte_identical_to_the_literal_it_replaced() -> None:
    result = decide(
        _signal(delta_percent=-45, sustained_low_days=3),
        consent_active=True,
        interventions_last_7_days=0,
    )
    assert result.decision is Decision.COORDINATOR_REVIEW
    assert result.support_priority == 80
    assert result.decided_by is PolicyGate.SEVERITY_PERSISTENCE
    assert result.rationale == [
        "Activity is more than 40% below the personal baseline.",
        "The decline has persisted for at least three valid-wear days.",
        "A human must review before any higher-touch outreach.",
    ]


def test_personal_rung_renders_the_person_s_own_setting() -> None:
    result = decide(
        _signal(delta_percent=-47, sustained_low_days=4),
        consent_active=True,
        interventions_last_7_days=0,
        review_threshold=ReviewThreshold(45, 4),
    )
    assert result.decided_by is PolicyGate.SEVERITY_PERSISTENCE
    assert result.rationale[:2] == [
        "Activity is more than 45% below the personal baseline.",
        "The decline has persisted for at least four valid-wear days.",
    ]


def test_floor_rung_fires_when_the_personal_setting_does_not() -> None:
    result = decide(
        _signal(delta_percent=-62, sustained_low_days=3),
        consent_active=True,
        interventions_last_7_days=5,
        review_threshold=ReviewThreshold(55, 5),
    )
    assert result.decision is Decision.COORDINATOR_REVIEW
    assert result.support_priority == 80
    assert result.decided_by is PolicyGate.REVIEW_FLOOR
    assert result.rationale == [
        "Activity is at least 60% below the personal baseline for at least three valid-wear days.",
        "This is Care+'s absolute review floor; it applies whatever this person's review "
        "setting is.",
        "A human must review before any higher-touch outreach.",
    ]


def test_shadow_rung_fires_below_the_personal_and_floor_rungs() -> None:
    since = date(2026, 8, 28)
    shadow = decide(
        _signal(delta_percent=-42, sustained_low_days=6),
        consent_active=True,
        interventions_last_7_days=5,
        review_threshold=T45_3,
        shadow_review_since=since,
    )
    assert shadow.decision is Decision.COORDINATOR_REVIEW
    assert shadow.support_priority == 80
    assert shadow.decided_by is PolicyGate.SHADOW_CHECK
    assert shadow.rationale == [
        "Care+'s starting review setting would have asked for a human on 2026-08-28.",
        "This person's own review setting has not asked within the 3-day grace period, so a "
        "human is asked now.",
        "A human must review before any higher-touch outreach.",
    ]
    personal_first = decide(
        _signal(delta_percent=-50, sustained_low_days=6),
        consent_active=True,
        interventions_last_7_days=0,
        review_threshold=T45_3,
        shadow_review_since=since,
    )
    assert personal_first.decided_by is PolicyGate.SEVERITY_PERSISTENCE


@pytest.mark.parametrize(
    ("kwargs", "gate", "decision"),
    [
        ({"consent_active": False}, PolicyGate.CONSENT, Decision.SUPPRESS),
        ({"safe": False}, PolicyGate.DATA_QUALITY, Decision.NO_ACTION),
        ({"confidence": 0.2}, PolicyGate.CONFIDENCE, Decision.NO_ACTION),
        ({"baseline": 300.0}, PolicyGate.SMALL_BASELINE, Decision.NO_ACTION),
    ],
)
def test_earlier_gates_precede_floor_and_shadow(
    kwargs: dict[str, object], gate: PolicyGate, decision: Decision
) -> None:
    overrides = dict(kwargs)
    consent = bool(overrides.pop("consent_active", True))
    signal = _signal(delta_percent=-70, sustained_low_days=5, **overrides)  # type: ignore[arg-type]
    result = decide(
        signal,
        consent_active=consent,
        interventions_last_7_days=0,
        review_threshold=ReviewThreshold(55, 5),
        shadow_review_since=date(2026, 8, 28),
    )
    assert (result.decision, result.decided_by) == (decision, gate)


def test_floor_and_shadow_are_unreachable_under_the_default() -> None:
    for severity in range(60, 101, 5):
        for sustained in range(3, 8):
            result = decide(
                _signal(delta_percent=-severity, sustained_low_days=sustained),
                consent_active=True,
                interventions_last_7_days=0,
            )
            assert result.decided_by is PolicyGate.SEVERITY_PERSISTENCE


# ── Live resolution ───────────────────────────────────────────────────────────────────────────


def test_no_facts_is_the_starting_setting() -> None:
    live = resolve_live_threshold([], DAY)
    assert live.threshold == DEFAULT_REVIEW_THRESHOLD
    assert live.source == "starting_setting"
    assert live.approval_id is None and not live.loosened
    assert live.effective_from_day is None and live.expires_on_day is None


def test_an_approval_takes_effect_the_next_day_and_expires_sixty_days_later() -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    assert resolve_live_threshold([approved], DAY).threshold == T40_3
    live = resolve_live_threshold([approved], DAY + timedelta(days=1))
    assert live.threshold == T40_4
    assert live.source == "approved" and live.approval_id == "A" and live.loosened
    # Approved on D, expires on D + 1 + 60.
    expires = DAY + timedelta(days=1 + LOOSENED_EXPIRY_DAYS)
    assert live.expires_on_day == expires
    assert resolve_live_threshold([approved], expires - timedelta(days=1)).threshold == T40_4
    lapsed = resolve_live_threshold([approved], expires)
    assert lapsed.threshold == T40_3
    assert lapsed.source == "expired" and lapsed.effective_from_day == expires


def test_the_expired_audit_row_does_not_pop_twice() -> None:
    base = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T35_3, decided_on=DAY
    )
    loosen = _fact(
        "B",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T35_3,
        after=ReviewThreshold(35, 4),
        decided_on=DAY + timedelta(days=10),
    )
    expires = loosen.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
    expired_row = _fact(
        "X",
        ReviewThresholdDecisionKind.EXPIRED,
        previous=ReviewThreshold(35, 4),
        after=T35_3,
        decided_on=expires,
        effective_from=expires,
        ends="B",
    )
    for day in (expires, expires + timedelta(days=5)):
        live = resolve_live_threshold([base, loosen, expired_row], day)
        # The tightening underneath (never loosened, so no clock) survives.
        assert live.threshold == T35_3
        assert live.approval_id == "A"
        assert live.source == "expired"


def test_a_two_level_expiry_chain_unwinds_in_one_read() -> None:
    first = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    second = _fact(
        "B",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T40_4,
        after=T40_5,
        decided_on=DAY + timedelta(days=20),
    )
    second_expires = second.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
    before = resolve_live_threshold([first, second], second_expires - timedelta(days=1))
    assert before.threshold == T40_5 and before.approval_id == "B"
    after = resolve_live_threshold([first, second], second_expires)
    assert after.threshold == DEFAULT_REVIEW_THRESHOLD
    assert after.source == "expired" and after.approval_id is None


def test_a_stricter_step_that_is_still_looser_than_the_default_keeps_an_expiry_clock() -> None:
    """Lead decision: 40%/4 days -> 35%/4 days asks sooner than the value it replaced but still
    waits longer than the starting setting, so it expires -- and it does not shield the loosening
    beneath it from expiring either."""
    first = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    t35_4 = ReviewThreshold(35, 4)
    second = _fact(
        "B",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T40_4,
        after=t35_4,
        decided_on=DAY + timedelta(days=10),
    )
    facts = [first, second]
    second_expires = second.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
    live = resolve_live_threshold(facts, second_expires - timedelta(days=1))
    assert live.threshold == t35_4 and live.approval_id == "B"
    assert live.loosened and live.expires_on_day == second_expires
    # B lapses, and A beneath it (whose own clock ran out earlier) lapses in the same read.
    lapsed = resolve_live_threshold(facts, second_expires)
    assert lapsed.threshold == DEFAULT_REVIEW_THRESHOLD
    assert lapsed.source == "expired" and lapsed.approval_id is None
    # A stricter step that lands back on the starting setting carries no clock.
    back = _fact(
        "C",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T45_3,
        after=T40_3,
        decided_on=DAY,
    )
    assert has_expiry_clock(T45_3, T40_3) is False
    assert has_expiry_clock(T40_4, t35_4) is True
    assert has_expiry_clock(T40_3, T35_3) is False
    assert resolve_live_threshold([back], DAY + timedelta(days=200)).expires_on_day is None
    # And no "wait longer" notice for the stricter step.
    assert senior_notice_for(facts, second.decided_on_day) is None


def test_reconfirming_restarts_the_clock() -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    original_expiry = approved.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
    reconfirmed = _fact(
        "R",
        ReviewThresholdDecisionKind.RECONFIRMED,
        previous=T40_4,
        after=T40_4,
        decided_on=original_expiry - timedelta(days=3),
        affects="A",
    )
    live = resolve_live_threshold([approved, reconfirmed], original_expiry)
    assert live.threshold == T40_4
    assert live.expires_on_day == reconfirmed.effective_from_day + timedelta(
        days=LOOSENED_EXPIRY_DAYS
    )
    assert live.source == "approved"
    # A reconfirmation recorded after the clock already ran out restores nothing.
    late = _fact(
        "L",
        ReviewThresholdDecisionKind.RECONFIRMED,
        previous=T40_4,
        after=T40_4,
        decided_on=original_expiry,
        affects="A",
    )
    assert (
        resolve_live_threshold([approved, late], original_expiry + timedelta(days=2)).threshold
        == DEFAULT_REVIEW_THRESHOLD
    )


def test_a_reached_too_late_revert_restores_the_previous_approved_value_next_day() -> None:
    first = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    second = _fact(
        "B",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T40_4,
        after=T40_5,
        decided_on=DAY + timedelta(days=10),
    )
    revert_day = DAY + timedelta(days=15)
    revert = _fact(
        "V",
        ReviewThresholdDecisionKind.REVERTED,
        previous=T40_5,
        after=T40_4,
        decided_on=revert_day,
        trigger=ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
        ends="B",
    )
    facts = [first, second, revert]
    assert resolve_live_threshold(facts, revert_day).threshold == T40_5
    live = resolve_live_threshold(facts, revert_day + timedelta(days=1))
    assert live.threshold == T40_4
    assert live.approval_id == "A" and live.loosened
    assert live.source == "reverted"
    assert live.effective_from_day == revert_day + timedelta(days=1)


def test_a_shadow_check_revert_clears_the_stack_back_to_the_default() -> None:
    first = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    second = _fact(
        "B",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T40_4,
        after=T40_5,
        decided_on=DAY + timedelta(days=10),
    )
    shadow = _fact(
        "S",
        ReviewThresholdDecisionKind.REVERTED,
        previous=T40_5,
        after=DEFAULT_REVIEW_THRESHOLD,
        decided_on=DAY + timedelta(days=20),
        trigger=ReviewThresholdRevertTrigger.SHADOW_CHECK,
        ends="B",
    )
    live = resolve_live_threshold([first, second, shadow], DAY + timedelta(days=21))
    assert live.threshold == DEFAULT_REVIEW_THRESHOLD
    assert live.source == "reverted" and live.approval_id is None


def test_rejections_checks_and_future_rows_change_nothing() -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    noise = [
        _fact(
            "J",
            ReviewThresholdDecisionKind.REJECTED,
            previous=T40_4,
            after=T40_5,
            decided_on=DAY + timedelta(days=2),
        ),
        _fact(
            "C",
            ReviewThresholdDecisionKind.CHECK_CONFIRMED,
            previous=T40_4,
            after=None,
            decided_on=DAY + timedelta(days=15),
        ),
        _fact(
            "U",
            ReviewThresholdDecisionKind.CHECK_UNRESOLVED,
            previous=T40_4,
            after=None,
            decided_on=DAY + timedelta(days=16),
        ),
        _fact(
            "F",
            ReviewThresholdDecisionKind.APPROVED,
            previous=T40_4,
            after=T40_5,
            decided_on=DAY + timedelta(days=40),
        ),
    ]
    live = resolve_live_threshold([approved, *noise], DAY + timedelta(days=20))
    assert live.threshold == T40_4 and live.approval_id == "A"


def test_a_revert_naming_an_approval_no_longer_live_is_a_no_op() -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    stray = _fact(
        "V",
        ReviewThresholdDecisionKind.REVERTED,
        previous=T40_4,
        after=T40_3,
        decided_on=DAY + timedelta(days=3),
        trigger=ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
        ends="missing",
    )
    live = resolve_live_threshold([approved, stray], DAY + timedelta(days=5))
    assert live.threshold == T40_4 and live.source == "approved"


def test_cooldown_and_blocked_values() -> None:
    assert cooldown_until([]) is None
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    rejected = _fact(
        "J",
        ReviewThresholdDecisionKind.REJECTED,
        previous=T40_4,
        after=T40_5,
        decided_on=DAY + timedelta(days=30),
    )
    assert cooldown_until([approved, rejected]) == DAY + timedelta(days=COOLDOWN_DAYS)
    reverted = _fact(
        "V",
        ReviewThresholdDecisionKind.REVERTED,
        previous=T40_4,
        after=T40_3,
        decided_on=DAY + timedelta(days=31),
        ends="A",
    )
    assert blocked_threshold_values([approved, rejected, reverted]) == {T40_5, T40_4}


# ── False alarms ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "action", "reason", "expected"),
    [
        (CaseStatus.RESOLVED, HumanAction.OVERRIDE, OverrideReason.NOT_A_CONCERN, True),
        (CaseStatus.RESOLVED, HumanAction.OVERRIDE, OverrideReason.KNOWN_CONTEXT, True),
        (CaseStatus.RESOLVED, HumanAction.OVERRIDE, OverrideReason.DATA_DOUBT, True),
        (CaseStatus.RESOLVED, HumanAction.OVERRIDE, OverrideReason.RECENT_CONTACT, False),
        (CaseStatus.RESOLVED, HumanAction.OVERRIDE, OverrideReason.OTHER, False),
        (CaseStatus.RESOLVED, HumanAction.OVERRIDE, None, False),
        (CaseStatus.RESOLVED, HumanAction.AGREE, OverrideReason.NOT_A_CONCERN, False),
        (CaseStatus.RESOLVED, None, None, False),
        (CaseStatus.ACKNOWLEDGED, HumanAction.OVERRIDE, OverrideReason.NOT_A_CONCERN, False),
        (CaseStatus.OPEN, HumanAction.HOLD, OverrideReason.NOT_A_CONCERN, False),
    ],
)
def test_is_false_alarm(
    status: CaseStatus,
    action: HumanAction | None,
    reason: OverrideReason | None,
    expected: bool,
) -> None:
    assert is_false_alarm(status, action, reason) is expected
    # Stored rows are strings; the answer must not depend on the type.
    assert (
        is_false_alarm(
            status.value, action.value if action else None, reason.value if reason else None
        )
        is expected
    )


# ── Structural guardrail ──────────────────────────────────────────────────────────────────────

KNOWN = {"review:1", "case:1", "day:2026-08-24"}


def _validate(**overrides: object) -> ThresholdVerdict:
    values: dict[str, object] = dict(
        live=T40_3,
        proposed=T40_4,
        cause=ReviewThresholdCause.TOO_TIGHT_FOR_PERSON,
        cited_evidence_ids=["review:1", "case:1"],
        known_evidence_ids=KNOWN,
        coordinator_reason=OverrideReason.NOT_A_CONCERN,
        facts=[],
        today=DAY,
    )
    values.update(overrides)
    return validate_threshold_structure(**values)  # type: ignore[arg-type]


def test_a_well_formed_loosening_passes() -> None:
    verdict = _validate()
    assert verdict.approved and verdict.violations == ()
    assert verdict.as_feedback() == "Approved."


def test_rule_1_cause_required_and_one_of_four() -> None:
    assert _validate(cause=None).violations == (VIOLATION_CAUSE_REQUIRED, VIOLATION_LOOSEN_CAUSE)
    assert VIOLATION_CAUSE_REQUIRED in _validate(cause="it_felt_wrong").violations
    no_change = _validate(proposed=None, cause=ReviewThresholdCause.ONE_OFF_EVENT)
    assert no_change.approved
    assert _validate(proposed=None, cause="worked_as_intended").approved
    assert _validate(proposed=None, cause=None, require_cause=False).approved
    assert not _validate(proposed=None, cause="nonsense", require_cause=False).approved


def test_rule_2_values_in_range_and_on_grid() -> None:
    off_top = _validate(live=ReviewThreshold(55, 3), proposed=ReviewThreshold(60, 3))
    assert off_top.violations == (VIOLATION_OFF_GRID,)
    off_bottom = _validate(live=ReviewThreshold(40, 3), proposed=ReviewThreshold(40, 2))
    assert VIOLATION_OFF_GRID in off_bottom.violations
    assert _validate(live=ReviewThreshold(50, 5), proposed=ReviewThreshold(55, 5)).approved


@pytest.mark.parametrize(
    "proposed",
    [ReviewThreshold(45, 4), ReviewThreshold(50, 3), ReviewThreshold(40, 5), T40_3],
)
def test_rule_3_exactly_one_dimension_by_exactly_one_step(proposed: ReviewThreshold) -> None:
    assert VIOLATION_NOT_ONE_STEP in _validate(proposed=proposed).violations
    assert _validate(proposed=T45_3).approved


def test_rule_4_cooldown_blocks_loosening_but_never_tightening() -> None:
    changed = _fact(
        "V",
        ReviewThresholdDecisionKind.REVERTED,
        previous=T45_3,
        after=T40_3,
        decided_on=DAY - timedelta(days=COOLDOWN_DAYS - 1),
    )
    loosening = _validate(facts=[changed], proposed=T40_4, blocked_values=set())
    assert loosening.violations == (VIOLATION_COOLDOWN,)
    tightening = _validate(
        facts=[changed],
        proposed=T35_3,
        cause=None,
        require_cause=False,
        coordinator_reason=None,
    )
    assert tightening.approved
    later = _validate(facts=[changed], proposed=T40_4, today=DAY + timedelta(days=1))
    assert later.approved
    rejection_only = _fact(
        "J", ReviewThresholdDecisionKind.REJECTED, previous=T40_3, after=T40_5, decided_on=DAY
    )
    assert _validate(facts=[rejection_only]).approved


def test_rule_5_citations_required_and_known() -> None:
    assert _validate(cited_evidence_ids=[]).violations == (VIOLATION_CITATIONS,)
    foreign = _validate(cited_evidence_ids=["review:1", "review:someone-else"])
    assert foreign.violations == (VIOLATION_CITATIONS,)
    assert VIOLATION_CITATIONS in _validate(proposed=None, cited_evidence_ids=[]).violations


def test_rule_6_repeated_rejected_or_reverted_value_blocks_loosening_only() -> None:
    rejected = _fact(
        "J",
        ReviewThresholdDecisionKind.REJECTED,
        previous=T40_3,
        after=T40_4,
        decided_on=DAY - timedelta(days=20),
    )
    assert _validate(facts=[rejected]).violations == (VIOLATION_REPEATED_VALUE,)
    reverted = _fact(
        "V",
        ReviewThresholdDecisionKind.REVERTED,
        previous=T45_3,
        after=T40_3,
        decided_on=DAY - timedelta(days=20),
    )
    assert _validate(facts=[reverted], proposed=T45_3).violations == (VIOLATION_REPEATED_VALUE,)
    assert _validate(proposed=T40_4, blocked_values={T40_4}).violations == (
        VIOLATION_REPEATED_VALUE,
    )
    # Restoring attention to a value once rejected is not a repeat of a loosening.
    tighten_back = _validate(
        live=T40_4,
        proposed=T40_3,
        facts=[rejected],
        blocked_values={T40_3},
        cause=None,
        require_cause=False,
    )
    assert tighten_back.approved


@pytest.mark.parametrize(
    "cause",
    [
        ReviewThresholdCause.ONE_OFF_EVENT,
        ReviewThresholdCause.BAD_DATA,
        ReviewThresholdCause.WORKED_AS_INTENDED,
    ],
)
def test_rule_7_loosening_requires_too_tight_for_person(cause: ReviewThresholdCause) -> None:
    assert _validate(cause=cause).violations == (VIOLATION_LOOSEN_CAUSE,)


@pytest.mark.parametrize(
    "reason",
    [
        OverrideReason.KNOWN_CONTEXT,
        OverrideReason.DATA_DOUBT,
        OverrideReason.RECENT_CONTACT,
        OverrideReason.OTHER,
        None,
    ],
)
def test_rule_8_loosening_requires_the_structured_not_a_concern_reason(
    reason: OverrideReason | None,
) -> None:
    assert _validate(coordinator_reason=reason).violations == (VIOLATION_LOOSEN_REASON,)


def test_feedback_numbers_every_violation() -> None:
    verdict = _validate(
        cause=ReviewThresholdCause.BAD_DATA, coordinator_reason=None, cited_evidence_ids=[]
    )
    assert not verdict.approved
    feedback = verdict.as_feedback()
    assert feedback.startswith("REJECTED by the deterministic safety gate.")
    assert "propose_threshold_change" in feedback
    for index, violation in enumerate(verdict.violations, 1):
        assert f"{index}. {violation}" in feedback


# ── Fixed-rule proposer ───────────────────────────────────────────────────────────────────────

TODAY = date(2026, 9, 30)


def _alarm(review_id: str, days_ago: int) -> FalseAlarmRef:
    return FalseAlarmRef(
        review_id=review_id,
        opened_day=TODAY - timedelta(days=days_ago),
        evidence_ids=(f"decision-{review_id}",),
    )


def _fixed(**overrides: object) -> FixedRuleOutput:
    trigger = _alarm("r2", 0)
    values: dict[str, object] = dict(
        live=T40_3,
        trigger_reason=OverrideReason.NOT_A_CONCERN,
        trigger=trigger,
        not_a_concern_alarms=[_alarm("r1", 20), trigger],
        today=TODAY,
        blocked_values=frozenset(),
    )
    values.update(overrides)
    return fixed_rule_output(**values)  # type: ignore[arg-type]


def test_known_context_and_data_doubt_never_propose() -> None:
    known = _fixed(trigger_reason=OverrideReason.KNOWN_CONTEXT)
    assert (known.output_kind, known.proposed, known.cause) == (
        ReviewThresholdOutputKind.NO_CHANGE,
        None,
        ReviewThresholdCause.ONE_OFF_EVENT,
    )
    assert known.reasoning == FIXED_RULE_KNOWN_CONTEXT
    assert known.cited == ("r2", "decision-r2")
    doubt = _fixed(trigger_reason=OverrideReason.DATA_DOUBT)
    assert (doubt.output_kind, doubt.cause) == (
        ReviewThresholdOutputKind.NO_CHANGE,
        ReviewThresholdCause.BAD_DATA,
    )
    assert doubt.reasoning == FIXED_RULE_DATA_DOUBT


@pytest.mark.parametrize("reason", [OverrideReason.RECENT_CONTACT, OverrideReason.OTHER, None])
def test_no_other_reason_loosens(reason: OverrideReason | None) -> None:
    output = _fixed(trigger_reason=reason)
    assert output.output_kind is ReviewThresholdOutputKind.NO_CHANGE
    assert output.proposed is None and output.cause is None
    assert output.reasoning == FIXED_RULE_NO_REASON


def test_one_not_a_concern_waits_for_a_second() -> None:
    output = _fixed(not_a_concern_alarms=[_alarm("r2", 0)])
    assert output.output_kind is ReviewThresholdOutputKind.NO_CHANGE
    assert output.cause is None
    assert output.reasoning == FIXED_RULE_WAITS_FOR_SECOND
    # A first alarm 30 days back is outside `[today - 29, today]`.
    stale = _fixed(not_a_concern_alarms=[_alarm("r1", 30), _alarm("r2", 0)])
    assert stale.output_kind is ReviewThresholdOutputKind.NO_CHANGE
    edge = _fixed(not_a_concern_alarms=[_alarm("r1", 29), _alarm("r2", 0)])
    assert edge.output_kind is ReviewThresholdOutputKind.PROPOSAL


def test_two_not_a_concern_within_thirty_days_propose_one_more_day() -> None:
    output = _fixed()
    assert output.output_kind is ReviewThresholdOutputKind.PROPOSAL
    assert output.proposed == T40_4
    assert output.cause is ReviewThresholdCause.TOO_TIGHT_FOR_PERSON
    assert output.cited == ("r1", "decision-r1", "r2", "decision-r2")
    verdict = validate_threshold_structure(
        live=T40_3,
        proposed=output.proposed,
        cause=output.cause,
        cited_evidence_ids=output.cited,
        known_evidence_ids=set(output.cited),
        coordinator_reason=OverrideReason.NOT_A_CONCERN,
        facts=[],
        today=TODAY,
    )
    assert verdict.approved, verdict.violations


def test_at_five_days_the_rule_moves_severity_and_skips_blocked_values() -> None:
    assert _fixed(live=T40_5).proposed == ReviewThreshold(45, 5)
    assert _fixed(blocked_values={T40_4}).proposed == T45_3
    exhausted = _fixed(live=ReviewThreshold(55, 5))
    assert exhausted.output_kind is ReviewThresholdOutputKind.NO_CHANGE
    assert exhausted.reasoning == FIXED_RULE_NOTHING_LEFT
    blocked_both = _fixed(blocked_values={T40_4, T45_3})
    assert blocked_both.output_kind is ReviewThresholdOutputKind.NO_CHANGE


def test_retry_after_rejection() -> None:
    other = _fixed(
        round_rejection=ReviewThresholdRejectionReason.PREFER_OTHER_CHANGE,
        rejected_proposal=T40_4,
        blocked_values={T40_4},
    )
    assert other.proposed == T45_3
    back = _fixed(
        round_rejection=ReviewThresholdRejectionReason.PREFER_OTHER_CHANGE,
        rejected_proposal=T45_3,
        blocked_values={T45_3},
    )
    assert back.proposed == T40_4
    for reason in (
        ReviewThresholdRejectionReason.CAUSE_DISPUTED,
        ReviewThresholdRejectionReason.NEED_MORE_EVIDENCE,
        ReviewThresholdRejectionReason.OTHER,
        ReviewThresholdRejectionReason.CONSENT_WITHDRAWN,
    ):
        ended = _fixed(round_rejection=reason, rejected_proposal=T40_4, blocked_values={T40_4})
        assert ended.output_kind is ReviewThresholdOutputKind.NO_CHANGE
        assert ended.reasoning == FIXED_RULE_ROUND_ENDED


def test_stage_three_tightening_helper() -> None:
    trigger = _alarm("late", 0)
    output = fixed_rule_tightening(live=T40_4, trigger=trigger)
    assert output.output_kind is ReviewThresholdOutputKind.PROPOSAL
    # 35%/4 days is off the grid: from the loosening side, one day fewer.
    assert output.proposed == T40_3
    assert fixed_rule_tightening(live=T40_3, trigger=trigger).proposed == T35_3
    assert output.cause is None
    assert output.cited == ("late", "decision-late")
    floored = fixed_rule_tightening(live=ReviewThreshold(30, 3), trigger=trigger)
    assert floored.output_kind is ReviewThresholdOutputKind.NO_CHANGE and floored.proposed is None


# ── Senior notice ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("message", [SENIOR_NOTICE_LATER, SENIOR_NOTICE_SOONER])
def test_notice_wording_passes_the_senior_vocabulary(message: str) -> None:
    assert SENIOR_SHELL_VOCABULARY.search(message) is None, message
    assert not any(character.isdigit() for character in message)


def test_notice_wording_is_fixed() -> None:
    assert SENIOR_NOTICE_LATER == (
        "Your care team has changed when Care+ lets them know about a quieter stretch. "
        "Because your activity naturally varies from week to week, Care+ will now wait a "
        "little longer before letting them know."
    )
    assert SENIOR_NOTICE_SOONER == (
        "Your care team has changed when Care+ lets them know about a quieter stretch. "
        "Care+ will now let them know a little sooner again, as it did before."
    )


def test_a_loosening_approval_shows_later_for_seven_days() -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    assert senior_notice_for([approved], DAY - timedelta(days=1)) is None
    for offset in range(SENIOR_NOTICE_DAYS):
        notice = senior_notice_for([approved], DAY + timedelta(days=offset))
        assert notice is not None
        assert notice.kind is ReviewThresholdNoticeKind.LATER
        assert notice.message == SENIOR_NOTICE_LATER
        assert notice.notice_id == "A" and notice.shown_from_day == DAY
    assert senior_notice_for([approved], DAY + timedelta(days=SENIOR_NOTICE_DAYS)) is None


@pytest.mark.parametrize(
    "kind", [ReviewThresholdDecisionKind.REVERTED, ReviewThresholdDecisionKind.EXPIRED]
)
def test_a_revert_or_expiry_that_asks_sooner_shows_sooner(
    kind: ReviewThresholdDecisionKind,
) -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    ended_on = DAY + timedelta(days=20)
    ended = _fact("E", kind, previous=T40_4, after=T40_3, decided_on=ended_on, ends="A")
    notice = senior_notice_for([approved, ended], ended_on + timedelta(days=2))
    assert notice is not None
    assert notice.kind is ReviewThresholdNoticeKind.SOONER
    assert notice.message == SENIOR_NOTICE_SOONER
    assert notice.notice_id == "E"


def test_no_notice_for_tightenings_or_superseded_changes() -> None:
    tightening = _fact(
        "T", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T35_3, decided_on=DAY
    )
    assert senior_notice_for([tightening], DAY) is None
    loosening = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    superseding = _fact(
        "B",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T40_4,
        after=ReviewThreshold(35, 4),
        decided_on=DAY + timedelta(days=1),
    )
    assert senior_notice_for([loosening, superseding], DAY + timedelta(days=2)) is None
    rejected = _fact(
        "J", ReviewThresholdDecisionKind.REJECTED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    assert senior_notice_for([rejected], DAY) is None


# ── Review fixes (stage-1 review round) ───────────────────────────────────────────────────────


def test_the_trigger_is_never_counted_on_top_of_the_callers_alarms() -> None:
    """The caller decides which alarms count (the repository drops alarms raised before the live
    setting took effect). A trigger it left out must not be added back to reach two."""
    output = _fixed(not_a_concern_alarms=[_alarm("r1", 5)], trigger=_alarm("r-old", 1))
    assert output.output_kind is ReviewThresholdOutputKind.NO_CHANGE
    assert output.reasoning == FIXED_RULE_WAITS_FOR_SECOND
    assert "r-old" not in output.cited
    nothing_counted = _fixed(not_a_concern_alarms=[], trigger=_alarm("r-old", 1))
    assert nothing_counted.output_kind is ReviewThresholdOutputKind.NO_CHANGE
    assert nothing_counted.cited == ("r-old", "decision-r-old")


@pytest.mark.parametrize(
    "reason",
    [ReviewThresholdRejectionReason.CONSENT_WITHDRAWN, ReviewThresholdRejectionReason.SUPERSEDED],
)
def test_a_system_rejection_never_blocks_the_value_from_being_proposed_again(
    reason: ReviewThresholdRejectionReason,
) -> None:
    system = ThresholdDecisionFact(
        decision_id="S",
        kind=ReviewThresholdDecisionKind.REJECTED,
        previous=T40_3,
        after=T40_4,
        decided_on_day=DAY,
        effective_from_day=DAY + timedelta(days=1),
        decided_at=AT,
        rejection_reason=reason,
    )
    coordinator = ThresholdDecisionFact(
        decision_id="C",
        kind=ReviewThresholdDecisionKind.REJECTED,
        previous=T40_3,
        after=T45_3,
        decided_on_day=DAY,
        effective_from_day=DAY + timedelta(days=1),
        decided_at=AT,
        rejection_reason=ReviewThresholdRejectionReason.OTHER,
    )
    assert blocked_threshold_values([system, coordinator]) == frozenset({T45_3})


def test_a_reconfirmation_restarts_only_the_approval_it_names() -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    expires = approved.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
    for affects in (None, "someone-else"):
        stray = _fact(
            "R",
            ReviewThresholdDecisionKind.RECONFIRMED,
            previous=T40_4,
            after=T40_4,
            decided_on=expires - timedelta(days=5),
            affects=affects,
        )
        live = resolve_live_threshold([approved, stray], expires)
        assert live.threshold == DEFAULT_REVIEW_THRESHOLD, affects


def test_reconfirming_on_the_last_live_day_keeps_the_setting() -> None:
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    expires = approved.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
    last_day = expires - timedelta(days=1)
    assert resolve_live_threshold([approved], last_day).approval_id == "A"
    reconfirmed = _fact(
        "R",
        ReviewThresholdDecisionKind.RECONFIRMED,
        previous=T40_4,
        after=T40_4,
        decided_on=last_day,
        affects="A",
    )
    live = resolve_live_threshold([approved, reconfirmed], expires)
    assert live.approval_id == "A"
    assert live.expires_on_day == expires + timedelta(days=LOOSENED_EXPIRY_DAYS)


def test_a_rejection_folded_after_the_expiry_day_does_not_itself_pop_the_stack() -> None:
    """Only facts that touch the stack trigger a stateless expiry check while folding."""
    approved = _fact(
        "A", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T40_4, decided_on=DAY
    )
    expires = approved.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
    # Same effective day as the reconfirmation, and folded first (ids break the tie).
    rejected = _fact(
        "Q",
        ReviewThresholdDecisionKind.REJECTED,
        previous=T40_4,
        after=T40_5,
        decided_on=expires - timedelta(days=1),
    )
    reconfirmed = _fact(
        "R",
        ReviewThresholdDecisionKind.RECONFIRMED,
        previous=T40_4,
        after=T40_4,
        decided_on=expires - timedelta(days=1),
        affects="A",
    )
    live = resolve_live_threshold([approved, rejected, reconfirmed], expires + timedelta(days=1))
    assert live.approval_id == "A"


def test_the_notice_a_proposal_would_produce_if_approved() -> None:
    later = senior_notice_if_approved(
        notice_id="P", previous=T40_3, proposed=T40_4, current_day=DAY
    )
    assert later is not None
    assert later.kind is ReviewThresholdNoticeKind.LATER
    assert later.message == SENIOR_NOTICE_LATER
    assert (later.notice_id, later.shown_from_day) == ("P", DAY)
    assert (
        senior_notice_if_approved(notice_id="P", previous=T40_3, proposed=T35_3, current_day=DAY)
        is None
    )


@pytest.mark.parametrize("reason", ["consent_withdrawn", "superseded"])
def test_system_rejection_reasons_are_refused_on_a_request(reason: str) -> None:
    from silverloop.models import ReviewThresholdRejectRequest

    with pytest.raises(ValidationError):
        ReviewThresholdRejectRequest(reason=reason)  # type: ignore[arg-type]


def test_every_value_an_ended_approval_held_counts_as_reverted_away_from() -> None:
    a1 = _fact(
        "A1", ReviewThresholdDecisionKind.APPROVED, previous=T40_3, after=T45_3, decided_on=DAY
    )
    a2 = _fact(
        "A2",
        ReviewThresholdDecisionKind.APPROVED,
        previous=T45_3,
        after=ReviewThreshold(45, 4),
        decided_on=DAY + timedelta(days=1),
    )
    a3 = _fact(
        "A3",
        ReviewThresholdDecisionKind.APPROVED,
        previous=ReviewThreshold(45, 4),
        after=T40_4,
        decided_on=DAY + timedelta(days=2),
    )
    later = DAY + timedelta(days=5)
    ends = [
        _fact(
            f"V{name}",
            ReviewThresholdDecisionKind.REVERTED,
            previous=T40_4,
            after=T40_3,
            decided_on=later,
            trigger=ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
            ends=name,
        )
        for name in ("A3", "A2", "A1")
    ]
    values = reverted_away_values([a1, a2, a3, *ends])
    assert values == frozenset({T45_3, ReviewThreshold(45, 4), T40_4})
    assert values <= blocked_threshold_values([a1, a2, a3, *ends])
