"""What a senior's own explanation of a quiet day may and may not change.

The assertion this file exists for is `test_no_explanation_can_stop_a_sustained_severe_decline`:
the bound in `context_explanation.EXPLANATION_MAX_SUSTAINED_DAYS` and the threshold on
`policy.decide`'s coordinator-review rung must stay disjoint, so that no answer a person can give
keeps a sustained, severe decline away from a human. Everything else here is the window arithmetic
and the two answers that deliberately explain nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from silverloop.context_explanation import (
    EXPLANATION_MAX_SUSTAINED_DAYS,
    active_explanation,
    explanation_for,
    explanation_window_days,
)
from silverloop.context_question import _OPTIONS
from silverloop.models import (
    ContextSignal,
    DataQualityAssessment,
    Decision,
    PolicyGate,
    SignalSummary,
)
from silverloop.policy import decide
from silverloop.review_threshold import (
    ABSOLUTE_REVIEW_FLOOR,
    DEFAULT_REVIEW_THRESHOLD,
    MIN_PERSISTENCE_DAYS,
)

NOW = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
DAY = date(2026, 8, 17)


def _quality(**overrides: object) -> DataQualityAssessment:
    defaults: dict[str, object] = dict(
        evidence_id="E-QUAL-1",
        assessed_at=NOW,
        source="synthetic",
        confidence=1.0,
        safe_to_interpret=True,
        reasons=["Wear-time is sufficient for behavioural interpretation."],
    )
    defaults.update(overrides)
    return DataQualityAssessment(**defaults)


def _signal(
    *,
    delta_percent: float,
    sustained_low_days: int,
    rainy: bool = False,
    confidence: float = 0.9,
    baseline: float = 6000.0,
    quality: DataQualityAssessment | None = None,
) -> SignalSummary:
    return SignalSummary(
        current_steps=int(baseline * (1 + delta_percent / 100)),
        delta_percent=delta_percent,
        baseline_median_steps=baseline,
        robust_z=-2.0,
        sustained_low_days=sustained_low_days,
        confidence=confidence,
        context=ContextSignal(rainy=rainy),
        quality=quality or _quality(),
    )


def _decide(signal: SignalSummary, explanation_value: str | None, *, stated_on: date = DAY):
    explanation = (
        None
        if explanation_value is None
        else explanation_for(explanation_value, stated_on=stated_on, day=DAY)
    )
    return decide(
        signal,
        consent_active=True,
        interventions_last_7_days=0,
        stated_explanation=explanation,
    )


# ── the invariant ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["away", "other_plans", "resting"])
def test_no_explanation_can_stop_a_sustained_severe_decline(value: str) -> None:
    """The load-bearing guarantee: a stated explanation never suppresses human review.

    Stated on the same day so the window is unambiguously in force -- the reason this returns
    COORDINATOR_REVIEW is the severity bound, not an expired explanation.
    """
    signal = _signal(delta_percent=-45.0, sustained_low_days=3)
    assert _decide(signal, value).decision is Decision.COORDINATOR_REVIEW


def test_the_explanation_bound_and_the_review_threshold_are_disjoint() -> None:
    """Stated as an arithmetic fact so a future edit to either number fails here first.

    Every review rung is covered: the shortest persistence any person's review setting may have
    (`MIN_PERSISTENCE_DAYS`, which bounds the default too) and the absolute review floor. So no
    calibrated setting can reopen a gap an explanation could slip a sustained decline through.
    """
    review_threshold_days = 3
    assert review_threshold_days >= EXPLANATION_MAX_SUSTAINED_DAYS
    assert MIN_PERSISTENCE_DAYS >= EXPLANATION_MAX_SUSTAINED_DAYS
    assert DEFAULT_REVIEW_THRESHOLD.persistence_days >= MIN_PERSISTENCE_DAYS
    assert ABSOLUTE_REVIEW_FLOOR.persistence_days >= EXPLANATION_MAX_SUSTAINED_DAYS


def test_an_explanation_given_every_day_still_escalates() -> None:
    """The person who says "I'm resting" all week is the case this bound exists for."""
    for day_count in (1, 2):
        assert (
            _decide(_signal(delta_percent=-45.0, sustained_low_days=day_count), "resting").decision
            is Decision.NO_ACTION
        )
    assert (
        _decide(_signal(delta_percent=-45.0, sustained_low_days=3), "resting").decision
        is Decision.COORDINATOR_REVIEW
    )


# ── the loop closing ──────────────────────────────────────────────────────────────────────────


def test_the_same_evidence_decides_differently_with_and_without_an_explanation() -> None:
    """F13's completion bar, reached with no model involved."""
    signal = _signal(delta_percent=-24.0, sustained_low_days=1)
    assert _decide(signal, None).decision is Decision.GENTLE_NUDGE
    explained = _decide(signal, "away")
    assert explained.decision is Decision.NO_ACTION
    assert explained.decided_by is PolicyGate.STATED_EXPLANATION


