"""Builds the "Since you last visited" catch-up from what the member can already read.

Every read goes through the stores' own permission-checked methods (`activity`,
`group_calendar`, `group_tasks`), so the catch-up can never show a member anything the feed, the
calendar or the task list would not. The agent itself (`silverloop.agent.catchup`) only sees the
`CatchUpContext` assembled here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from silverloop.agent.catchup import (
    CatchUpContext,
    FeedItem,
    OpenVisit,
    TaskToday,
    write_catch_up,
)
from silverloop.agent.loop import llm_source
from silverloop.config import Settings
from silverloop.family_activity import aware
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_tasks import FamilyTaskStore, occurs_on
from silverloop.models import AgentStep, CatchUp

# How far ahead "needs someone" looks, the same window as Home's list.
OPEN_VISIT_DAYS = 14
# The most recent feed entries read; a catch-up is a glance, not the whole history.
FEED_LIMIT = 50


def build_context(
    calendar: FamilyCalendarStore,
    tasks: FamilyTaskStore,
    sub: str,
    group_id: str,
    since: datetime | None,
    today: date,
) -> CatchUpContext:
    page = calendar.activity(sub, group_id, FEED_LIMIT, None)
    cutoff = aware(since) if since is not None else None
    feed = [
        FeedItem(
            at=aware(entry.at),
            actor_name=entry.actor_name,
            is_me=entry.is_me,
            kind=entry.kind.value,
            appointment_title=entry.appointment_title,
            on_date=entry.on_date,
            check_in_kind=entry.check_in_kind.value if entry.check_in_kind else None,
        )
        for entry in page.entries
        if cutoff is None or aware(entry.at) > cutoff
    ]

    upcoming = calendar.group_calendar(
        sub, group_id, today, today + timedelta(days=OPEN_VISIT_DAYS - 1)
    )
    helped = {assignment.occurrence_id for assignment in upcoming.assignments}
    open_visits = sorted(
        (
            OpenVisit(
                title=occurrence.title,
                day=occurrence.date,
                start=occurrence.start,
                kind=occurrence.kind.value,
            )
            for occurrence in upcoming.appointments
            if occurrence.occurrence_id not in helped and occurrence.date >= today
        ),
        key=lambda visit: (visit.day, visit.start),
    )

    task_list = tasks.group_tasks(sub, group_id, today, today)
    ticked = {tick.task_id for tick in task_list.ticks if tick.day == today}
    tasks_today = sorted(
        (
            TaskToday(title=task.title, time=task.time, done=task.task_id in ticked)
            for task in task_list.tasks
            if occurs_on(task, today)  # type: ignore[arg-type] - same fields as the row
        ),
        key=lambda task: task.time,
    )

    return CatchUpContext(
        senior_name=upcoming.senior_name,
        today=today,
        since=cutoff,
        feed=feed,
        open_visits=open_visits,
        tasks_today=tasks_today,
    )


def catch_up(context: CatchUpContext, settings: Settings) -> CatchUp:
    result = write_catch_up(context, settings=settings)
    return CatchUp(
        mode=result.mode,
        source=llm_source(settings) if result.mode == "agent" else None,
        summary=result.summary,
        highlights=result.highlights,
        since=context.since,
        generated_at=datetime.now(UTC),
        model=result.model if result.mode == "agent" else None,
        new_updates=sum(1 for item in context.feed if not item.is_me),
        visits_needing_someone=len(context.open_visits),
        tasks_done=sum(1 for task in context.tasks_today if task.done),
        tasks_total=len(context.tasks_today),
        steps=[
            AgentStep(tool_name=call.tool_name, ok=call.ok, summary=call.summary)
            for call in result.tool_calls
        ],
    )
