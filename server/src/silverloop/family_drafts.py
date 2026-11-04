"""Builds the typed-appointment draft from what the member typed and the group's calendar.

The calendar is read through the store's member-checked `group_calendar`, so a non-member gets the
same 404 the calendar gives. The agent (`silverloop.agent.appointment_draft`) only sees the
`DraftContext` assembled here, and nothing is saved.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from silverloop.agent.appointment_draft import (
    MAX_DAYS_AHEAD,
    DraftContext,
    ExistingAppointment,
    draft_appointment,
)
from silverloop.agent.loop import llm_source
from silverloop.config import Settings
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.models import AgentStep, AppointmentDraft, AppointmentKind, RepeatRule


def build_context(
    calendar: FamilyCalendarStore, sub: str, group_id: str, text: str, today: date
) -> DraftContext:
    upcoming = calendar.group_calendar(sub, group_id, today, today + timedelta(days=MAX_DAYS_AHEAD))
    return DraftContext(
        today=today,
        text=text,
        upcoming=[
            ExistingAppointment(title=item.title, day=item.date, start=item.start, end=item.end)
            for item in upcoming.appointments
        ],
    )


def draft(context: DraftContext, settings: Settings) -> AppointmentDraft:
    result = draft_appointment(context, settings=settings)
    filled = result.draft
    return AppointmentDraft(
        mode=result.mode,
        source=llm_source(settings) if result.mode == "agent" else None,
        title=filled.title,
        kind=AppointmentKind(filled.kind) if filled.kind else None,
        date=filled.date,
        start=filled.start,
        end=filled.end,
        location=filled.location,
        repeat=RepeatRule(filled.repeat),
        missing=filled.missing,
        assumed=filled.assumed,
        clashes=result.clashes,
        generated_at=datetime.now(UTC),
        model=result.model if result.mode == "agent" else None,
        steps=[
            AgentStep(tool_name=call.tool_name, ok=call.ok, summary=call.summary)
            for call in result.tool_calls
        ],
    )