def test_a_suggestion_is_deferred_too_not_only_a_nudge() -> None:
    signal = _signal(delta_percent=-30.0, sustained_low_days=2)
    assert _decide(signal, None).decision is Decision.PROGRAMME_SUGGESTION
    assert _decide(signal, "away").decision is Decision.NO_ACTION


def test_the_rationale_names_the_person_and_the_expiry() -> None:
    result = _decide(_signal(delta_percent=-24.0, sustained_low_days=1), "away")
    assert "away from home" in result.rationale[0]
    assert "2026-08-19" in result.rationale[2], "the through-day must be recorded"


def test_the_person_is_preferred_over_the_weather_in_the_audit() -> None:
    """Both gates return NO_ACTION; the person's own account is the one recorded."""
    signal = _signal(delta_percent=-24.0, sustained_low_days=1, rainy=True)
    assert "Rain" not in " ".join(_decide(signal, "resting").rationale)
    assert "Rain" in " ".join(_decide(signal, None).rationale)


# ── the answers that explain nothing ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["not_feeling_it", "prefer_not_to_say"])
def test_two_answers_explain_nothing_by_design(value: str) -> None:
    assert explanation_window_days(value) is None
    assert explanation_for(value, stated_on=DAY, day=DAY) is None
    signal = _signal(delta_percent=-24.0, sustained_low_days=1)
    assert _decide(signal, value).decision is Decision.GENTLE_NUDGE


def test_every_offered_option_is_accounted_for() -> None:
    """No option may be silently unhandled: each either explains something or is a known no-op."""
    silent = {"not_feeling_it", "prefer_not_to_say"}
    for option in _OPTIONS:
        window = explanation_window_days(option.value)
        if option.value in silent:
            assert window is None, f"{option.value} must not explain anything"
        else:
            assert window is not None, f"{option.value} has no recorded effect"
            assert window >= 1


# ── the window ────────────────────────────────────────────────────────────────────────────────


def test_a_one_day_answer_does_not_reach_tomorrow() -> None:
    """`other_plans` is past tense about one day and makes no claim about the next."""
    assert explanation_for("other_plans", stated_on=DAY, day=DAY) is not None
    assert explanation_for("other_plans", stated_on=DAY, day=date(2026, 8, 18)) is None


def test_resting_reaches_tomorrow_but_not_the_day_after() -> None:
    """Two days, so it can actually defer a nudge -- see the window table's own note on why a
    one-day window is evidential only: the day an answer describes is already decided."""
    assert explanation_for("resting", stated_on=DAY, day=date(2026, 8, 18)) is not None
    assert explanation_for("resting", stated_on=DAY, day=date(2026, 8, 19)) is None


def test_away_covers_three_days_then_expires() -> None:
    covered = [date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)]
    for day in covered:
        assert explanation_for("away", stated_on=DAY, day=day) is not None, day
    assert explanation_for("away", stated_on=DAY, day=date(2026, 8, 20)) is None


def test_an_explanation_does_not_apply_before_it_was_given() -> None:
    assert explanation_for("away", stated_on=DAY, day=date(2026, 8, 16)) is None


def test_the_ladder_resumes_once_the_window_closes() -> None:
    signal = _signal(delta_percent=-24.0, sustained_low_days=1)
    expired = date(2026, 8, 13)
    assert _decide(signal, "away", stated_on=expired).decision is Decision.GENTLE_NUDGE


# ── resolving several answers ─────────────────────────────────────────────────────────────────


def test_the_most_recent_answer_wins() -> None:
    resolved = active_explanation(
        [("away", date(2026, 8, 15)), ("resting", DAY)],
        day=DAY,
    )
    assert resolved is not None
    assert resolved.value == "resting"


def test_a_row_without_a_scenario_day_is_skipped_not_guessed() -> None:
    assert active_explanation([("away", None)], day=DAY) is None


def test_no_answers_resolves_to_nothing() -> None:
    assert active_explanation([], day=DAY) is None


def test_only_silent_answers_resolve_to_nothing() -> None:
    assert active_explanation([("prefer_not_to_say", DAY)], day=DAY) is None


# ── precedence against the gates above it ─────────────────────────────────────────────────────


def test_consent_is_still_checked_first() -> None:
    signal = _signal(delta_percent=-24.0, sustained_low_days=1)
    result = decide(
        signal,
        consent_active=False,
        interventions_last_7_days=0,
        stated_explanation=explanation_for("away", stated_on=DAY, day=DAY),
    )
    assert result.decision is Decision.SUPPRESS


def test_an_explanation_cannot_rescue_an_uninterpretable_day() -> None:
    """The same reasoning that stops `self_reported_conflict` flipping `safe_to_interpret`."""
    unusable = _quality(
        safe_to_interpret=False, reasons=["Tracker wear-time was 2 hours."], confidence=0.25
    )
    signal = _signal(delta_percent=-24.0, sustained_low_days=1, quality=unusable)
    result = _decide(signal, "away")
    assert result.decision is Decision.NO_ACTION
    assert "wear-time" in " ".join(result.rationale).lower()
