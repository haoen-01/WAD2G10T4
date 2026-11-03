from datetime import UTC, date, datetime, timedelta

from silverloop.analytics import (
    CANDIDATE_BASELINE_STREAK_DAYS,
    ConfirmedReference,
    analyse_signal,
    calculate_reference,
    clamp_streak_days,
)
from silverloop.models import ContextSignal, DailyMetric

ASSESSMENT_TIME = datetime(2026, 1, 29, 12, tzinfo=UTC)


def metric(day_offset: int, steps: int, wear_hours: float = 13) -> DailyMetric:
    return DailyMetric(
        day=date(2026, 1, 1) + timedelta(days=day_offset),
        steps=steps,
        active_minutes=40,
        sleep_hours=7,
        wear_hours=wear_hours,
    )


def test_personal_baseline_and_sustained_signal() -> None:
    history = [metric(index, 6000 + (index % 3) * 100) for index in range(26)]
    history.extend([metric(26, 3100), metric(27, 3000)])
    baseline, signal = analyse_signal(
        history,
        metric(28, 2800),
        ContextSignal(),
        person_id="mdm-lim",
        assessed_at=ASSESSMENT_TIME,
    )

    assert 5900 < baseline.median_steps < 6200
    assert signal.delta_percent < -50
    assert signal.sustained_low_days == 3
    assert signal.confidence > 0.9


def test_low_wear_prevents_behavioural_interpretation() -> None:
    history = [metric(index, 6000) for index in range(28)]
    _, signal = analyse_signal(
        history,
        metric(28, 500, wear_hours=2),
        ContextSignal(),
        person_id="mdm-lim",
        assessed_at=ASSESSMENT_TIME,
    )

    assert signal.quality.safe_to_interpret is False
    assert signal.quality.assessed_at == ASSESSMENT_TIME
    assert signal.confidence == 0
    assert signal.sustained_low_days == 0
    assert signal.delta_percent == 0


# ── The candidate-baseline release: `clamp_streak_days` and `ConfirmedReference` ────────────────


def test_clamp_streak_days_is_zero_with_no_reference() -> None:
    history = [metric(index, 2500) for index in range(60)]
    assert clamp_streak_days(history, 0) == 0


def test_clamp_streak_days_requires_a_long_settled_decline() -> None:
    """A brief dip must not read as long enough to ask about; a genuinely long one must."""
    stable = [metric(index, 6000) for index in range(28)]

    short_decline = [*stable, *[metric(28 + index, 2500) for index in range(10)]]
    reference, _ = calculate_reference(short_decline)
    assert clamp_streak_days(short_decline, reference) < CANDIDATE_BASELINE_STREAK_DAYS

    long_decline = [*stable, *[metric(28 + index, 2500) for index in range(45)]]
    reference, _ = calculate_reference(long_decline)
    assert clamp_streak_days(long_decline, reference) >= CANDIDATE_BASELINE_STREAK_DAYS


def test_clamp_streak_days_survives_a_single_low_wear_gap() -> None:
    """A missed charge mid-decline must not read as recovery -- see `MAX_PERSISTENCE_GAP_DAYS`'s
    own reasoning, which this streak inherits by construction (via `_valid`) rather than
    duplicating.
    """
    stable = [metric(index, 6000) for index in range(28)]
    declining = [metric(28 + index, 2500) for index in range(20)]
    gap_day = [metric(48, 2500, wear_hours=2)]
    more_declining = [metric(49 + index, 2500) for index in range(20)]
    history = [*stable, *declining, *gap_day, *more_declining]
    reference, _ = calculate_reference(history)
    assert clamp_streak_days(history, reference) >= CANDIDATE_BASELINE_STREAK_DAYS


def test_clamp_streak_days_resets_once_activity_genuinely_recovers() -> None:
    stable = [metric(index, 6000) for index in range(28)]
    declining = [metric(28 + index, 2500) for index in range(45)]
    recovered = [metric(73 + index, 6000) for index in range(30)]
    history = [*stable, *declining, *recovered]
    reference, _ = calculate_reference(history)
    assert clamp_streak_days(history, reference) == 0


def test_confirmed_reference_bypasses_the_earliest_days_computation() -> None:
    history = [metric(index, 6000) for index in range(28)]
    confirmed = ConfirmedReference(steps=2500.0, days=32)
    assert calculate_reference(history, confirmed=confirmed) == (2500.0, 32)


def test_confirmed_reference_stops_the_clamp_from_binding() -> None:
    """The whole point of the release: once the person's own confirmed reference matches their
    settled activity, `effective_median_steps` stops sitting below the honest rolling median.
    """
    history = [metric(index, 2500) for index in range(60)]
    _, signal_without = analyse_signal(
        history,
        metric(60, 2500),
        ContextSignal(),
        person_id="mdm-lim",
        assessed_at=ASSESSMENT_TIME,
        confirmed_reference=ConfirmedReference(steps=6000.0, days=28),
    )
    assert signal_without.delta_percent < -50

    baseline_confirmed, signal_confirmed = analyse_signal(
        history,
        metric(60, 2500),
        ContextSignal(),
        person_id="mdm-lim",
        assessed_at=ASSESSMENT_TIME,
        confirmed_reference=ConfirmedReference(steps=2500.0, days=28),
    )
    assert baseline_confirmed.reference_steps == 2500.0
    assert baseline_confirmed.effective_median_steps == baseline_confirmed.median_steps
    assert signal_confirmed.delta_percent == 0
    assert signal_confirmed.sustained_low_days == 0
