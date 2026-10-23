"""The bounded LLM re-rank's two pure edges: what the planner is shown, and how its answer merges.

`SqlAlchemyRepository.search_activities` and the evaluator-only ranker inspector
(`silverloop.ranker_inspector`) both call these, so an inspected planner run sees exactly the
context a real search would have built, and its order is merged by exactly the same rule. Neither
function talks to a model, a database or the network; the call in between is
`agent.planner.plan_activity_ranking`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from silverloop.agent import ActivityOption, ActivityPlanRun, ActivityRankingContext
from silverloop.agent.constants import MAX_ACTIVITY_OPTIONS_RETURNED
from silverloop.local_time import local_hour
from silverloop.models import FilterOutcome, RankedActivity

PLANNER_NARROWED_RULE = "planner_narrowed"


def time_window_of(start_at: datetime | None) -> str:
    """Coarse bucket for one session time, matching `TimeWindow`'s vocabulary.

    Kept here rather than imported so the planner's view of an option is assembled in one place;
    `activity_search` owns the same buckets for filtering, and the two must agree.
    """
    if start_at is None:
        return "any"
    hour = local_hour(start_at)
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def build_ranking_context(
    ranked: Sequence[RankedActivity], understood: list[str]
) -> ActivityRankingContext:
    """The planner's read-only view of an already-filtered, already-ranked search."""
    return ActivityRankingContext(
        understood_lines=understood,
        options=[
            ActivityOption(
                key=item.candidate.activity_id,
                title=item.candidate.title,
                category=item.candidate.category,
                distance_m=item.candidate.distance_m,
                environment=item.candidate.indoor_outdoor.value,
                intensity=(
                    item.candidate.intensity.value if item.candidate.intensity is not None else None
                ),
                time_window=time_window_of(item.candidate.start_at),
                deterministic_rank=item.rank,
                reasons=[reason.text for reason in item.reasons],
            )
            for item in ranked
        ],
    )


def merge_planner_order(
    ranked: list[RankedActivity], plan_run: ActivityPlanRun
) -> tuple[list[RankedActivity], list[FilterOutcome]]:
    """Apply a planner run's `selected_order` to the deterministic order.

    Returns the merged order and a `planner_narrowed` `FilterOutcome` for every option the planner
    was shown but left out. When the run selected nothing that exists in `ranked`, the order is
    returned unchanged and nothing is recorded as narrowed.
    """
    deterministic_order = [item.candidate.activity_id for item in ranked]
    by_id = {item.candidate.activity_id: item for item in ranked}
    reordered = [by_id[key] for key in plan_run.selected_order if key in by_id]
    if not reordered:
        return ranked, []
    # The model is shown at most `MAX_ACTIVITY_OPTIONS_RETURNED` options and may only reorder or
    # narrow those. Anything below that cap was never its to judge: it keeps the deterministic
    # order behind the planner's choice rather than being reported as something the planner
    # dropped.
    shown_ids = set(deterministic_order[:MAX_ACTIVITY_OPTIONS_RETURNED])
    kept_ids = {item.candidate.activity_id for item in reordered}
    # The guardrail lets the planner narrow the shown set. Anything it drops has to be recorded
    # here, because `filtered_out` is the only account of what was excluded -- and an option the
    # model chose to hide is exactly the kind this record exists to expose. Left out, "the agent
    # chose well" would be unfalsifiable in precisely the case where it matters.
    narrowed = [
        FilterOutcome(
            activity_id=item.candidate.activity_id,
            title=item.candidate.title,
            rule=PLANNER_NARROWED_RULE,
            detail=(
                "Permitted by the rules, but the planner did not include it in what it offered."
            ),
        )
        for item in ranked
        if item.candidate.activity_id in shown_ids and item.candidate.activity_id not in kept_ids
    ]
    reordered = reordered + [
        item
        for item in ranked
        if item.candidate.activity_id not in shown_ids
        and item.candidate.activity_id not in kept_ids
    ]
    # Only what the model was shown and chose is the agent's; the unseen tail kept the ranker's
    # order behind it and is labelled so (D3).
    merged = [
        item.model_copy(
            update={
                "rank": position,
                "selected_by": (
                    "agent"
                    if plan_run.used_agent and item.candidate.activity_id in kept_ids
                    else "ranker"
                ),
            }
        )
        for position, item in enumerate(reordered, start=1)
    ]
    return merged, narrowed
