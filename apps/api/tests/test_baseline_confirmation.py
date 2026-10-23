"""The other question worth asking: "is this your new normal?"

These tests pin the restraint `baseline_confirmation.py` exists to enforce -- see its own module
docstring. Every "no question" case here mirrors a specific guard in `question_for`, so a future
change that quietly starts asking sooner, or keeps asking through a decline, fails loudly here
first.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from silverloop.analytics import CANDIDATE_BASELINE_STREAK_DAYS
from silverloop.baseline_confirmation import (
    DECLINE_COOLDOWN_DAYS,
    QUESTION_ID,
    question_for,
)
from silverloop.models import (
    AttentionBand,
    BaselineConfirmationDecision,
    BaselineSummary,
    ContextSignal,
    DataQualityAssessment,
    Decision,
    PersonState,
    PolicyGate,
    SignalSummary,
)

NOW = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
TODAY = date(2026, 9, 6)


def _quality(**overrides: object) -> DataQualityAssessment:
    defaults: dict[str, object] = dict(
        evidence_id="E-QUAL-1",
        assessed_at=NOW,
        source="synthetic",
        confidence=0.9,
        safe_to_interpret=True,
        reasons=[],
    )
    defaults.update(overrides)
    return DataQualityAssessment(**defaults)


def _signal(**overrides: object) -> SignalSummary:
    defaults: dict[str, object] = dict(
        current_steps=2500,
        delta_percent=-48.8,
        baseline_median_steps=4885,
        robust_z=-6.0,
        sustained_low_days=7,
        confidence=0.9,
        context=ContextSignal(),
        quality=_quality(),
    )
    defaults.update(overrides)
    return SignalSummary(**defaults)


def _state(**overrides: object) -> PersonState:
    defaults: dict[str, object] = dict(
        person_id="p1",
        display_name="Test Person",
        preferred_language="en",
        consent_active=True,
        current_day=TODAY,
        attention_band=AttentionBand.REVIEW,
        baseline=BaselineSummary(
            window_days=28,
            median_steps=2500,
            mad_steps=0,
            data_quality=1.0,
            reference_steps=5747,
            reference_window_days=28,
            effective_median_steps=4884.9,
        ),
        signal=_signal(),
        last_decision=Decision.COORDINATOR_REVIEW,
        rationale=["Activity is more than 40% below the personal baseline."],
        decided_by_gate=PolicyGate.SEVERITY_PERSISTENCE,
        permitted_actions=[Decision.COORDINATOR_REVIEW, Decision.NO_ACTION],
    )
    defaults.update(overrides)
    return PersonState(**defaults)


# ── Asked only when the clamp has been bound long enough ────────────────────────────────────────


def test_asks_once_the_clamp_has_been_bound_long_enough() -> None:
    question = question_for(
        _state(),
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS,
        last_decision=None,
        last_decided_on=None,
    )
    assert question is not None
    assert question.question_id == QUESTION_ID
    assert question.streak_days == CANDIDATE_BASELINE_STREAK_DAYS


def test_a_shorter_streak_asks_nothing() -> None:
    question = question_for(
        _state(),
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS - 1,
        last_decision=None,
        last_decided_on=None,
    )
    assert question is None


def test_no_anchored_reference_asks_nothing() -> None:
    state = _state(
        baseline=BaselineSummary(
            window_days=0, median_steps=0, mad_steps=0, data_quality=0, reference_steps=0
        )
    )
    question = question_for(
        state,
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS + 10,
        last_decision=None,
        last_decided_on=None,
    )
    assert question is None


def test_consent_off_asks_nothing() -> None:
    state = _state(
        consent_active=False,
        last_decision=Decision.SUPPRESS,
        permitted_actions=[Decision.SUPPRESS],
    )
    question = question_for(
        state,
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS + 10,
        last_decision=None,
        last_decided_on=None,
    )
    assert question is None


def test_unreliable_tracker_asks_nothing() -> None:
    state = _state(signal=_signal(quality=_quality(safe_to_interpret=False)))
    question = question_for(
        state,
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS + 10,
        last_decision=None,
        last_decided_on=None,
    )
    assert question is None


# ── A decline starts a cooldown, not a permanent silence ────────────────────────────────────────


def test_a_recent_decline_suppresses_a_repeat_question() -> None:
    question = question_for(
        _state(),
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS + 5,
        last_decision=BaselineConfirmationDecision.DECLINE,
        last_decided_on=TODAY,
    )
    assert question is None


def test_the_cooldown_eventually_expires() -> None:
    from datetime import timedelta

    state = _state(current_day=TODAY + timedelta(days=DECLINE_COOLDOWN_DAYS))
    question = question_for(
        state,
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS + 5,
        last_decision=BaselineConfirmationDecision.DECLINE,
        last_decided_on=TODAY,
    )
    assert question is not None


def test_a_prior_confirm_does_not_suppress_a_fresh_streak() -> None:
    """A second life change deserves its own question, with no cooldown -- only a decline waits."""
    question = question_for(
        _state(),
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS,
        last_decision=BaselineConfirmationDecision.CONFIRM,
        last_decided_on=TODAY,
    )
    assert question is not None


# ── Never internal vocabulary ─────────────────────────────────────────────────────────────────


def test_question_text_never_uses_internal_vocabulary() -> None:
    """Mirrors what `apps/e2e/tests/product-loop.spec.ts` asserts about the senior surface: no
    band names, no raw percentages, no coordinator vocabulary in anything shown to the person.
    """
    import re

    forbidden = re.compile(r"\b(?:stable|watch|review|\d+%)\b", re.IGNORECASE)
    question = question_for(
        _state(),
        clamp_streak_days=CANDIDATE_BASELINE_STREAK_DAYS,
        last_decision=None,
        last_decided_on=None,
    )
    assert question is not None
    assert forbidden.search(question.question) is None
