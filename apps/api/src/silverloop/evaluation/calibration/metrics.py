"""Pure metrics over the id-free run traces: workload, misses, delay, movement, reviewer pattern.

Nothing here reads a database or a clock. Every number is a count, a simulated sequence day or a
ratio of two counts, so two runs of the evaluation produce identical metrics.

Definitions (the report repeats them):

- **workload** -- review cases opened. A case the simulated coordinator resolves while the decline
  continues is followed by a new case the next day the ladder still asks, and that is counted: it
  is a real request for a human decision.
- **covered day** -- a day on which a review case opened, or on which any review case was still
  unresolved at the end of the day (after that day's review). An acknowledged case stays in front of
  the coordinator, and a later declining day refreshes it instead of opening another, so an episode
  it spans has reached a human even though no new case opened.
- **retained** -- a review-worthy episode with at least one covered day between its first and last
  authored day; **missed** -- one with none; **late** -- retained, but its first covered day is
  after `should_reach_by_day`.
- **delay** -- for a review-worthy episode retained in both, the first covered day in this arm minus
  the first covered day in the `starting_setting` arm for the same profile and sequence. Negative
  means sooner.
- **floor episode** -- an episode with at least three consecutive valid-wear authored days 60% or
  more below the reference (`CalibrationSequence.reaches_floor`). "Opened" still means a case
  opened during it, as does "benign asked about": both count asking, not coverage.
- **eligible to loosen** -- a review the fixed rule may count toward a looser setting: resolved,
  overridden as not a concern, not marked as reaching the coordinator too late.
- **loosening later reverted** -- of eligible reviews that triggered or were cited by an approved
  looser proposal, those whose approval a later `reverted` decision ended.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from silverloop.evaluation.calibration.sequences import CalibrationSequence
from silverloop.review_threshold import SHADOW_GRACE_DAYS

if TYPE_CHECKING:
    from silverloop.evaluation.calibration.runner import RunTrace

GATE_LABELS: dict[str, str] = {
    "severity_persistence": "review_setting",
    "review_floor": "floor",
    "shadow_check": "shadow_check",
}

CAP_REASON = "weekly_cap"


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _case_days(trace: RunTrace) -> list[int]:
    return [day.day for day in trace.days if day.case_opened]


def _covered_days(trace: RunTrace) -> list[int]:
    return [day.day for day in trace.days if day.case_opened or day.case_unresolved]


def first_case_day(trace: RunTrace, start_day: int, end_day: int) -> int | None:
    return next((day for day in _case_days(trace) if start_day <= day <= end_day), None)


def first_covered_day(trace: RunTrace, start_day: int, end_day: int) -> int | None:
    return next((day for day in _covered_days(trace) if start_day <= day <= end_day), None)


@dataclass(frozen=True)
class EpisodeOutcome:
    episode_id: str
    label: str
    review_worthy: bool
    reaches_floor: bool
    cases_opened: int
    first_case_day: int | None
    starting_first_case_day: int | None
    first_covered_day: int | None
    starting_first_covered_day: int | None
    delay_days: int | None
    late: bool

    def document(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "label": self.label,
            "review_worthy": self.review_worthy,
            "reaches_floor": self.reaches_floor,
            "cases_opened": self.cases_opened,
            "first_case_day": self.first_case_day,
            "starting_first_case_day": self.starting_first_case_day,
            "first_covered_day": self.first_covered_day,
            "starting_first_covered_day": self.starting_first_covered_day,
            "delay_days": self.delay_days,
            "late": self.late,
        }


def episode_outcomes(
    trace: RunTrace, starting: RunTrace, sequence: CalibrationSequence
) -> list[EpisodeOutcome]:
    days = _case_days(trace)
    outcomes: list[EpisodeOutcome] = []
    for episode in sequence.episodes:
        first = first_case_day(trace, episode.start_day, episode.end_day)
        reference = first_case_day(starting, episode.start_day, episode.end_day)
        covered = first_covered_day(trace, episode.start_day, episode.end_day)
        covered_reference = first_covered_day(starting, episode.start_day, episode.end_day)
        delay = (
            covered - covered_reference
            if covered is not None and covered_reference is not None
            else None
        )
        outcomes.append(
            EpisodeOutcome(
                episode_id=episode.episode_id,
                label=episode.label,
                review_worthy=episode.review_worthy,
                reaches_floor=sequence.reaches_floor(episode),
                cases_opened=sum(episode.start_day <= day <= episode.end_day for day in days),
                first_case_day=first,
                starting_first_case_day=reference,
                first_covered_day=covered,
                starting_first_covered_day=covered_reference,
                delay_days=delay if episode.review_worthy else None,
                late=(
                    episode.review_worthy
                    and covered is not None
                    and episode.should_reach_by_day is not None
                    and covered > episode.should_reach_by_day
                ),
            )
        )
    return outcomes


def workload(trace: RunTrace, sequence: CalibrationSequence) -> dict[str, Any]:
    by_gate: Counter[str] = Counter()
    on_review_worthy = on_benign = outside = 0
    for day in trace.days:
        if not day.case_opened:
            continue
        by_gate[GATE_LABELS.get(day.gate, day.gate)] += 1
        episode = sequence.episode_on(day.day)
        if episode is None:
            outside += 1
        elif episode.review_worthy:
            on_review_worthy += 1
        else:
            on_benign += 1
    return {
        "cases_opened": sum(by_gate.values()),
        "cases_by_route": {label: by_gate.get(label, 0) for label in GATE_LABELS.values()},
        "cases_on_review_worthy_episodes": on_review_worthy,
        "cases_on_benign_episodes": on_benign,
        "cases_outside_episodes": outside,
    }


def episode_summary(outcomes: list[EpisodeOutcome]) -> dict[str, Any]:
    worthy = [item for item in outcomes if item.review_worthy]
    benign = [item for item in outcomes if not item.review_worthy]
    floor = [item for item in outcomes if item.reaches_floor]
    delays = [item.delay_days for item in worthy if item.delay_days is not None]
    return {
        "review_worthy": len(worthy),
        "review_worthy_retained": sum(item.first_covered_day is not None for item in worthy),
        "review_worthy_missed": sum(item.first_covered_day is None for item in worthy),
        "review_worthy_late": sum(item.late for item in worthy),
        "max_delay_days": max(delays) if delays else None,
        "benign": len(benign),
        "benign_asked_about": sum(item.first_case_day is not None for item in benign),
        "floor_episodes": len(floor),
        "floor_episodes_opened": sum(item.first_case_day is not None for item in floor),
    }


def threshold_movement(trace: RunTrace) -> dict[str, Any]:
    approvals = [item for item in trace.decisions if item.kind == "approved"]
    revert_rows = [item for item in trace.decisions if item.kind == "reverted"]
    # A shadow-check put-back ends every approval on the stack with a row of its own; it is still
    # one put-back. Counted once per (day, trigger); the rows are reported beside it.
    reverts: Counter[str] = Counter(
        trigger
        for _, trigger in dict.fromkeys(
            (item.decided_on_day, item.revert_trigger or "unknown") for item in revert_rows
        )
    )
    changes: dict[tuple[int, str, str | None], dict[str, Any]] = {}
    for item in trace.decisions:
        if item.kind not in ("approved", "reverted", "expired"):
            continue
        key = (
            (item.decided_on_day, item.kind, item.revert_trigger)
            if item.kind != "approved"
            else (item.decided_on_day, f"approved-{item.ordinal}", None)
        )
        # The last row of a same-day put-back is the decisive one: it records the change lived.
        changes[key] = {
            "decided_on_day": item.decided_on_day,
            "effective_from_day": item.effective_from_day,
            "kind": item.kind,
            "trigger": item.revert_trigger,
            "before": list(item.before),
            "after": list(item.after) if item.after is not None else None,
        }
    looser = sum(
        1
        for item in approvals
        if item.after is not None
        and (item.after[0] > item.before[0] or item.after[1] > item.before[1])
    )
    severities = [day.live_severity_pct for day in trace.days]
    persistences = [day.live_persistence_days for day in trace.days]
    start = (severities[0], persistences[0]) if trace.days else None
    final = (severities[-1], persistences[-1]) if trace.days else None
    return {
        "approved_changes": len(approvals),
        "approved_looser": looser,
        "approved_sooner": len(approvals) - looser,
        "put_backs": sum(reverts.values()),
        "approvals_ended_by_put_backs": len(revert_rows),
        "put_backs_by_trigger": {
            trigger: reverts.get(trigger, 0)
            for trigger in ("shadow_check", "reached_too_late", "far_more_severe")
        },
        "expired": sum(item.kind == "expired" for item in trace.decisions),
        "severity_pct_min": min(severities) if severities else None,
        "severity_pct_max": max(severities) if severities else None,
        "persistence_days_min": min(persistences) if persistences else None,
        "persistence_days_max": max(persistences) if persistences else None,
        "first_day_setting": list(start) if start else None,
        "final_setting": list(final) if final else None,
        "days_looser_than_start": sum(
            1
            for day in trace.days
            if start is not None
            and (day.live_severity_pct > start[0] or day.live_persistence_days > start[1])
        ),
        "days_sooner_than_start": sum(
            1
            for day in trace.days
            if start is not None
            and (day.live_severity_pct < start[0] or day.live_persistence_days < start[1])
        ),
        "changes": list(changes.values()),
    }


def calibrator_activity(trace: RunTrace) -> dict[str, Any]:
    kinds: Counter[str] = Counter()
    for proposal in trace.proposals:
        if proposal.output_kind == "proposal":
            kinds[f"proposal_{proposal.direction}"] += 1
        else:
            kinds[proposal.output_kind] += 1
    calibrations = [item for item in trace.proposals if item.output_kind != "write_up"]
    return {
        "proposals_looser": kinds.get("proposal_looser", 0),
        "proposals_sooner": kinds.get("proposal_sooner", 0),
        "no_change": kinds.get("no_change", 0),
        "write_ups": kinds.get("write_up", 0),
        "outputs_by_agent": sum(item.proposer == "agent" for item in calibrations),
        "outputs_by_fixed_rule": sum(item.proposer == "fixed_rule" for item in calibrations),
        "agent_fallbacks": sum(
            item.agent_mode not in (None, "agent", "fallback_disabled") for item in calibrations
        ),
        "approvals_refused": sum(item.outcome == "refused" for item in trace.approval_attempts),
        "calibration_skips": dict(trace.calibration_skips),
        "calibration_discards": dict(trace.calibration_discards),
        "weekly_cap_skips": trace.calibration_skips.get(CAP_REASON, 0)
        + trace.calibration_discards.get(CAP_REASON, 0),
    }


def reviewer_pattern(trace: RunTrace) -> dict[str, Any]:
    reviews = trace.reviews
    eligible = {item.ordinal for item in reviews if item.counts_toward_loosening}
    approvals = {
        item.proposal_ordinal: item.ordinal
        for item in trace.decisions
        if item.kind == "approved" and item.proposal_ordinal is not None
    }
    reverted_approvals = {
        item.ends_approval_ordinal
        for item in trace.decisions
        if item.kind == "reverted" and item.ends_approval_ordinal is not None
    }
    led: set[int] = set()
    reverted: set[int] = set()
    for proposal in trace.proposals:
        if proposal.direction != "looser" or proposal.ordinal not in approvals:
            continue
        basis = eligible & {*proposal.trigger_review_ordinals, *proposal.cited_review_ordinals}
        led |= basis
        if approvals[proposal.ordinal] in reverted_approvals:
            reverted |= basis
    overrides = sum(item.human_action == "override" for item in reviews)
    return {
        "reviews": len(reviews),
        "overrides": overrides,
        "override_rate": _rate(overrides, len(reviews)),
        "marked_reached_too_late": sum(item.reached_too_late for item in reviews),
        "eligible_to_loosen": len(eligible),
        "eligible_to_loosen_share": _rate(len(eligible), len(reviews)),
        "eligible_led_to_approved_loosening": len(led),
        "eligible_loosening_later_reverted": len(reverted),
        "eligible_loosening_later_reverted_share": _rate(len(reverted), len(led)),
    }


def run_metrics(
    trace: RunTrace, starting: RunTrace, sequence: CalibrationSequence
) -> dict[str, Any]:
    outcomes = episode_outcomes(trace, starting, sequence)
    return {
        "sequence_id": sequence.sequence_id,
        "workload": workload(trace, sequence),
        "episodes": episode_summary(outcomes),
        "episode_outcomes": [item.document() for item in outcomes],
        "threshold": threshold_movement(trace),
        "calibrator": calibrator_activity(trace),
        "reviewer_pattern": reviewer_pattern(trace),
    }


_SUMMED_WORKLOAD = (
    "cases_opened",
    "cases_on_review_worthy_episodes",
    "cases_on_benign_episodes",
    "cases_outside_episodes",
)
_SUMMED_EPISODES = (
    "review_worthy",
    "review_worthy_retained",
    "review_worthy_missed",
    "review_worthy_late",
    "benign",
    "benign_asked_about",
    "floor_episodes",
    "floor_episodes_opened",
)
_SUMMED_THRESHOLD = (
    "approved_changes",
    "approved_looser",
    "approved_sooner",
    "put_backs",
    "approvals_ended_by_put_backs",
    "expired",
    "days_looser_than_start",
    "days_sooner_than_start",
)
_SUMMED_CALIBRATOR = (
    "proposals_looser",
    "proposals_sooner",
    "no_change",
    "write_ups",
    "outputs_by_agent",
    "outputs_by_fixed_rule",
    "agent_fallbacks",
    "approvals_refused",
    "weekly_cap_skips",
)
_SUMMED_PATTERN = (
    "reviews",
    "overrides",
    "marked_reached_too_late",
    "eligible_to_loosen",
    "eligible_led_to_approved_loosening",
    "eligible_loosening_later_reverted",
)


def _sum_counters(items: list[dict[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for item in items:
        total.update(item)
    return dict(sorted(total.items()))


def _max_or_none(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _min_or_none(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def totals(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum one (arm, profile)'s per-sequence metrics; maxima stay maxima."""
    workload_total: dict[str, Any] = {
        key: sum(run["workload"][key] for run in runs) for key in _SUMMED_WORKLOAD
    }
    workload_total["cases_by_route"] = _sum_counters(
        [run["workload"]["cases_by_route"] for run in runs]
    )
    episodes_total: dict[str, Any] = {
        key: sum(run["episodes"][key] for run in runs) for key in _SUMMED_EPISODES
    }
    episodes_total["max_delay_days"] = _max_or_none(
        [run["episodes"]["max_delay_days"] for run in runs]
    )
    threshold_total: dict[str, Any] = {
        key: sum(run["threshold"][key] for run in runs) for key in _SUMMED_THRESHOLD
    }
    threshold_total["put_backs_by_trigger"] = _sum_counters(
        [run["threshold"]["put_backs_by_trigger"] for run in runs]
    )
    for key, pick in (
        ("severity_pct_min", _min_or_none),
        ("persistence_days_min", _min_or_none),
        ("severity_pct_max", _max_or_none),
        ("persistence_days_max", _max_or_none),
    ):
        threshold_total[key] = pick([run["threshold"][key] for run in runs])
    calibrator_total: dict[str, Any] = {
        key: sum(run["calibrator"][key] for run in runs) for key in _SUMMED_CALIBRATOR
    }
    calibrator_total["calibration_skips"] = _sum_counters(
        [run["calibrator"]["calibration_skips"] for run in runs]
    )
    calibrator_total["calibration_discards"] = _sum_counters(
        [run["calibrator"]["calibration_discards"] for run in runs]
    )
    pattern_total: dict[str, Any] = {
        key: sum(run["reviewer_pattern"][key] for run in runs) for key in _SUMMED_PATTERN
    }
    pattern_total["override_rate"] = _rate(pattern_total["overrides"], pattern_total["reviews"])
    pattern_total["eligible_to_loosen_share"] = _rate(
        pattern_total["eligible_to_loosen"], pattern_total["reviews"]
    )
    pattern_total["eligible_loosening_later_reverted_share"] = _rate(
        pattern_total["eligible_loosening_later_reverted"],
        pattern_total["eligible_led_to_approved_loosening"],
    )
    return {
        "workload": workload_total,
        "episodes": episodes_total,
        "threshold": threshold_total,
        "calibrator": calibrator_total,
        "reviewer_pattern": pattern_total,
    }


