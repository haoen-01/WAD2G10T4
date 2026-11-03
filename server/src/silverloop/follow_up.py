from __future__ import annotations

from datetime import date
from statistics import median

from silverloop.analytics import MINIMUM_WEAR_HOURS
from silverloop.models import DailyMetric, FollowUpObservation

# How many days after outreach to look at. Short on purpose: this is a description of the days
# immediately around one suggestion, not a claim about a person's trajectory, and a longer window
# would collect so much unrelated life that attributing any of it to a text message would be
# absurd. It is already a stretch at three days, which is what `caveat` exists to say.
OBSERVATION_WINDOW_DAYS = 3

# The comparison window before the outreach day, so "after" is measured against the days that
# actually prompted the suggestion rather than against a long-run average.
COMPARISON_WINDOW_DAYS = 3

# Below this many valid-wear days after the outreach there is nothing to say, and the observation
# reports itself unavailable rather than averaging one day and calling it a week.
MINIMUM_VALID_DAYS_AFTER = 2

# How close to the anchored reference counts as "back toward what was usual for them". Matches
# `BASELINE_DRIFT_FLOOR` in spirit: the same generous band, because a person is not required to
# hit their exact former median to have had a better week.
RETURN_FRACTION = 0.85

CAVEAT = (
    "This describes what happened, not why. One person over a few days cannot show that a "
    "suggestion caused anything -- people get more active for every reason there is. Comparing "
    "outreach against no outreach is done across many people in the evaluation harness, never "
    "from a single record like this one."
)


def _valid(metrics: list[DailyMetric]) -> list[DailyMetric]:
    return [metric for metric in metrics if metric.wear_hours >= MINIMUM_WEAR_HOURS]


def _unavailable(intervention_id: str, reason: str) -> FollowUpObservation:
    return FollowUpObservation(
        intervention_id=intervention_id,
        available=False,
        reason_unavailable=reason,
        caveat=CAVEAT,
    )


def observe_effect(
    *,
    intervention_id: str,
    outreach_day: date,
    history: list[DailyMetric],
    reference_steps: float,
) -> FollowUpObservation:
    """Describe what a person's activity did in the days after one piece of outreach.

    Every input here was already being written to disk and never read back. That gap is why the
    product could describe what it decided but never whether reaching out was worth doing.

    Deliberately descriptive, never causal. The function reports medians, a direction, and a
    sentence a person could read, and it attaches `CAVEAT` to every result including the
    unavailable ones -- so there is no code path that produces a number without the warning that
    belongs beside it.
    """
    ordered = sorted(history, key=lambda metric: metric.day)
    before = _valid([metric for metric in ordered if metric.day < outreach_day])
    after = _valid([metric for metric in ordered if metric.day > outreach_day])[
        :OBSERVATION_WINDOW_DAYS
    ]

    if not before:
        return _unavailable(intervention_id, "No valid-wear days before the suggestion.")
    if len(after) < MINIMUM_VALID_DAYS_AFTER:
        return _unavailable(
            intervention_id,
            "Not enough days have been recorded since the suggestion yet.",
        )

    window_before = before[-COMPARISON_WINDOW_DAYS:]
    steps_before = float(median([metric.steps for metric in window_before]))
    steps_after = float(median([metric.steps for metric in after]))
    change_percent = round((steps_after - steps_before) / max(1.0, steps_before) * 100, 1)

    # Both conditions matter. Activity has to have gone up AND landed somewhere near where this
    # person used to be -- rising from very little to slightly more is a real change but it is not
    # a return, and calling it one would overstate what happened.
    returned = bool(
        reference_steps > 0
        and steps_after > steps_before
        and steps_after >= reference_steps * RETURN_FRACTION
    )

    if returned:
        interpretation = "In the days after, activity came back close to what is usual for them."
    elif steps_after > steps_before:
        interpretation = "In the days after, activity was a little higher than the days before."
    elif steps_after < steps_before:
        interpretation = "In the days after, activity stayed lower than the days before."
    else:
        interpretation = "In the days after, activity was about the same as the days before."

    return FollowUpObservation(
        intervention_id=intervention_id,
        available=True,
        observed_from=after[0].day,
        observed_to=after[-1].day,
        days_observed=(after[-1].day - after[0].day).days + 1,
        valid_days_observed=len(after),
        steps_before=round(steps_before, 1),
        steps_after=round(steps_after, 1),
        change_percent=change_percent,
        reference_steps=round(reference_steps, 1),
        returned_toward_usual=returned,
        interpretation=interpretation,
        caveat=CAVEAT,
    )
