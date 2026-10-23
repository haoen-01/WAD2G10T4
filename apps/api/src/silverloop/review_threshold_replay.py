"""Per-day signal series for the review threshold: the shadow check, the replay and variability.

Pure over data the caller hands in -- it imports `analytics`, `policy` and `review_threshold`, and
never the database. The repository feeds it stored rows (as `DailyMetric`s, their contexts, and two
callables answering "what did this person confirm / dispute, as of that day"), so the per-day
signals here are recomputed exactly as `SqlAlchemyRepository._evaluate` computes today's.

Three consumers:

- `shadow_review_since`, read on every evaluation of a person whose live setting is looser than
  the starting setting. Stateless: it derives the answer from history and writes nothing.
- `replay_thresholds`, the code-computed "what would the candidate setting have done over the
  last eight weeks" table a coordinator sees before approving.
- `variability_summary`, the normal-variability facts the stage-2 agent reads.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from typing import Literal

from silverloop.analytics import ConfirmedReference, analyse_signal
from silverloop.models import (
    ContextSignal,
    DailyMetric,
    Decision,
    PolicyGate,
    ReviewThresholdReplay,
    ReviewThresholdReplayEpisode,
    SignalSummary,
)
from silverloop.policy import decide
from silverloop.quality import assess_data_quality
from silverloop.review_threshold import (
    DEFAULT_REVIEW_THRESHOLD,
    REPLAY_WINDOW_DAYS,
    SHADOW_GRACE_DAYS,
    SHADOW_SCAN_DAYS,
    ReviewThreshold,
)

REPLAY_DISCLOSURE = "Calculated by code from stored synthetic history; not written by a model."

# The shortfalls the variability summary reports shares for, and the run lengths it counts.
VARIABILITY_SEVERITY_PCTS: tuple[int, ...] = (40, 45, 50, 55, 60)
VARIABILITY_RUN_DAYS: tuple[int, ...] = (3, 4, 5)


@dataclass(frozen=True)
class DaySignal:
    day: date
    signal: SignalSummary


def day_signals(
    metrics: Sequence[DailyMetric],
    contexts: Sequence[ContextSignal],
    *,
    person_id: str,
    last_n: int,
    confirmed_reference_on: Callable[[date], ConfirmedReference | None],
    conflict_on: Callable[[date], tuple[bool, str | None]],
) -> list[DaySignal]:
    """The signal for each of the last `last_n` stored days, as `_evaluate` computed it that day.

    `metrics` is the run's full stored history in day order and `contexts[i]` is the stored
    `context_json` of `metrics[i]`. Each day is analysed over every earlier row (not just the
    window), with the confirmed reference in force that day and that day's self-reported conflict
    folded back into the quality assessment -- the same three steps `_evaluate` takes for today.
    """
    if len(metrics) != len(contexts):
        raise ValueError("metrics and contexts must be parallel sequences")
    if last_n <= 0 or not metrics:
        return []
    ordered = list(metrics)
    signals: list[DaySignal] = []
    for index in range(max(0, len(ordered) - last_n), len(ordered)):
        current = ordered[index]
        assessment_time = datetime.combine(current.day, time(hour=12), tzinfo=UTC)
        _, signal = analyse_signal(
            ordered[:index],
            current,
            contexts[index],
            person_id=person_id,
            assessed_at=assessment_time,
            confirmed_reference=confirmed_reference_on(current.day),
        )
        conflict, conflict_note = conflict_on(current.day)
        if conflict:
            signal = signal.model_copy(
                update={
                    "quality": assess_data_quality(
                        current,
                        person_id=person_id,
                        assessed_at=assessment_time,
                        self_reported_conflict=True,
                        self_reported_conflict_note=conflict_note,
                    )
                }
            )
        signals.append(DaySignal(day=current.day, signal=signal))
    return signals


def review_fires(signal: SignalSummary, threshold: ReviewThreshold) -> bool:
    """Whether the ladder would ask a human that day under `threshold` (the floor included).

    Consent on and no contacts: the question is what the threshold does, and every review rung
    sits above the contact gates anyway.
    """
    return (
        decide(
            signal,
            consent_active=True,
            interventions_last_7_days=0,
            review_threshold=threshold,
        ).decision
        is Decision.COORDINATOR_REVIEW
    )


def _closes_episode(signal: SignalSummary) -> bool:
    """The recovery-close predicate: an interpretable day that is not low.

    A low-wear day is silence, not recovery, so it never ends an episode.
    """
    return signal.quality.safe_to_interpret and signal.sustained_low_days == 0


def _open_episode(days: Sequence[DaySignal]) -> list[DaySignal] | None:
    """The unfinished episode ending on the last day, scanning back at most `SHADOW_SCAN_DAYS`.

    `None` when the last day itself closes an episode.
    """
    if not days or _closes_episode(days[-1].signal):
        return None
    today = days[-1].day
    earliest = today - timedelta(days=SHADOW_SCAN_DAYS)
    episode: list[DaySignal] = []
    for entry in reversed(days):
        if entry.day <= earliest or _closes_episode(entry.signal):
            break
        episode.append(entry)
    episode.reverse()
    return episode


def shadow_review_since(
    days: Sequence[DaySignal], *, threshold_on: Callable[[date], ReviewThreshold]
) -> date | None:
    """The day the starting setting would have asked, when a looser setting still has not.

    For today `D` (the last entry of `days`, which must be in day order) this returns `F` only when
    all of these hold:

    1. the setting live on `D` is looser than the starting setting;
    2. `D` is inside an unfinished episode -- the days after the most recent interpretable
       non-low day, scanning back at most `SHADOW_SCAN_DAYS` (low-wear days do not end it);
    3. `F` is the first day of that episode on which the starting setting asks;
    4. `D - F >= SHADOW_GRACE_DAYS`;
    5. on no day in `[F, D)` did the setting live that day (floor included) ask.
    """
    if not days:
        return None
    today = days[-1].day
    if not threshold_on(today).looser_than(DEFAULT_REVIEW_THRESHOLD):
        return None
    episode = _open_episode(days)
    if not episode:
        return None
    first = next(
        (entry for entry in episode if review_fires(entry.signal, DEFAULT_REVIEW_THRESHOLD)),
        None,
    )
    if first is None or (today - first.day).days < SHADOW_GRACE_DAYS:
        return None
    for entry in episode:
        if first.day <= entry.day < today and review_fires(entry.signal, threshold_on(entry.day)):
            return None
    return first.day


# ── Replay ────────────────────────────────────────────────────────────────────────────────────

ReachedVia = Literal["threshold", "floor", "shadow_check"]


def _first_review(
    days: Sequence[DaySignal], episode: Sequence[DaySignal], threshold: ReviewThreshold
) -> tuple[date, ReachedVia] | None:
    """The first day in `episode` a person held at `threshold` would have been asked about.

    The shadow check is simulated from the same history the live check would read; the threshold
    is held constant, because the replay asks what this setting would have done, and the episode
    ends for the question at its first review.
    """
    positions = {entry.day: index for index, entry in enumerate(days)}
    for entry in episode:
        result = decide(
            entry.signal,
            consent_active=True,
            interventions_last_7_days=0,
            review_threshold=threshold,
        )
        if result.decision is Decision.COORDINATOR_REVIEW:
            via: ReachedVia = (
                "floor" if result.decided_by is PolicyGate.REVIEW_FLOOR else "threshold"
            )
            return entry.day, via
        prefix = days[: positions[entry.day] + 1]
        since = shadow_review_since(prefix, threshold_on=lambda _day: threshold)
        if since is not None:
            shadowed = decide(
                entry.signal,
                consent_active=True,
                interventions_last_7_days=0,
                review_threshold=threshold,
                shadow_review_since=since,
            )
            if shadowed.decision is Decision.COORDINATOR_REVIEW:
                return entry.day, "shadow_check"
    return None


def _episodes(days: Sequence[DaySignal]) -> list[tuple[list[DaySignal], bool]]:
    """Split a day series at recovery-close days; each episode starts at its first low day.

    Each episode comes with `ongoing`: true only for the trailing episode that no recovery-close
    day has ended by the last stored day.
    """
    episodes: list[tuple[list[DaySignal], bool]] = []
    current: list[DaySignal] = []
    for entry in days:
        if _closes_episode(entry.signal):
            if current:
                episodes.append((current, False))
            current = []
            continue
        if not current and not (
            entry.signal.quality.safe_to_interpret and entry.signal.sustained_low_days >= 1
        ):
            continue
        current.append(entry)
    if current:
        episodes.append((current, True))
    return episodes


def replay_thresholds(
    days: Sequence[DaySignal], *, current: ReviewThreshold, candidate: ReviewThreshold
) -> ReviewThresholdReplay:
    """What `current` and `candidate` would each have done over the last `REPLAY_WINDOW_DAYS`.

    `days` is a `day_signals` series in day order; only its last `REPLAY_WINDOW_DAYS` entries are
    read. One row per episode in which either setting (floor and simulated shadow check included)
    would have asked, the trailing unfinished episode included and marked `ongoing`.
    `days_later` is candidate minus current (negative: sooner). On a finished episode a `None`
    review day means that setting never asked before recovery; on an ongoing episode it means
    only "not yet". `reviews_with_current`, `reviews_with_candidate` and `max_days_later` read
    finished episodes only, so an unfinished episode can never be presented as a review saved.
    Raises `ValueError` for an empty series or an off-grid setting.
    """
    window = list(days)[-REPLAY_WINDOW_DAYS:]
    if not window:
        raise ValueError("replay needs at least one stored day")
    episodes: list[ReviewThresholdReplayEpisode] = []
    for episode, ongoing in _episodes(window):
        current_review = _first_review(window, episode, current)
        candidate_review = _first_review(window, episode, candidate)
        if current_review is None and candidate_review is None:
            continue
        days_later = (
            (candidate_review[0] - current_review[0]).days
            if current_review is not None and candidate_review is not None
            else None
        )
        episodes.append(
            ReviewThresholdReplayEpisode(
                first_low_day=episode[0].day,
                ongoing=ongoing,
                current_review_day=current_review[0] if current_review else None,
                candidate_review_day=candidate_review[0] if candidate_review else None,
                days_later=days_later,
                candidate_reached_via=candidate_review[1] if candidate_review else None,
            )
        )
    finished = [episode for episode in episodes if not episode.ongoing]
    later = [episode.days_later for episode in finished if episode.days_later is not None]
    return ReviewThresholdReplay(
        current=current.as_value(),
        candidate=candidate.as_value(),
        window_start_day=window[0].day,
        window_end_day=window[-1].day,
        episodes=episodes,
        reviews_with_current=sum(episode.current_review_day is not None for episode in finished),
        reviews_with_candidate=sum(
            episode.candidate_review_day is not None for episode in finished
        ),
        max_days_later=max(later) if later else None,
        disclosure=REPLAY_DISCLOSURE,
    )


# ── Normal variability ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VariabilitySummary:
    """Code-computed facts about how much this person's ordinary days swing.

    `share_at_least_pct_below[p]` is the share of interpretable days at least `p`% below the
    baseline (the comparison the review rung makes); `recovered_runs_at_least[n]` counts low runs
    that reached `n` sustained days and then recovered.
    """

    valid_days: int
    median_steps: float | None
    mad_over_median: float | None
    share_at_least_pct_below: dict[int, float]
    recovered_runs_at_least: dict[int, int]


def variability_summary(days: Sequence[DaySignal]) -> VariabilitySummary:
    valid = [entry for entry in days if entry.signal.quality.safe_to_interpret]
    steps = [entry.signal.current_steps for entry in valid]
    centre = float(median(steps)) if steps else None
    mad_ratio = (
        round(float(median(abs(value - centre) for value in steps)) / centre, 3) if centre else None
    )
    shares = {
        pct: (
            round(
                sum(abs(min(0.0, entry.signal.delta_percent)) >= pct for entry in valid)
                / len(valid),
                3,
            )
            if valid
            else 0.0
        )
        for pct in VARIABILITY_SEVERITY_PCTS
    }
    runs = dict.fromkeys(VARIABILITY_RUN_DAYS, 0)
    longest = 0
    for entry in days:
        signal = entry.signal
        if not signal.quality.safe_to_interpret:
            continue
        if signal.sustained_low_days == 0:
            for length in VARIABILITY_RUN_DAYS:
                if longest >= length:
                    runs[length] += 1
            longest = 0
        else:
            longest = max(longest, signal.sustained_low_days)
    return VariabilitySummary(
        valid_days=len(valid),
        median_steps=centre,
        mad_over_median=mad_ratio,
        share_at_least_pct_below=shares,
        recovered_runs_at_least=runs,
    )
