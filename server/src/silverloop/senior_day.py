"""Builds "Read my day" from what the senior's own screen already shows.

Every read goes through the stores' own methods (`calendar`, `person_tasks`) behind the route's
`check_reader`, so the script can never say anything the senior's calendar and task list would
not. The agent itself (`silverloop.agent.my_day`) only sees the `MyDayContext` assembled here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from silverloop.agent.catchup import TaskToday
from silverloop.agent.loop import llm_source
from silverloop.agent.my_day import DayAppointment, MyDayContext, PartOfDay, write_my_day
from silverloop.config import Settings
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_tasks import FamilyTaskStore, occurs_on
from silverloop.local_time import local_hour
from silverloop.models import AgentStep, FamilyCalendar, MyDay


def part_of_day(now: datetime) -> PartOfDay:
    hour = local_hour(now)
    if hour < 12:
        return "morning"
    return "afternoon" if hour < 18 else "evening"


def _appointments(calendar: FamilyCalendar, day: date) -> list[DayAppointment]:
    names = {member.member_id: member.display_name for member in calendar.members}
    going: dict[str, list[str]] = {}
    for assignment in calendar.assignments:
        if name := names.get(assignment.member_id):
            going.setdefault(assignment.occurrence_id, []).append(name)
    return sorted(
        (
            DayAppointment(
                title=occurrence.title,
                kind=occurrence.kind.value,
                start=occurrence.start,
                end=occurrence.end,
                going_with=tuple(going.get(occurrence.occurrence_id, [])),
            )
            for occurrence in calendar.appointments
            if occurrence.date == day
        ),
        key=lambda item: item.start,
    )


def build_context(
    calendar: FamilyCalendarStore,
    tasks: FamilyTaskStore,
    person_id: str,
    viewer_sub: str | None,
    today: date,
    now: datetime,
) -> MyDayContext:
    tomorrow = today + timedelta(days=1)
    days = calendar.calendar(person_id, viewer_sub, today, tomorrow)
    task_list = tasks.person_tasks(person_id, today, today)
    ticked = {tick.task_id for tick in task_list.ticks if tick.day == today}
    reminders = sorted(
        (
            TaskToday(title=task.title, time=task.time, done=task.task_id in ticked)
            for task in task_list.tasks
            if occurs_on(task, today)  # type: ignore[arg-type] - same fields as the row
        ),
        key=lambda task: task.time,
    )
    return MyDayContext(
        senior_name=days.senior_name,
        today=today,
        part_of_day=part_of_day(now),
        appointments=_appointments(days, today),
        reminders=reminders,
        tomorrow=_appointments(days, tomorrow),
    )


def my_day(context: MyDayContext, settings: Settings) -> MyDay:
    result = write_my_day(context, settings=settings)
    return MyDay(
        mode=result.mode,
        source=llm_source(settings) if result.mode == "agent" else None,
        script=result.script,
        day=context.today,
        generated_at=datetime.now(UTC),
        model=result.model if result.mode == "agent" else None,
        appointments_today=len(context.appointments),
        reminders_done=sum(1 for task in context.reminders if task.done),
        reminders_total=len(context.reminders),
        steps=[
            AgentStep(tool_name=call.tool_name, ok=call.ok, summary=call.summary)
            for call in result.tool_calls
        ],
    )
