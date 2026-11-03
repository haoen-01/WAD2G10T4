from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median

from silverloop.models import (
    BaselineSummary,
    ContextSignal,
    DailyMetric,
    SignalSummary,
)
from silverloop.quality import assess_data_quality

# How many valid-wear days form each of the two baselines.
BASELINE_WINDOW_DAYS = 28
REFERENCE_WINDOW_DAYS = 28

# A day counts as evidence about behaviour only if the tracker was worn long enough to mean
# anything. Below this it is neither a low day nor a normal one -- it is silence.
MINIMUM_WEAR_HOURS = 8.0

# How many consecutive silent days a run of low days can absorb before it stops being a run.
#
# The persistence counter used to `break` on any low-wear day, so a single missed charge read as
# recovery and collapsed a week-long decline to one day -- dropping the response two full action
# classes. Device non-compliance correlates with the people most worth noticing, so the system's
# answer to "we are missing data about someone already declining" must not be to become less
# concerned. Skipping is bounded: past this many gaps there genuinely is not enough evidence.
MAX_PERSISTENCE_GAP_DAYS = 2

# How far back the persistence scan looks. Wider than the run it can report, so that skipped
# low-wear days do not push real low days out of view.
PERSISTENCE_WINDOW_DAYS = 7

# A day is "low" below this fraction of the effective baseline.
LOW_DAY_FRACTION = 0.7

# How far the rolling baseline may sit below the anchored reference before it stops being
# believed.
#
# This is the fix for the defect that made a declining person invisible. A rolling median follows
# whoever it is measuring: someone whose activity falls and stays down drags their own baseline
# down with them, and within about a month the system reports them as normal -- measured at day 17
# for a 56% decline, and permanently thereafter. Clamping the baseline to a floor beneath the
# reference means a sustained fall keeps registering as a fall.
#
# 0.85 is deliberately generous. Real routines drift -- seasons, a knee, a house move -- and the
# clamp must not treat ordinary variation as decline. It only binds when someone has moved a long
# way from where they started and stayed there.
#
# The clamp does have a release, but it is not automatic: `calculate_reference` accepts an
# optional `ConfirmedReference`, written only once the person themselves has told Care+ a
# sustained clamp reflects their life now (see `baseline_confirmation.py` and
# `CANDIDATE_BASELINE_STREAK_DAYS` below for when that question is worth asking, and
# `BaselineConfirmationRow` for where the answer is durably recorded). Nothing here infers a new
# normal on its own -- that judgement about a person's life stays theirs, and a decline, or simply
# never asking, leaves the clamp bound exactly as it was.
BASELINE_DRIFT_FLOOR = 0.85

# How many of the most recent days, counting backward, the clamp above must have been binding --
# the rolling median genuinely sitting below `reference * BASELINE_DRIFT_FLOOR`, not merely
# today's single reading -- before it is worth asking whether this is the person's new normal.
#
# Deliberately its own constant rather than a reuse of `PERSISTENCE_WINDOW_DAYS` (7) or
# `BASELINE_WINDOW_DAYS` (28): those answer "is a decline happening right now, over the last
# week" and "how much history forms one rolling number", which are different questions on
# different timescales from "has this stopped being a decline and become how this person lives".
#
# The clamp itself needs about `BASELINE_WINDOW_DAYS` days to fully bind in the first place -- the
# rolling median only fully reflects a sustained fall once more than half its own window is low
# (measured at day 17 for a 28-day window; see `BASELINE_DRIFT_FLOOR`'s own comment). Requiring
# the clamp to have then stayed bound for a further `BASELINE_WINDOW_DAYS` means it has had one
# complete rolling window of its own to keep saying "yes, still true" before a life-change
# question is raised. Asking any sooner risks asking about exactly the ordinary variation --
# illness, travel, a bad few weeks -- that `BASELINE_DRIFT_FLOOR`'s generosity exists to absorb.
# Asking is a far bigger interruption than a nudge, so it has to earn a correspondingly higher
# bar. Chosen equal to `BASELINE_WINDOW_DAYS` on purpose, not by coincidence: the two windows are
# the same length because the justification above requires them to be, but they are named,
# tuned and can move independently.
CANDIDATE_BASELINE_STREAK_DAYS = BASELINE_WINDOW_DAYS

