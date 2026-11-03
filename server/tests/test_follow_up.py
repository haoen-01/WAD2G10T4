"""`follow_up.observe_effect` -- what happened in the days after one piece of outreach.

The risk this module carries is not arithmetic, it is overclaiming. It reads days a person lived
for a hundred reasons and puts them next to a text message, so the tests below are mostly about
what it must *refuse* to say: no observation without enough valid-wear days behind it, no "they
came back to normal" for a rise that did not come back to normal, no number anywhere without the
caveat that says a single record cannot show cause.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from silverloop.analytics import MINIMUM_WEAR_HOURS
from silverloop.follow_up import (
    CAVEAT,
    MINIMUM_VALID_DAYS_AFTER,
    RETURN_FRACTION,
    observe_effect,
)
from silverloop.models import DailyMetric, FollowUpObservation

OUTREACH_DAY = date(2026, 9, 1)
INTERVENTION = "intervention_test"

LOW_WEAR = MINIMUM_WEAR_HOURS - 1.0
GOOD_WEAR = MINIMUM_WEAR_HOURS + 2.0


def _metric(day: date, steps: int, wear_hours: float = GOOD_WEAR) -> DailyMetric:
    return DailyMetric(
        day=day,
        steps=steps,
        active_minutes=max(1, steps // 100),
        sleep_hours=7.0,
        wear_hours=wear_hours,
        source="synthetic",
    )


def _days(start_offset: int, steps: list[int], wear_hours: float = GOOD_WEAR) -> list[DailyMetric]:
    return [
        _metric(OUTREACH_DAY + timedelta(days=start_offset + index), value, wear_hours)
        for index, value in enumerate(steps)
    ]


def _observe(history: list[DailyMetric], reference_steps: float = 4000.0) -> FollowUpObservation:
    return observe_effect(
        intervention_id=INTERVENTION,
        outreach_day=OUTREACH_DAY,
        history=history,
        reference_steps=reference_steps,
    )


# ── Unavailable rather than thin ──────────────────────────────────────────────────────────────


def test_too_few_valid_days_after_is_unavailable_and_still_carries_the_caveat() -> None:
    """One day is not a week. Averaging it and presenting a number would be the whole failure."""
    history = [*_days(-3, [3000, 3000, 3000]), *_days(1, [3600])]

    observation = _observe(history)

    assert observation.available is False
    assert observation.reason_unavailable
    assert observation.caveat == CAVEAT
    # Every numeric field is meaningless when `available` is False and must not carry a stray
    # value a consumer could render.
    assert observation.change_percent == 0
    assert observation.steps_after == 0
    assert observation.returned_toward_usual is False


def test_the_minimum_is_a_boundary_not_a_suggestion() -> None:
    """One valid day short is unavailable; exactly the minimum is available."""
    before = _days(-3, [3000, 3000, 3000])

    short = _observe([*before, *_days(1, [3600] * (MINIMUM_VALID_DAYS_AFTER - 1))])
    exact = _observe([*before, *_days(1, [3600] * MINIMUM_VALID_DAYS_AFTER)])

    assert short.available is False
    assert exact.available is True
    assert exact.valid_days_observed == MINIMUM_VALID_DAYS_AFTER


def test_no_valid_days_before_the_outreach_is_unavailable() -> None:
    """Nothing to compare against is a different reason, and must be reported as its own."""
    history = [*_days(-3, [3000, 3000, 3000], wear_hours=LOW_WEAR), *_days(1, [3600, 3600, 3600])]

    observation = _observe(history)

    assert observation.available is False
    assert observation.reason_unavailable
    assert "before" in observation.reason_unavailable.lower()
    assert observation.caveat == CAVEAT


# ── "Came back toward what is usual" needs both halves ────────────────────────────────────────


def test_returned_toward_usual_requires_landing_near_the_reference_not_merely_rising() -> None:
    """Rising from very little to slightly more is a real change and is NOT a return.

    500 -> 900 steps is an 80% rise and nowhere near a 4,000-step reference. Reporting that as
    "back to what is usual for them" would be the most flattering available reading of the data
    and the least true one.
    """
    history = [*_days(-3, [500, 500, 500]), *_days(1, [900, 900, 900])]

    observation = _observe(history, reference_steps=4000.0)

    assert observation.available is True
    assert observation.steps_after > observation.steps_before
    assert observation.change_percent > 0
    assert observation.returned_toward_usual is False
    assert "a little higher" in observation.interpretation
    assert "usual" not in observation.interpretation


def test_returned_toward_usual_requires_rising_not_merely_sitting_near_the_reference() -> None:
    """The other half of the conjunction: already-at-reference days that then fall are not a
    return, however close to the reference they land."""
    reference = 4000.0
    history = [*_days(-3, [4200, 4200, 4200]), *_days(1, [3900, 3900, 3900])]

    observation = _observe(history, reference_steps=reference)

    assert observation.steps_after >= reference * RETURN_FRACTION
    assert observation.steps_after < observation.steps_before
    assert observation.returned_toward_usual is False
    assert "stayed lower" in observation.interpretation


def test_a_rise_that_lands_near_the_reference_is_a_return() -> None:
    reference = 4000.0
    history = [*_days(-3, [1500, 1500, 1500]), *_days(1, [3600, 3600, 3600])]

    observation = _observe(history, reference_steps=reference)

    assert observation.steps_after >= reference * RETURN_FRACTION
    assert observation.returned_toward_usual is True
    assert "usual" in observation.interpretation


def test_a_zero_reference_can_never_produce_a_return() -> None:
    """No anchored reference means nothing to return *to*; the honest answer is "went up"."""
    history = [*_days(-3, [500, 500, 500]), *_days(1, [9000, 9000, 9000])]

    observation = _observe(history, reference_steps=0.0)

    assert observation.available is True
    assert observation.returned_toward_usual is False


def test_unchanged_activity_is_described_as_unchanged() -> None:
    history = [*_days(-3, [3000, 3000, 3000]), *_days(1, [3000, 3000, 3000])]

    observation = _observe(history)

    assert observation.change_percent == 0
    assert observation.returned_toward_usual is False
    assert "about the same" in observation.interpretation


# ── Low-wear days are not evidence, on either side ────────────────────────────────────────────


def test_low_wear_days_are_excluded_from_both_windows() -> None:
    """A day the device was barely worn is a device fact, not an activity fact.

    Both planted low-wear days are extreme enough to move the medians visibly if they leaked in:
    9,000 steps just before the outreach and 50 steps just after.
    """
    history = [
        *_days(-4, [1000, 1000, 1000]),
        *_days(-1, [9000], wear_hours=LOW_WEAR),
        *_days(1, [50], wear_hours=LOW_WEAR),
        *_days(2, [2000, 2000]),
    ]

    observation = _observe(history)

    assert observation.available is True
    assert observation.steps_before == 1000
    assert observation.steps_after == 2000
    assert observation.valid_days_observed == 2
    # The observation window is anchored to the first *valid* day after, not the first day.
    assert observation.observed_from == OUTREACH_DAY + timedelta(days=2)


def test_low_wear_days_can_make_an_observation_unavailable_on_their_own() -> None:
    """Three days of data after the outreach, none of them wearable -- so, nothing to say."""
    history = [*_days(-3, [3000, 3000, 3000]), *_days(1, [3600, 3600, 3600], wear_hours=LOW_WEAR)]

    observation = _observe(history)

    assert observation.available is False
    assert observation.caveat == CAVEAT


def test_the_outreach_day_itself_belongs_to_neither_window() -> None:
    """The day the message was sent is ambiguous -- it is partly before and partly after."""
    history = [
        *_days(-3, [1000, 1000, 1000]),
        *_days(0, [9000]),
        *_days(1, [2000, 2000, 2000]),
    ]

    observation = _observe(history)

    assert observation.steps_before == 1000
    assert observation.steps_after == 2000


def test_history_order_does_not_change_the_result() -> None:
    history = [*_days(-3, [1000, 2000, 3000]), *_days(1, [4000, 5000, 6000])]

    ordered = _observe(list(history))
    shuffled = _observe(list(reversed(history)))

    assert ordered == shuffled


# ── No path produces a number without the warning beside it ───────────────────────────────────


@pytest.mark.parametrize(
    ("label", "history"),
    [
        ("no history at all", []),
        ("nothing before", [*_days(1, [3600, 3600, 3600])]),
        ("nothing after", [*_days(-3, [3000, 3000, 3000])]),
        ("too few after", [*_days(-3, [3000, 3000, 3000]), *_days(1, [3600])]),
        ("all low wear", _days(-3, [3000] * 6, wear_hours=LOW_WEAR)),
        ("a rise", [*_days(-3, [1000, 1000, 1000]), *_days(1, [3600, 3600, 3600])]),
        ("a fall", [*_days(-3, [3600, 3600, 3600]), *_days(1, [1000, 1000, 1000])]),
        ("no change", [*_days(-3, [3000, 3000, 3000]), *_days(1, [3000, 3000, 3000])]),
    ],
)
def test_every_result_carries_the_caveat(label: str, history: list[DailyMetric]) -> None:
    """The single most important property in this module.

    There must be no code path -- available, unavailable, up, down or flat -- that hands a
    consumer a description of someone's week without the sentence saying it is not a claim of
    cause. A caveat that only appears on the interesting results is a caveat nobody reads.
    """
    observation = _observe(history)

    assert observation.caveat, f"{label} produced a result with no caveat"
    assert observation.caveat == CAVEAT
    assert observation.intervention_id == INTERVENTION


def test_the_caveat_says_a_single_record_cannot_establish_cause() -> None:
    """Guards the wording, not just the presence of a string. This sentence is the boundary."""
    assert "not why" in CAVEAT
    assert "cannot show that a suggestion caused anything" in CAVEAT
    assert "evaluation harness" in CAVEAT