def containment(runs: list[dict[str, Any]], starting_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether an (arm, profile) stayed inside the guarantees calibration promises.

    Per sequence, not only in total: a miss in one sequence may not be paid for by a catch in
    another.
    """
    by_sequence = {run["sequence_id"]: run for run in starting_runs}
    missed_ok = all(
        run["episodes"]["review_worthy_missed"]
        <= by_sequence[run["sequence_id"]]["episodes"]["review_worthy_missed"]
        for run in runs
    )
    delays = [run["episodes"]["max_delay_days"] for run in runs]
    max_delay = _max_or_none(delays)
    delay_ok = max_delay is None or max_delay <= SHADOW_GRACE_DAYS
    floor_ok = all(
        run["episodes"]["floor_episodes_opened"] == run["episodes"]["floor_episodes"]
        for run in runs
    )
    cap_skips = sum(run["calibrator"]["weekly_cap_skips"] for run in runs)
    return {
        "missed_no_more_than_starting_setting": missed_ok,
        "max_delay_days": max_delay,
        "max_delay_within_grace_days": delay_ok,
        "grace_days": SHADOW_GRACE_DAYS,
        "every_floor_episode_opened_a_case": floor_ok,
        "weekly_cap_skips": cap_skips,
        "holds": missed_ok and delay_ok and floor_ok and cap_skips == 0,
    }


__all__ = [
    "CAP_REASON",
    "EpisodeOutcome",
    "calibrator_activity",
    "containment",
    "episode_outcomes",
    "episode_summary",
    "first_case_day",
    "first_covered_day",
    "reviewer_pattern",
    "run_metrics",
    "threshold_movement",
    "totals",
    "workload",
]
