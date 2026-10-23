"""Properties of the review block across every allowed threshold.

The honest claim a looser review setting can make is not "no review is ever missed" -- a setting
that waits four days delays a review by design -- but these two:

1. the absolute floor always asks a human when consent, data quality, confidence and scale permit,
   whatever the setting; and
2. no allowed setting delays a review more than `SHADOW_GRACE_DAYS` past the day the starting
   setting would have asked, in an unfinished, consented, interpretable episode -- the shadow
   check asks instead, and the setting reverts to the default from the next day.

Checked over the core `scenarios/` replayed through the evaluation harness's environment (never the
database), and over generated sequences whose numbers are chosen to sit between the settings.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from silverloop.analytics import analyse_signal
from silverloop.evaluation.scenario_spec import discover_scenarios
from silverloop.evaluation.simulation import EnvironmentStep, replay
from silverloop.models import (
    ContextSignal,
    DailyMetric,
    Decision,
    PolicyGate,
    ReviewThresholdDecisionKind,
    ReviewThresholdRevertTrigger,
    SignalSummary,
)
from silverloop.policy import MINIMUM_INTERPRETABLE_BASELINE, decide
from silverloop.review_threshold import (
    ABSOLUTE_REVIEW_FLOOR,
    ALLOWED_THRESHOLDS,
    DEFAULT_REVIEW_THRESHOLD,
    SHADOW_GRACE_DAYS,
    RevertPlan,
    ReviewThreshold,
    ThresholdDecisionFact,
    asks_sooner,
    is_single_step,
    never_later,
    reached_too_late_revert,
    resolve_live_threshold,
)
from silverloop.review_threshold_replay import (
    DaySignal,
    day_signals,
    replay_thresholds,
    review_fires,
    shadow_review_since,
    variability_summary,
)

SCENARIO_DIRECTORY = Path(__file__).parents[3] / "scenarios"
PERSON = "mdm-test"
START = date(2026, 6, 1)
HISTORY_DAYS = 60
BASELINE_STEPS = 6000


def _scenario_steps() -> list[tuple[str, list[EnvironmentStep]]]:
    return [
        (scenario.name, list(replay(scenario)))
        for scenario in discover_scenarios(SCENARIO_DIRECTORY)
    ]


SCENARIOS = _scenario_steps()


def _permits_review(step_signal: SignalSummary, consent_active: bool) -> bool:
    return (
        consent_active
        and step_signal.quality.safe_to_interpret
        and step_signal.confidence >= 0.45
        and not (0 < step_signal.baseline_median_steps < MINIMUM_INTERPRETABLE_BASELINE)
    )


# ── The floor ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("threshold", ALLOWED_THRESHOLDS, ids=str)
def test_floor_always_reviews_when_the_earlier_gates_permit(threshold: ReviewThreshold) -> None:
    checked = 0
    for name, steps in SCENARIOS:
        for step in steps:
            severe = step.signal.model_copy(
                update={
                    "delta_percent": -62.0,
                    "sustained_low_days": max(3, step.signal.sustained_low_days),
                }
            )
            result = decide(
                severe,
                consent_active=step.consent_active,
                interventions_last_7_days=3,
                review_threshold=threshold,
            )
            context = (name, step.step, threshold)
            if not step.consent_active:
                assert (result.decision, result.decided_by) == (
                    Decision.SUPPRESS,
                    PolicyGate.CONSENT,
                ), context
            elif not severe.quality.safe_to_interpret:
                assert (result.decision, result.decided_by) == (
                    Decision.NO_ACTION,
                    PolicyGate.DATA_QUALITY,
                ), context
            elif _permits_review(severe, step.consent_active):
                expected_gate = (
                    PolicyGate.SEVERITY_PERSISTENCE
                    if threshold.fires(62.0, severe.sustained_low_days)
                    else PolicyGate.REVIEW_FLOOR
                )
                assert result.decision is Decision.COORDINATOR_REVIEW, context
                assert result.decided_by is expected_gate, context
                checked += 1
            else:
                assert result.decision is Decision.NO_ACTION, context
    assert checked > 0


# ── Generated sequences ───────────────────────────────────────────────────────────────────────


def _metrics(low_steps: list[int], *, tail: list[int] | None = None) -> list[DailyMetric]:
    """Sixty ordinary days at a constant 6,000 steps, then `low_steps`, then `tail`."""
    steps = [BASELINE_STEPS] * HISTORY_DAYS + low_steps + (tail or [])
    return [
        DailyMetric(
            day=START + timedelta(days=index),
            steps=value,
            active_minutes=40,
            sleep_hours=7.0,
            wear_hours=12.0,
        )
        for index, value in enumerate(steps)
    ]


def _series(metrics: list[DailyMetric], last_n: int = 40) -> list[DaySignal]:
    return day_signals(
        metrics,
        [ContextSignal() for _ in metrics],
        person_id=PERSON,
        last_n=last_n,
        confirmed_reference_on=lambda _day: None,
        conflict_on=lambda _day: (False, None),
    )


def _live_simulation(
    days: list[DaySignal], threshold: ReviewThreshold, *, consent: bool = True
) -> list[tuple[date, ReviewThreshold, Decision, PolicyGate | None]]:
    """Fold `decide` day by day the way `_evaluate` + `advance` do: the shadow check is read only
    for a looser live setting, and a `shadow_check` decision reverts to the default next day."""
    live = threshold
    live_on: dict[date, ReviewThreshold] = {}
    out: list[tuple[date, ReviewThreshold, Decision, PolicyGate | None]] = []
    for index, entry in enumerate(days):
        live_on[entry.day] = live
        since = (
            shadow_review_since(days[: index + 1], threshold_on=live_on.__getitem__)
            if live.looser_than(DEFAULT_REVIEW_THRESHOLD)
            else None
        )
        result = decide(
            entry.signal,
            consent_active=consent,
            interventions_last_7_days=0,
            review_threshold=live,
            shadow_review_since=since,
        )
        out.append((entry.day, live, result.decision, result.decided_by))
        if result.decided_by is PolicyGate.SHADOW_CHECK:
            live = DEFAULT_REVIEW_THRESHOLD
    return out


def test_day_signals_recompute_each_day_as_evaluate_does() -> None:
    metrics = _metrics([3480] * 4)
    series = _series(metrics, last_n=5)
    assert [entry.day for entry in series] == [metric.day for metric in metrics[-5:]]
    for offset, entry in enumerate(series):
        index = len(metrics) - 5 + offset
        _, expected = analyse_signal(
            metrics[:index],
            metrics[index],
            ContextSignal(),
            person_id=PERSON,
            assessed_at=datetime.combine(entry.day, time(hour=12), tzinfo=UTC),
        )
        assert entry.signal == expected
    disputed_day = metrics[-1].day
    disputed = day_signals(
        metrics,
        [ContextSignal() for _ in metrics],
        person_id=PERSON,
        last_n=2,
        confirmed_reference_on=lambda _day: None,
        conflict_on=lambda day: (day == disputed_day, "Walked all day."),
    )
    assert disputed[0].signal.quality == series[-2].signal.quality
    assert disputed[1].signal.quality != series[-1].signal.quality
    assert disputed[1].signal.quality.safe_to_interpret  # a conflict never flips this
    with pytest.raises(ValueError):
        day_signals(
            metrics,
            [],
            person_id=PERSON,
            last_n=1,
            confirmed_reference_on=lambda _day: None,
            conflict_on=lambda _day: (False, None),
        )


def test_constant_42_percent_under_45_3_is_asked_on_f_plus_3_by_the_shadow_check() -> None:
    days = _series(_metrics([3480] * 10))
    assert days[-1].signal.delta_percent == -42.0
    first_default = next(e.day for e in days if review_fires(e.signal, DEFAULT_REVIEW_THRESHOLD))
    lenient = ReviewThreshold(45, 3)
    simulated = _live_simulation(days, lenient)
    reviews = [
        (day, gate)
        for day, _, decision, gate in simulated
        if decision is Decision.COORDINATOR_REVIEW
    ]
    shadow_day = first_default + timedelta(days=SHADOW_GRACE_DAYS)
    assert reviews[0] == (shadow_day, PolicyGate.SHADOW_CHECK)
    # Nothing asked before it, and the next day the live setting is the default.
    assert all(day >= shadow_day for day, _ in reviews)
    next_day = {day: live for day, live, _, _ in simulated}[shadow_day + timedelta(days=1)]
    assert next_day == DEFAULT_REVIEW_THRESHOLD
    # The same revert, as the repository stores it, resolves to the default from the next day.
    approved = ThresholdDecisionFact(
        decision_id="A",
        kind=ReviewThresholdDecisionKind.APPROVED,
        previous=DEFAULT_REVIEW_THRESHOLD,
        after=lenient,
        decided_on_day=first_default - timedelta(days=10),
        effective_from_day=first_default - timedelta(days=9),
        decided_at=datetime.combine(first_default - timedelta(days=10), time(), tzinfo=UTC),
    )
    revert = ThresholdDecisionFact(
        decision_id="S",
        kind=ReviewThresholdDecisionKind.REVERTED,
        previous=lenient,
        after=DEFAULT_REVIEW_THRESHOLD,
        decided_on_day=shadow_day,
        effective_from_day=shadow_day + timedelta(days=1),
        decided_at=datetime.combine(shadow_day, datetime.min.time(), tzinfo=UTC),
        revert_trigger=ReviewThresholdRevertTrigger.SHADOW_CHECK,
        ends_approval_id="A",
    )
    assert resolve_live_threshold([approved, revert], shadow_day).threshold == lenient
    assert (
        resolve_live_threshold([approved, revert], shadow_day + timedelta(days=1)).threshold
        == DEFAULT_REVIEW_THRESHOLD
    )


def test_the_shadow_check_waits_the_whole_grace_period() -> None:
    days = _series(_metrics([3480] * 10))
    lenient = ReviewThreshold(45, 3)
    first_default = next(e.day for e in days if review_fires(e.signal, DEFAULT_REVIEW_THRESHOLD))
    for index, entry in enumerate(days):
        since = shadow_review_since(days[: index + 1], threshold_on=lambda _day: lenient)
        if (entry.day - first_default).days >= SHADOW_GRACE_DAYS:
            assert since == first_default
        else:
            assert since is None
    # Never for the default or a stricter setting.
    for threshold in (DEFAULT_REVIEW_THRESHOLD, ReviewThreshold(35, 3)):
        assert shadow_review_since(days, threshold_on=lambda _day, t=threshold: t) is None


def test_a_recovery_day_ends_the_episode_and_a_low_wear_day_does_not() -> None:
    lenient = ReviewThreshold(45, 3)
    recovered = _series(_metrics([3480] * 4, tail=[6000]))
    assert shadow_review_since(recovered, threshold_on=lambda _day: lenient) is None
    metrics = _metrics([3480] * 3)
    gap = metrics[-1].day + timedelta(days=1)
    metrics.append(
        DailyMetric(day=gap, steps=900, active_minutes=5, sleep_hours=None, wear_hours=2.0)
    )
    metrics.extend(
        DailyMetric(
            day=gap + timedelta(days=offset),
            steps=3480,
            active_minutes=20,
            sleep_hours=7.0,
            wear_hours=12.0,
        )
        for offset in (1, 2)
    )
    days = _series(metrics)
    assert not days[-3].signal.quality.safe_to_interpret
    first_default = next(e.day for e in days if review_fires(e.signal, DEFAULT_REVIEW_THRESHOLD))
    assert shadow_review_since(days, threshold_on=lambda _day: lenient) == first_default


def test_62_percent_for_three_days_reviews_under_every_setting() -> None:
    days = _series(_metrics([2280] * 3))
    today = days[-1]
    assert today.signal.delta_percent == -62.0 and today.signal.sustained_low_days == 3
    for threshold in ALLOWED_THRESHOLDS:
        result = decide(
            today.signal,
            consent_active=True,
            interventions_last_7_days=0,
            review_threshold=threshold,
        )
        assert result.decision is Decision.COORDINATOR_REVIEW
        assert result.decided_by is (
            PolicyGate.SEVERITY_PERSISTENCE
            if threshold.persistence_days == 3
            else PolicyGate.REVIEW_FLOOR
        )
        withdrawn = decide(
            today.signal,
            consent_active=False,
            interventions_last_7_days=0,
            review_threshold=threshold,
            shadow_review_since=today.day,
        )
        assert (withdrawn.decision, withdrawn.decided_by) == (Decision.SUPPRESS, PolicyGate.CONSENT)
    failed = today.signal.model_copy(
        update={"quality": today.signal.quality.model_copy(update={"safe_to_interpret": False})}
    )
    for threshold in ALLOWED_THRESHOLDS:
        result = decide(
            failed,
            consent_active=True,
            interventions_last_7_days=0,
            review_threshold=threshold,
            shadow_review_since=today.day,
        )
        assert (result.decision, result.decided_by) == (
            Decision.NO_ACTION,
            PolicyGate.DATA_QUALITY,
        )
    assert ABSOLUTE_REVIEW_FLOOR.fires(62.0, 3)


@pytest.mark.parametrize("low_steps", [3480, 3300, 3000, 2700, 2460])
@pytest.mark.parametrize("threshold", ALLOWED_THRESHOLDS, ids=str)
def test_generated_declines_are_asked_about_by_f_plus_3_under_every_setting(
    threshold: ReviewThreshold, low_steps: int
) -> None:
    """The core scenarios never hold a decline long enough to need the shadow check, so the bound
    is also checked on constant declines from 42% to 59% -- between the default and the floor."""
    days = _series(_metrics([low_steps] * 10))
    first_default = next(e.day for e in days if review_fires(e.signal, DEFAULT_REVIEW_THRESHOLD))
    reviews = [
        (day, gate)
        for day, _, decision, gate in _live_simulation(days, threshold)
        if decision is Decision.COORDINATOR_REVIEW
    ]
    assert reviews, threshold
    first_day, first_gate = reviews[0]
    assert first_day <= first_default + timedelta(days=SHADOW_GRACE_DAYS)
    if first_gate is PolicyGate.SHADOW_CHECK:
        assert first_day == first_default + timedelta(days=SHADOW_GRACE_DAYS)
        assert threshold.looser_than(DEFAULT_REVIEW_THRESHOLD)
    if not threshold.looser_than(DEFAULT_REVIEW_THRESHOLD):
        assert first_day <= first_default


# ── Bounded delay over the scenarios ──────────────────────────────────────────────────────────


def _closes(signal: SignalSummary) -> bool:
    return signal.quality.safe_to_interpret and signal.sustained_low_days == 0


def _episodes_compared(
    name: str,
    days: list[DaySignal],
    consent: dict[date, bool],
    threshold: ReviewThreshold,
) -> int:
    """How many default-first-asks episodes in `days` were checked against the F + 3 bound."""
    signals = {entry.day: entry.signal for entry in days}
    live = threshold
    live_on: dict[date, ReviewThreshold] = {}
    reviewed: set[date] = set()
    for index, entry in enumerate(days):
        live_on[entry.day] = live
        since = (
            shadow_review_since(days[: index + 1], threshold_on=live_on.__getitem__)
            if live.looser_than(DEFAULT_REVIEW_THRESHOLD)
            else None
        )
        result = decide(
            entry.signal,
            consent_active=consent[entry.day],
            interventions_last_7_days=0,
            review_threshold=live,
            shadow_review_since=since,
        )
        if result.decision is Decision.COORDINATOR_REVIEW:
            reviewed.add(entry.day)
        if result.decided_by is PolicyGate.SHADOW_CHECK:
            live = DEFAULT_REVIEW_THRESHOLD

    compared = 0
    episode_start: date | None = None
    asked_in_episode = False
    for entry in days:
        if _closes(entry.signal):
            episode_start, asked_in_episode = None, False
            continue
        if episode_start is None:
            episode_start = entry.day
        default_asks = consent[entry.day] and review_fires(entry.signal, DEFAULT_REVIEW_THRESHOLD)
        if not default_asks or asked_in_episode:
            continue
        asked_in_episode = True
        first = entry.day
        deadline = first + timedelta(days=SHADOW_GRACE_DAYS)
        window = [first + timedelta(days=offset) for offset in range(SHADOW_GRACE_DAYS + 1)]
        if any(
            day not in signals
            or _closes(signals[day])
            or not consent[day]
            or not signals[day].quality.safe_to_interpret
            or signals[day].confidence < 0.45
            for day in window
        ):
            continue
        assert any(episode_start <= day <= deadline for day in reviewed), (
            name,
            threshold,
            first,
            sorted(reviewed),
        )
        compared += 1
    return compared


# Generated declines held long enough for the bound to bind: between the default and every looser
# severity, and past the floor. The core scenarios rarely hold a decline past F + 3.
GENERATED_DECLINES: tuple[tuple[str, list[int]], ...] = (
    ("constant 42% for 10 days", [3480] * 10),
    ("constant 52% for 10 days", [2880] * 10),
    ("constant 62% for 10 days", [2280] * 10),
)


@pytest.mark.parametrize("threshold", ALLOWED_THRESHOLDS, ids=str)
def test_no_setting_delays_a_review_more_than_the_grace_period(threshold: ReviewThreshold) -> None:
    """For every episode in which the default asks on day F, the setting asks by F + 3 -- unless
    the episode recovered first, the series ended, or a day up to F + 3 could not be decided
    (consent withdrawn or an uninterpretable reading), which blocks every rung alike.

    Checked over the core scenarios and over generated declines; the generated ones guarantee the
    bound is actually exercised (`compared > 0`) for every setting, the looser ones included.
    """
    from_scenarios = 0
    for name, steps in SCENARIOS:
        days = [DaySignal(day=step.metric.day, signal=step.signal) for step in steps]
        consent = {step.metric.day: step.consent_active for step in steps}
        from_scenarios += _episodes_compared(name, days, consent, threshold)
    if threshold == DEFAULT_REVIEW_THRESHOLD:
        assert from_scenarios > 0

    generated = 0
    for name, low_steps in GENERATED_DECLINES:
        days = _series(_metrics(low_steps, tail=[BASELINE_STEPS] * 3))
        generated += _episodes_compared(
            name, days, dict.fromkeys((e.day for e in days), True), threshold
        )
    assert generated == len(GENERATED_DECLINES), threshold


# ── Replay and variability ────────────────────────────────────────────────────────────────────


def test_replay_reports_days_later_and_how_the_candidate_asked() -> None:
    days = _series(_metrics([3480] * 10, tail=[6000] * 3), last_n=56)
    first_default = next(e.day for e in days if review_fires(e.signal, DEFAULT_REVIEW_THRESHOLD))

    shadow = replay_thresholds(
        days, current=DEFAULT_REVIEW_THRESHOLD, candidate=ReviewThreshold(45, 3)
    )
    assert len(shadow.episodes) == 1
    episode = shadow.episodes[0]
    assert episode.current_review_day == first_default
    assert episode.candidate_review_day == first_default + timedelta(days=SHADOW_GRACE_DAYS)
    assert episode.days_later == SHADOW_GRACE_DAYS
    assert episode.candidate_reached_via == "shadow_check"
    assert (shadow.reviews_with_current, shadow.reviews_with_candidate) == (1, 1)
    assert shadow.max_days_later == SHADOW_GRACE_DAYS
    assert shadow.disclosure == (
        "Calculated by code from stored synthetic history; not written by a model."
    )
    assert shadow.window_end_day == days[-1].day

    one_day = replay_thresholds(
        days, current=DEFAULT_REVIEW_THRESHOLD, candidate=ReviewThreshold(40, 4)
    )
    assert one_day.episodes[0].days_later == 1
    assert one_day.episodes[0].candidate_reached_via == "threshold"

    sooner = replay_thresholds(
        days, current=ReviewThreshold(40, 4), candidate=DEFAULT_REVIEW_THRESHOLD
    )
    assert sooner.episodes[0].days_later == -1


def test_replay_candidate_is_none_when_the_episode_recovers_inside_the_grace_period() -> None:
    days = _series(_metrics([3480] * 4, tail=[6000] * 2), last_n=56)
    result = replay_thresholds(
        days, current=DEFAULT_REVIEW_THRESHOLD, candidate=ReviewThreshold(45, 3)
    )
    assert len(result.episodes) == 1
    assert result.episodes[0].current_review_day is not None
    assert result.episodes[0].candidate_review_day is None
    assert result.episodes[0].days_later is None
    assert (result.reviews_with_current, result.reviews_with_candidate) == (1, 0)
    assert result.max_days_later is None


def test_replay_floor_is_named() -> None:
    days = _series(_metrics([2280] * 5, tail=[6000]), last_n=56)
    result = replay_thresholds(
        days, current=DEFAULT_REVIEW_THRESHOLD, candidate=ReviewThreshold(40, 5)
    )
    assert result.episodes[0].candidate_reached_via == "floor"
    assert result.episodes[0].days_later == 0


@pytest.mark.parametrize("threshold", ALLOWED_THRESHOLDS, ids=str)
def test_replay_over_the_scenarios_never_reports_more_than_the_grace_period(
    threshold: ReviewThreshold,
) -> None:
    for name, steps in SCENARIOS:
        days = [DaySignal(day=step.metric.day, signal=step.signal) for step in steps]
        result = replay_thresholds(days, current=DEFAULT_REVIEW_THRESHOLD, candidate=threshold)
        if result.max_days_later is not None:
            assert result.max_days_later <= SHADOW_GRACE_DAYS, (name, threshold)
        if not threshold.looser_than(DEFAULT_REVIEW_THRESHOLD):
            assert result.reviews_with_candidate >= result.reviews_with_current, (name, threshold)


def test_variability_summary() -> None:
    days = _series(_metrics([3480] * 4, tail=[6000] * 6), last_n=20)
    summary = variability_summary(days)
    assert summary.valid_days == 20
    assert summary.median_steps == 6000.0
    assert summary.mad_over_median == 0.0
    assert summary.share_at_least_pct_below[40] == 0.2
    assert summary.share_at_least_pct_below[45] == 0.0
    assert summary.recovered_runs_at_least == {3: 1, 4: 1, 5: 0}
    empty = variability_summary([])
    assert empty.valid_days == 0 and empty.median_steps is None


# ── Reverts and expiry never ask later (random approval stacks) ───────────────────────────────


def _one_step_moves(live: ReviewThreshold) -> list[ReviewThreshold]:
    return [
        candidate
        for candidate in ALLOWED_THRESHOLDS
        if is_single_step(live, candidate) and candidate.is_allowed
    ]


def _approval(
    decision_id: str, previous: ReviewThreshold, after: ReviewThreshold, day: date, at: datetime
) -> ThresholdDecisionFact:
    return ThresholdDecisionFact(
        decision_id=decision_id,
        kind=ReviewThresholdDecisionKind.APPROVED,
        previous=previous,
        after=after,
        decided_on_day=day,
        effective_from_day=day + timedelta(days=1),
        decided_at=at,
    )


def _ending_rows(
    outcome: RevertPlan, day: date, at: datetime, counter: int
) -> list[ThresholdDecisionFact]:
    """The rows the repository writes for a plan: one per removed approval, top-down."""
    return [
        ThresholdDecisionFact(
            decision_id=f"v{counter}_{index}",
            kind=ReviewThresholdDecisionKind.REVERTED,
            previous=outcome.previous if index == len(outcome.ends) - 1 else held,
            after=outcome.restored,
            decided_on_day=day,
            effective_from_day=day + timedelta(days=1),
            decided_at=at + timedelta(microseconds=index),
            revert_trigger=ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
            ends_approval_id=approval_id,
        )
        for index, (approval_id, held) in enumerate(outcome.ends)
    ]


@pytest.mark.parametrize("seed", range(300))
def test_after_any_revert_or_expiry_the_live_setting_never_asks_later(seed: int) -> None:
    """Random stacks built from allowed one-step approvals -- loosening, stepping back and manual
    tightening alike, several on one day so some are still pending for tomorrow -- with
    reconfirmations and reached-too-late marks (sometimes twice the same day) at random days.

    - After a mark, tomorrow never asks later than tomorrow would have without it, and, when a
      revert is written, never later than today's live value either.
    - On every day on which no approval takes effect, the live setting asks no later than the day
      before in either dimension -- whatever lapsed or was reverted.
    """
    rng = random.Random(seed)
    start = date(2026, 1, 1)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    facts: list[ThresholdDecisionFact] = []
    day = start
    counter = 0
    horizon = start + timedelta(days=260)
    while day < start + timedelta(days=150):
        day += timedelta(days=rng.randint(0, 20))
        counter += 1
        decided_at = at + timedelta(days=(day - start).days, seconds=counter)
        live = resolve_live_threshold(facts, day)
        tomorrow = resolve_live_threshold(facts, day + timedelta(days=1))
        roll = rng.random()
        if roll < 0.55:
            # Built on tomorrow's value, so a second approval the same day stacks on a pending one.
            after = rng.choice(_one_step_moves(tomorrow.threshold))
            facts.append(_approval(f"a{counter}", tomorrow.threshold, after, day, decided_at))
        elif roll < 0.65 and live.approval_id is not None and live.loosened:
            facts.append(
                ThresholdDecisionFact(
                    decision_id=f"r{counter}",
                    kind=ReviewThresholdDecisionKind.RECONFIRMED,
                    previous=live.threshold,
                    after=live.threshold,
                    decided_on_day=day,
                    effective_from_day=day + timedelta(days=1),
                    decided_at=decided_at,
                    affects_decision_id=live.approval_id,
                )
            )
        else:
            for mark in range(2 if rng.random() < 0.3 else 1):
                before = resolve_live_threshold(facts, day + timedelta(days=1)).threshold
                outcome = reached_too_late_revert(
                    facts, today=day, decided_at=decided_at + timedelta(milliseconds=mark)
                )
                if isinstance(outcome, RevertPlan):
                    assert asks_sooner(outcome.restored, live.threshold), (seed, outcome, live)
                    facts.extend(
                        _ending_rows(
                            outcome, day, decided_at + timedelta(milliseconds=mark), counter
                        )
                    )
                after_mark = resolve_live_threshold(facts, day + timedelta(days=1)).threshold
                assert never_later(after_mark, before), (seed, day, before, after_mark)
                if isinstance(outcome, RevertPlan):
                    assert after_mark == outcome.restored, (seed, day, outcome, after_mark)
                    assert never_later(after_mark, live.threshold), (seed, day, after_mark)
                if mark == 1:
                    assert not isinstance(outcome, RevertPlan), (seed, day, "second revert")
    approval_days = {
        fact.effective_from_day
        for fact in facts
        if fact.kind is ReviewThresholdDecisionKind.APPROVED
    }
    previous = resolve_live_threshold(facts, start)
    cursor = start + timedelta(days=1)
    while cursor <= horizon:
        current = resolve_live_threshold(facts, cursor)
        if cursor not in approval_days:
            assert never_later(current.threshold, previous.threshold), (
                seed,
                cursor,
                previous.threshold,
                current.threshold,
            )
        assert current.threshold.is_allowed
        previous = current
        cursor += timedelta(days=1)


@pytest.mark.parametrize("seed", range(30))
def test_the_repository_paths_never_leave_tomorrow_asking_later(seed: int) -> None:
    """The same property through the real writers: approvals stored for today and tomorrow,
    `review_case(reached_too_late=True)` (sometimes twice a day), and `advance()`'s daily checks."""
    from silverloop.db_models import ReviewThresholdDecisionRow, ScenarioRunRow
    from silverloop.models import CaseStatus, HumanAction
    from silverloop.sql_repository import SqlAlchemyRepository, _utcnow

    rng = random.Random(seed)
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"prop-{seed}-setup-{index}")
        case_id = repository.list_cases()[0].case_id

        def fold(offset: int) -> ReviewThreshold:
            with repository.sessions() as session:
                run = session.scalar(select(ScenarioRunRow).where(ScenarioRunRow.active.is_(True)))
                assert run is not None
                return resolve_live_threshold(
                    repository._threshold_facts(session, run.run_id),
                    run.current_day + timedelta(days=offset),
                ).threshold

        for step in range(6):
            roll = rng.random()
            if roll < 0.45:
                with repository.sessions.begin() as session:
                    run = session.scalar(
                        select(ScenarioRunRow).where(ScenarioRunRow.active.is_(True))
                    )
                    assert run is not None
                    facts = repository._threshold_facts(session, run.run_id)
                    tomorrow = resolve_live_threshold(facts, run.current_day + timedelta(days=1))
                    after = rng.choice(_one_step_moves(tomorrow.threshold))
                    session.add(
                        ReviewThresholdDecisionRow(
                            decision_id=f"prop_{seed}_{step}",
                            run_id=run.run_id,
                            person_id=run.person_id,
                            kind="approved",
                            previous_severity_pct=tomorrow.threshold.severity_pct,
                            previous_persistence_days=tomorrow.threshold.persistence_days,
                            severity_pct=after.severity_pct,
                            persistence_days=after.persistence_days,
                            decided_by="coordinator",
                            decided_on_day=run.current_day,
                            effective_from_day=run.current_day + timedelta(days=1),
                            decided_at=_utcnow(),
                        )
                    )
            elif roll < 0.75:
                yesterday = fold(0)
                with repository.sessions() as session:
                    run = session.scalar(
                        select(ScenarioRunRow).where(ScenarioRunRow.active.is_(True))
                    )
                    assert run is not None
                    approvals_tomorrow = any(
                        fact.kind is ReviewThresholdDecisionKind.APPROVED
                        and fact.effective_from_day == run.current_day + timedelta(days=1)
                        for fact in repository._threshold_facts(session, run.run_id)
                    )
                repository.advance("activity_declines", event_id=f"prop-{seed}-{step}")
                if not approvals_tomorrow:
                    assert never_later(fold(0), yesterday), (seed, step, yesterday, fold(0))
            else:
                for _ in range(2 if rng.random() < 0.3 else 1):
                    today = fold(0)
                    before = fold(1)
                    repository.review_case(
                        case_id,
                        CaseStatus.ACKNOWLEDGED,
                        "Should have reached me sooner.",
                        "coordinator",
                        human_action=HumanAction.AGREE,
                        reached_too_late=True,
                    )
                    after_mark = fold(1)
                    assert never_later(after_mark, before), (seed, step, before, after_mark)
                    assert never_later(after_mark, today), (seed, step, today, after_mark)
    finally:
        repository.close()