# Bound on how far back `clamp_streak_days` scans. Past this many days the exact count no longer
# changes anything -- the one thing the streak is used for is comparing against
# `CANDIDATE_BASELINE_STREAK_DAYS` -- so scanning further would only spend time confirming
# something already known, and cost would otherwise grow without limit for a person who has
# genuinely lived at their new level for a very long time.
CANDIDATE_BASELINE_STREAK_SCAN_LIMIT_DAYS = CANDIDATE_BASELINE_STREAK_DAYS * 3


@dataclass(frozen=True)
class ConfirmedReference:
    """A reference the person has explicitly agreed describes their life now.

    The one way `calculate_reference` returns anything other than the earliest-days median --
    see `BASELINE_DRIFT_FLOOR`'s own comment on the clamp's release. `days` is carried through only
    so `BaselineSummary.reference_window_days` keeps reporting how much evidence sits behind the
    number, the same promise it makes for the derived case.
    """

    steps: float
    days: int


def _mad(values: list[int], centre: float) -> float:
    return float(median([abs(value - centre) for value in values]))


def _valid(history: list[DailyMetric]) -> list[DailyMetric]:
    return [metric for metric in history if metric.wear_hours >= MINIMUM_WEAR_HOURS]


def calculate_reference(
    history: list[DailyMetric], *, confirmed: ConfirmedReference | None = None
) -> tuple[float, int]:
    """The anchored reference: the median over the earliest valid days on record.

    Computed from stored history rather than persisted, so it needs no migration and is
    reproducible from the same data every time. Returns `(median, days_used)`; `days_used` is
    reported so nobody has to guess how much evidence is behind the number.

    `confirmed`, when given, bypasses the earliest-days computation entirely and returns the
    person's own confirmed reference instead -- see `ConfirmedReference` and
    `BASELINE_DRIFT_FLOOR`'s own comment on why this is the clamp's only release.
    """
    if confirmed is not None:
        return confirmed.steps, confirmed.days
    valid = _valid(history)[:REFERENCE_WINDOW_DAYS]
    if not valid:
        return 0.0, 0
    return round(float(median([metric.steps for metric in valid])), 1), len(valid)


def calculate_baseline(
    history: list[DailyMetric], *, confirmed_reference: ConfirmedReference | None = None
) -> BaselineSummary:
    """Rolling baseline over the recent window, plus the anchored reference.

    `history` is the person's full record; the rolling window is taken from its tail and the
    reference from its head, so both come from one call and cannot disagree about the data.
    """
    window = history[-BASELINE_WINDOW_DAYS:]
    valid = _valid(window)
    values = [metric.steps for metric in valid]
    reference_steps, reference_days = calculate_reference(history, confirmed=confirmed_reference)
    if not values:
        return BaselineSummary(
            window_days=len(window),
            median_steps=0,
            mad_steps=0,
            data_quality=0,
            reference_steps=reference_steps,
            reference_window_days=reference_days,
        )
    centre = float(median(values))
    quality = min(1.0, len(valid) / max(1, len(window)))
    # The rolling median is reported as-is -- it is the honest answer to "what does a typical day
    # look like for them lately". The effective baseline is what the ladder reasons about.
    effective = max(centre, reference_steps * BASELINE_DRIFT_FLOOR)
    return BaselineSummary(
        window_days=len(window),
        median_steps=round(centre, 1),
        mad_steps=round(_mad(values, centre), 1),
        data_quality=round(quality, 3),
        reference_steps=reference_steps,
        reference_window_days=reference_days,
        effective_median_steps=round(effective, 1),
    )


def low_day_threshold(baseline: BaselineSummary) -> float:
    """The step count below which a worn day is a low day: `LOW_DAY_FRACTION` of the effective
    baseline (the rolling median when no clamp applies). Zero when there is no usual level, so
    nothing reads as low against a baseline of nothing."""
    effective = baseline.effective_median_steps or baseline.median_steps
    return max(0.0, effective) * LOW_DAY_FRACTION


def _sustained_low_days(history: list[DailyMetric], current: DailyMetric, threshold: float) -> int:
    """Consecutive low days, counting backwards, tolerating a bounded number of silent days.

    A day with too little wear-time is skipped rather than treated as the end of the run: missing
    data is not evidence of recovery. A genuinely normal day still ends the run, because that is
    real evidence. See `MAX_PERSISTENCE_GAP_DAYS`.
    """
    window = [*history[-(PERSISTENCE_WINDOW_DAYS - 1) :], current]
    sustained = 0
    gaps = 0
    for metric in reversed(window):
        if metric.wear_hours < MINIMUM_WEAR_HOURS:
            gaps += 1
            if gaps > MAX_PERSISTENCE_GAP_DAYS:
                break
            continue
        if metric.steps < threshold:
            sustained += 1
        else:
            break
    return sustained


def clamp_streak_days(history: list[DailyMetric], reference_steps: float) -> int:
    """How many of the most recent days, counting backward, `BASELINE_DRIFT_FLOOR` has been
    binding -- the rolling median genuinely sitting below `reference_steps * BASELINE_DRIFT_FLOOR`
    on that day, not merely today's single reading.

    Recomputes the rolling median as it would have read on each earlier day (the same tail-window
    logic `calculate_baseline` uses), rather than re-testing raw daily step counts the way
    `_sustained_low_days` does: what matters here is whether the clamp -- a statement about the
    rolling median -- has stayed bound, and a single low-wear day cannot end that on its own,
    because `_valid` already excludes it from the median rather than reading it as a recovery.
    `reference_steps` is held fixed across the whole scan (never recomputed per day): once
    `history` holds `REFERENCE_WINDOW_DAYS` valid days, `calculate_reference` is prefix-invariant --
    the earliest valid days it selects do not change as more days are appended -- so the reference
    that applies today applied on every earlier day too. See `CANDIDATE_BASELINE_STREAK_DAYS` for
    how this streak is used, and `CANDIDATE_BASELINE_STREAK_SCAN_LIMIT_DAYS` for why the scan is
    bounded rather than walking the entire history.
    """
    if reference_steps <= 0:
        return 0
    floor = reference_steps * BASELINE_DRIFT_FLOOR
    streak = 0
    earliest_cutoff = max(0, len(history) - CANDIDATE_BASELINE_STREAK_SCAN_LIMIT_DAYS)
    for cutoff in range(len(history), earliest_cutoff, -1):
        start = max(0, cutoff - BASELINE_WINDOW_DAYS)
        valid = _valid(history[start:cutoff])
        if not valid:
            break
        centre = median(metric.steps for metric in valid)
        if centre >= floor:
            break
        streak += 1
    return streak


def analyse_signal(
    history: list[DailyMetric],
    current: DailyMetric,
    context: ContextSignal,
    *,
    person_id: str,
    assessed_at: datetime,
    confirmed_reference: ConfirmedReference | None = None,
) -> tuple[BaselineSummary, SignalSummary]:
    quality = assess_data_quality(current, person_id=person_id, assessed_at=assessed_at)
    baseline = calculate_baseline(history, confirmed_reference=confirmed_reference)
    if not quality.safe_to_interpret:
        return baseline, SignalSummary(
            current_steps=current.steps,
            delta_percent=0,
            reference_delta_percent=0,
            robust_z=0,
            sustained_low_days=0,
            confidence=0,
            context=context,
            quality=quality,
        )
    # Every downstream judgement uses the effective baseline, not the raw rolling median: that is
    # the whole point of the clamp. `median_steps` remains available for display.
    effective = baseline.effective_median_steps or baseline.median_steps
    denominator = max(1.0, effective)
    delta = (current.steps - effective) / denominator
    scale = max(250.0, baseline.mad_steps * 1.4826)
    robust_z = (current.steps - effective) / scale
    # Zero reference means no valid history to anchor to; report no deviation rather than an
    # invented one against a baseline of nothing.
    if baseline.reference_steps > 0:
        reference_delta = (current.steps - baseline.reference_steps) / baseline.reference_steps
    else:
        reference_delta = 0.0
    sustained = _sustained_low_days(history, current, low_day_threshold(baseline))
    coverage = min(1.0, current.wear_hours / 12)
    confidence = baseline.data_quality * coverage
    if context.rainy:
        confidence *= 0.65
    return baseline, SignalSummary(
        current_steps=current.steps,
        delta_percent=round(delta * 100, 1),
        reference_delta_percent=round(reference_delta * 100, 1),
        baseline_median_steps=effective,
        robust_z=round(robust_z, 2),
        sustained_low_days=sustained,
        confidence=round(max(0, min(1, confidence)), 3),
        context=context,
        quality=quality,
    )
