"""The family calendar: a senior's appointments, when each family member is free, and who is going
along. Shared by everyone in the senior's family group, and read by the senior too.

Rules, mirrored from the browser's `lib/family.ts` so both sides agree:

* A repeating appointment is stored once. Its days are worked out on read (`occurrence_dates`), and
  each day is its own `occurrence_id` (`<appointment_id>@<YYYY-MM-DD>`), so every week of a weekly
  visit has its own answers and helpers.
* A member's answer for one day of an appointment replaces their earlier answer for it. Saying
  "not available" also takes them off it: nobody helps with something they cannot make.
* "I'll help" takes the day and so also answers "available". "Step back" only takes them off.
* Members only change their own availability and their own helping; anyone in the group can add,
  change or remove appointments.
* A member can ask another to take a day (`family_asks`). "I'll help" ends that day's open ask,
  and removing the day (an edit or a delete) withdraws it.

Writes need an **active** member of the group; anyone else gets 404, as for the group itself.
"""

from __future__ import annotations

import calendar as month_calendar
import contextlib
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from silverloop import family_activity, family_asks
from silverloop.db_models import (
    AccountRow,
    AppointmentNoteRow,
    AppointmentRow,
    AvailabilityEntryRow,
    CareGroupRow,
    FamilyActivityRow,
    FamilyPinRow,
    GroupMemberRow,
    HelperAskRow,
    HelperAssignmentRow,
    PersonRow,
)
from silverloop.family_activity import ORIGIN_DEMO_SEED, UnknownCursorError, record
from silverloop.family_groups import FamilyGroupError, senior_name_of
from silverloop.family_tasks import FamilyTaskStore, seed_demo_tasks
from silverloop.models import (
    Appointment,
    AppointmentKind,
    AppointmentNote,
    AppointmentNoteRequest,
    AppointmentOccurrence,
    AppointmentRequest,
    AvailabilityEntryOut,
    AvailabilityRequest,
    AvailabilityStatus,
    CalendarMember,
    CheckInKind,
    CheckInRequest,
    FamilyActivityEntry,
    FamilyActivityKind,
    FamilyActivityPage,
    FamilyCalendar,
    HelperAsk,
    HelperAskList,
    HelperAskRequest,
    HelperAssignment,
    MemberStatus,
    NotificationPage,
    NotificationReadRequest,
    RepeatRule,
)

AVATAR_COLOURS = 6
MAX_RANGE_DAYS = 400
MAX_NOTES_PER_DAY = 100


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


# ── Repeats ──────────────────────────────────────────────────────────────────


def _add_months(day: date, months: int) -> date | None:
    """The same day of the month `months` later, or None when that month is too short."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    if day.day > month_calendar.monthrange(year, month)[1]:
        return None
    return date(year, month, day.day)


def occurrence_dates(row: AppointmentRow, lo: date, hi: date) -> Iterator[date]:
    """Every day of `row` from `lo` to `hi`, inclusive. A monthly appointment on the 31st skips
    months without one."""
    last = min(hi, row.repeat_until) if row.repeat_until else hi
    start = row.start_date
    if start > last:
        return
    if row.repeat == RepeatRule.NONE:
        if lo <= start:
            yield start
        return
    if row.repeat in (RepeatRule.DAILY, RepeatRule.WEEKLY):
        step = 1 if row.repeat == RepeatRule.DAILY else 7
        skip = max(0, -(-(lo - start).days // step))  # whole steps to reach `lo`
        day = start + timedelta(days=skip * step)
        while day <= last:
            yield day
            day += timedelta(days=step)
        return
    months = 0
    while True:
        day = _add_months(start, months)
        months += 1
        if day is None:
            continue
        if day > last:
            return
        if day >= lo:
            yield day


def occurrence_id(appointment_id: str, day: date) -> str:
    return f"{appointment_id}@{day.isoformat()}"


def _parse_occurrence(value: str) -> tuple[str, date]:
    appointment_id, _, day = value.partition("@")
    try:
        return appointment_id, date.fromisoformat(day)
    except ValueError as exc:
        raise FamilyGroupError(404, "Appointment not found") from exc


def _appointment_out(row: AppointmentRow) -> Appointment:
    return Appointment(
        appointment_id=row.appointment_id,
        title=row.title,
        kind=AppointmentKind(row.kind),
        date=row.start_date,
        start=row.start_time,
        end=row.end_time,
        location=row.location,
        notes=row.notes,
        repeat=RepeatRule(row.repeat),
        repeat_until=row.repeat_until,
    )


def _stored_fields(row: AppointmentRow) -> tuple[object, ...]:
    """Everything `_apply` sets, to tell whether an edit changed anything."""
    return (
        row.title,
        row.kind,
        row.start_date,
        row.start_time,
        row.end_time,
        row.location,
        row.notes,
        row.repeat,
        row.repeat_until,
    )


def _feed_day(row: AppointmentRow) -> date | None:
    """The day a feed entry about this appointment points at: its one day, or None for a repeating
    appointment (the entry is about the series, so it links to no single occurrence)."""
    return row.start_date if row.repeat == RepeatRule.NONE else None


class FamilyCalendarStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    # ── Who may do what ──────────────────────────────────────────────────────

    @staticmethod
    def _active_member(session: Session, sub: str, group_id: str) -> GroupMemberRow:
        member = session.scalar(
            select(GroupMemberRow).where(
                GroupMemberRow.group_id == group_id,
                GroupMemberRow.sub == sub,
                GroupMemberRow.status == MemberStatus.ACTIVE.value,
            )
        )
        if member is None:
            raise FamilyGroupError(404, "Group not found")
        return member

    def is_active_member_for_person(self, sub: str, person_id: str) -> bool:
        """Whether `sub` is an active member of the family group caring for `person_id`."""
        with self.sessions() as session:
            return (
                session.scalar(
                    select(GroupMemberRow.member_id)
                    .join(CareGroupRow, CareGroupRow.group_id == GroupMemberRow.group_id)
                    .where(
                        CareGroupRow.person_id == person_id,
                        GroupMemberRow.sub == sub,
                        GroupMemberRow.status == MemberStatus.ACTIVE.value,
                    )
                )
                is not None
            )

    # ── Reading ──────────────────────────────────────────────────────────────

    @staticmethod
    def _check_range(lo: date, hi: date) -> None:
        if hi < lo or (hi - lo).days > MAX_RANGE_DAYS:
            raise FamilyGroupError(422, f"Ask for at most {MAX_RANGE_DAYS} days at a time.")

    def calendar(
        self, person_id: str, viewer_sub: str | None, lo: date, hi: date
    ) -> FamilyCalendar:
        """The calendar of the senior `person_id`: their family group's, or an empty one when they
        have no group yet. Who may read it is checked by the route."""
        self._check_range(lo, hi)
        with self.sessions() as session:
            person = session.get(PersonRow, person_id)
            if person is None:
                raise FamilyGroupError(404, "Person not found")
            group = session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == person_id))
            if group is None:
                return FamilyCalendar(
                    person_id=person_id,
                    senior_name=person.display_name,
                    group_id=None,
                    from_date=lo,
                    to_date=hi,
                    members=[],
                    appointments=[],
                    availability=[],
                    assignments=[],
                )
            return self._group_calendar(session, group, viewer_sub, lo, hi)

    def group_calendar(self, sub: str, group_id: str, lo: date, hi: date) -> FamilyCalendar:
        """The family group's calendar, whether or not its senior is linked yet. Active members
        only; anyone else gets 404."""
        self._check_range(lo, hi)
        with self.sessions() as session:
            self._active_member(session, sub, group_id)
            group = session.get(CareGroupRow, group_id)
            if group is None:  # pragma: no cover - membership implies the group
                raise FamilyGroupError(404, "Group not found")
            return self._group_calendar(session, group, sub, lo, hi)

    @staticmethod
    def _group_calendar(
        session: Session, group: CareGroupRow, viewer_sub: str | None, lo: date, hi: date
    ) -> FamilyCalendar:
        # Until the senior is linked there is no person: the typed name, and nothing about them.
        person = session.get(PersonRow, group.person_id) if group.person_id is not None else None
        member_rows = session.execute(
            select(GroupMemberRow, AccountRow)
            .outerjoin(AccountRow, AccountRow.sub == GroupMemberRow.sub)
            .where(
                GroupMemberRow.group_id == group.group_id,
                GroupMemberRow.status == MemberStatus.ACTIVE.value,
            )
            .order_by(GroupMemberRow.created_at, GroupMemberRow.member_id)
        ).all()
        members = [
            CalendarMember(
                member_id=member.member_id,
                display_name=account.display_name if account else "Family member",
                relationship=member.relationship,
                colour=index % AVATAR_COLOURS,
                is_me=viewer_sub is not None and member.sub == viewer_sub,
            )
            for index, (member, account) in enumerate(member_rows)
        ]
        active_ids = {member.member_id for member in members}

        appointment_rows = session.scalars(
            select(AppointmentRow).where(AppointmentRow.group_id == group.group_id)
        ).all()
        days: set[str] = set()
        occurrences: list[AppointmentOccurrence] = []
        for row in appointment_rows:
            for day in occurrence_dates(row, lo, hi):
                key = occurrence_id(row.appointment_id, day)
                days.add(key)
                occurrences.append(
                    AppointmentOccurrence(
                        occurrence_id=key,
                        appointment_id=row.appointment_id,
                        title=row.title,
                        kind=AppointmentKind(row.kind),
                        date=day,
                        start=row.start_time,
                        end=row.end_time,
                        location=row.location,
                        notes=row.notes,
                        repeat=RepeatRule(row.repeat),
                    )
                )
        occurrences.sort(key=lambda o: (o.date, o.start, o.title))

        availability: list[AvailabilityEntryOut] = []
        for entry in session.scalars(
            select(AvailabilityEntryRow)
            .where(
                AvailabilityEntryRow.group_id == group.group_id,
                AvailabilityEntryRow.on_date >= lo,
                AvailabilityEntryRow.on_date <= hi,
            )
            .order_by(AvailabilityEntryRow.created_at, AvailabilityEntryRow.entry_id)
        ):
            key = (
                occurrence_id(entry.appointment_id, entry.on_date) if entry.appointment_id else None
            )
            # An answer for a day the appointment no longer has (it was moved) is left out.
            if entry.member_id not in active_ids or (key is not None and key not in days):
                continue
            availability.append(
                AvailabilityEntryOut(
                    entry_id=entry.entry_id,
                    member_id=entry.member_id,
                    date=entry.on_date,
                    start=entry.start_time,
                    end=entry.end_time,
                    status=AvailabilityStatus(entry.status),
                    occurrence_id=key,
                )
            )

        assignments = [
            HelperAssignment(
                occurrence_id=occurrence_id(row.appointment_id, row.on_date),
                member_id=row.member_id,
            )
            for row in session.scalars(
                select(HelperAssignmentRow)
                .where(
                    HelperAssignmentRow.group_id == group.group_id,
                    HelperAssignmentRow.on_date >= lo,
                    HelperAssignmentRow.on_date <= hi,
                )
                .order_by(HelperAssignmentRow.created_at, HelperAssignmentRow.assignment_id)
            )
            if row.member_id in active_ids
            and occurrence_id(row.appointment_id, row.on_date) in days
        ]
        return FamilyCalendar(
            person_id=group.person_id,
            senior_name=senior_name_of(group, person),
            group_id=group.group_id,
            from_date=lo,
            to_date=hi,
            members=members,
            appointments=occurrences,
            availability=availability,
            assignments=assignments,
        )

    # ── Appointments ─────────────────────────────────────────────────────────

    def create_appointment(self, sub: str, group_id: str, body: AppointmentRequest) -> Appointment:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            row = AppointmentRow(
                appointment_id=_id("appt"),
                group_id=group_id,
                created_by=sub,
                created_at=_utcnow(),
            )
            self._apply(row, body)
            session.add(row)
            record(
                session,
                group_id=group_id,
                actor_member_id=member.member_id,
                kind=FamilyActivityKind.APPOINTMENT_ADDED,
                appointment=row,
                day=_feed_day(row),
            )
            return _appointment_out(row)

    def update_appointment(
        self, sub: str, group_id: str, appointment_id: str, body: AppointmentRequest
    ) -> Appointment:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            row = self._appointment(session, group_id, appointment_id, lock=True)
            # Asks whose day has started lapse first, at the time they had, before the edit could
            # withdraw them instead.
            family_asks.lapse_due(session, [group_id], self._occurs)
            before = _stored_fields(row)
            self._apply(row, body)
            # Saving the form unchanged is not news.
            if _stored_fields(row) != before:
                # Notes on a day the appointment no longer has could never be read or removed
                # again, so they go now. Their feed entries stay: those hold no text.
                for note in session.scalars(
                    select(AppointmentNoteRow).where(
                        AppointmentNoteRow.appointment_id == appointment_id
                    )
                ).all():
                    if not self._occurs(row, note.on_date):
                        session.delete(note)
                # An open ask for a day the appointment no longer has is withdrawn. A time change
                # on the same day keeps it open; it lapses at the new start.
                family_asks.withdraw_for_appointment(
                    session, row, member.member_id, occurs=self._occurs
                )
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=member.member_id,
                    kind=FamilyActivityKind.APPOINTMENT_CHANGED,
                    appointment=row,
                    day=_feed_day(row),
                )
            return _appointment_out(row)

    def delete_appointment(self, sub: str, group_id: str, appointment_id: str) -> None:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            row = self._appointment(session, group_id, appointment_id, lock=True)
            # Asks whose day has started lapse, not withdraw: the asker hears it went unanswered.
            family_asks.lapse_due(session, [group_id], self._occurs)
            # The entry keeps the title, since the appointment itself is about to go.
            record(
                session,
                group_id=group_id,
                actor_member_id=member.member_id,
                kind=FamilyActivityKind.APPOINTMENT_REMOVED,
                appointment=row,
                day=_feed_day(row),
            )
            # Its open asks end as withdrawn; the ask rows stay (no foreign key), with the title.
            family_asks.withdraw_for_appointment(session, row, member.member_id)
            session.execute(
                delete(AppointmentNoteRow).where(
                    AppointmentNoteRow.appointment_id == appointment_id
                )
            )
            session.execute(
                delete(AvailabilityEntryRow).where(
                    AvailabilityEntryRow.appointment_id == appointment_id
                )
            )
            session.execute(
                delete(HelperAssignmentRow).where(
                    HelperAssignmentRow.appointment_id == appointment_id
                )
            )
            session.delete(row)

    @staticmethod
    def _apply(row: AppointmentRow, body: AppointmentRequest) -> None:
        row.title = body.title.strip()
        row.kind = body.kind.value
        row.start_date = body.date
        row.start_time = body.start
        row.end_time = body.end
        row.location = (body.location or "").strip() or None
        row.notes = (body.notes or "").strip() or None
        row.repeat = body.repeat.value
        row.repeat_until = body.repeat_until if body.repeat != RepeatRule.NONE else None

    @staticmethod
    def _appointment(
        session: Session, group_id: str, appointment_id: str, *, lock: bool = False
    ) -> AppointmentRow:
        """`lock` takes the appointment row for update (PostgreSQL; a no-op on SQLite). Asking,
        "I'll go", editing and deleting take it before they read or end any ask, so they run one
        at a time per appointment: an ask cannot open on a day someone just took or removed. The
        lock comes before `lapse_due`, which updates asks, so every path locks in the same order.
        """
        row = session.get(AppointmentRow, appointment_id, with_for_update=lock or None)
        if row is None or row.group_id != group_id:
            raise FamilyGroupError(404, "Appointment not found")
        return row

    def _occurrence(
        self, session: Session, group_id: str, value: str, *, lock: bool = False
    ) -> tuple[AppointmentRow, date]:
        appointment_id, day = _parse_occurrence(value)
        row = self._appointment(session, group_id, appointment_id, lock=lock)
        if next(occurrence_dates(row, day, day), None) != day:
            raise FamilyGroupError(404, "Appointment not found")
        return row, day

    # ── Availability and helping (always the caller's own) ───────────────────

    def add_window(
        self, sub: str, group_id: str, body: AvailabilityRequest
    ) -> AvailabilityEntryOut:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            entry = AvailabilityEntryRow(
                entry_id=_id("avail"),
                group_id=group_id,
                member_id=member.member_id,
                on_date=body.date,
                start_time=body.start,
                end_time=body.end,
                status=body.status.value,
                created_at=_utcnow(),
            )
            session.add(entry)
            family_activity.record_availability_updated(
                session, group_id=group_id, actor_member_id=member.member_id, day=body.date
            )
            return AvailabilityEntryOut(
                entry_id=entry.entry_id,
                member_id=member.member_id,
                date=body.date,
                start=body.start,
                end=body.end,
                status=body.status,
                occurrence_id=None,
            )

    def remove_entry(self, sub: str, group_id: str, entry_id: str) -> None:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            entry = session.get(AvailabilityEntryRow, entry_id)
            if entry is None or entry.member_id != member.member_id:
                raise FamilyGroupError(404, "Not found")
            day = entry.on_date
            session.delete(entry)
            family_activity.record_availability_updated(
                session, group_id=group_id, actor_member_id=member.member_id, day=day
            )

    def _answer(
        self,
        session: Session,
        member: GroupMemberRow,
        row: AppointmentRow,
        day: date,
        status: AvailabilityStatus,
    ) -> int:
        """Replace the member's answer for the day. Returns how many helper assignments that
        removed (only "unavailable" removes one)."""
        session.execute(
            delete(AvailabilityEntryRow).where(
                AvailabilityEntryRow.member_id == member.member_id,
                AvailabilityEntryRow.appointment_id == row.appointment_id,
                AvailabilityEntryRow.on_date == day,
            )
        )
        session.add(
            AvailabilityEntryRow(
                entry_id=_id("answer"),
                group_id=row.group_id,
                member_id=member.member_id,
                on_date=day,
                start_time=row.start_time,
                end_time=row.end_time,
                status=status.value,
                appointment_id=row.appointment_id,
                created_at=_utcnow(),
            )
        )
        if status == AvailabilityStatus.UNAVAILABLE:
            return self._step_back(session, member, row, day)
        return 0

    @staticmethod
    def _step_back(session: Session, member: GroupMemberRow, row: AppointmentRow, day: date) -> int:
        """Take the member off the day. Returns how many assignments that removed (0 or 1)."""
        assignments = session.scalars(
            select(HelperAssignmentRow).where(
                HelperAssignmentRow.member_id == member.member_id,
                HelperAssignmentRow.appointment_id == row.appointment_id,
                HelperAssignmentRow.on_date == day,
            )
        ).all()
        for assignment in assignments:
            session.delete(assignment)
        return len(assignments)

    def answer(self, sub: str, group_id: str, occurrence: str, status: AvailabilityStatus) -> None:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            row, day = self._occurrence(session, group_id, occurrence)
            if self._answer(session, member, row, day, status):
                # An answer alone is not news, but losing a helper is.
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=member.member_id,
                    kind=FamilyActivityKind.HELPER_STEPPED_BACK,
                    appointment=row,
                    day=day,
                )

    def volunteer(self, sub: str, group_id: str, occurrence: str) -> None:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            # Locked so a concurrent ask for this day waits and then sees the new helper.
            row, day = self._occurrence(session, group_id, occurrence, lock=True)
            # "I'll go" ends an open ask for the day: accepted if it was the asked member.
            family_asks.on_volunteer(session, member, row, day, self._occurs)
            if self._volunteer(session, member, row, day):
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=member.member_id,
                    kind=FamilyActivityKind.HELPER_JOINED,
                    appointment=row,
                    day=day,
                )

    def _volunteer(
        self, session: Session, member: GroupMemberRow, row: AppointmentRow, day: date
    ) -> bool:
        """Answer "available" and take the day. Returns whether the member was newly added."""
        self._answer(session, member, row, day, AvailabilityStatus.AVAILABLE)
        already = session.scalar(
            select(HelperAssignmentRow.assignment_id).where(
                HelperAssignmentRow.member_id == member.member_id,
                HelperAssignmentRow.appointment_id == row.appointment_id,
                HelperAssignmentRow.on_date == day,
            )
        )
        if already is None:
            session.add(
                HelperAssignmentRow(
                    assignment_id=_id("help"),
                    group_id=row.group_id,
                    appointment_id=row.appointment_id,
                    on_date=day,
                    member_id=member.member_id,
                    created_at=_utcnow(),
                )
            )
        return already is None

    def step_back(self, sub: str, group_id: str, occurrence: str) -> None:
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            row, day = self._occurrence(session, group_id, occurrence)
            if self._step_back(session, member, row, day):
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=member.member_id,
                    kind=FamilyActivityKind.HELPER_STEPPED_BACK,
                    appointment=row,
                    day=day,
                )

    # ── Activity feed and check-ins ──────────────────────────────────────────

    @staticmethod
    def _occurs(row: AppointmentRow, day: date) -> bool:
        return next(occurrence_dates(row, day, day), None) == day

    def activity(
        self, sub: str, group_id: str, limit: int, before: str | None
    ) -> FamilyActivityPage:
        """The group's feed, newest first. Active members only."""
        with self.sessions() as session:
            self._active_member(session, sub, group_id)
            try:
                return family_activity.page(
                    session,
                    group_id=group_id,
                    viewer_sub=sub,
                    limit=limit,
                    before=before,
                    occurs=self._occurs,
                )
            except UnknownCursorError as exc:
                raise FamilyGroupError(422, "That page marker is not one of this group's.") from exc

    def check_in(self, sub: str, group_id: str, body: CheckInRequest) -> FamilyActivityEntry:
        """Tell the group you called, visited or messaged the senior. The note is for the group
        only: nothing is sent to the senior and nothing goes to logs or the audit trail."""
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            row = record(
                session,
                group_id=group_id,
                actor_member_id=member.member_id,
                kind=FamilyActivityKind.CHECK_IN,
                check_in_kind=CheckInKind(body.kind),
                note=body.note,
            )
            session.flush()
            [entry] = family_activity.entries_out(session, [row], sub, self._occurs)
            return entry

    # ── Asks and notifications (rules in `family_asks`) ──────────────────────
    #
    # Each opens a write transaction, even to read, because open asks whose day has started lapse
    # on access (ADR 0014). Asking, accepting, declining and withdrawing check membership, lock the
    # appointment, and only then lapse due asks (see `_appointment` and `_ask_locked`); then the
    # actor (403), then an ended ask (409), then the rest. Listing open asks lapses first: it locks
    # no appointment.

    def create_ask(self, sub: str, group_id: str, body: HelperAskRequest) -> HelperAsk:
        try:
            with self.sessions.begin() as session:
                member = self._active_member(session, sub, group_id)
                # The appointment is locked before lapsing, the same order as "I'll go" and
                # editing, so the helper and day checks below cannot race them.
                row, day = self._occurrence(session, group_id, body.occurrence_id, lock=True)
                family_asks.lapse_due(session, [group_id], self._occurs)
                ask = family_asks.create(
                    session,
                    asker=member,
                    appointment=row,
                    day=day,
                    asked_member_id=body.asked_member_id,
                )
                session.flush()
                return family_asks.ask_out(session, ask, member.member_id)
        except IntegrityError as exc:
            # Another ask for the same day was opened between the check and this insert.
            raise FamilyGroupError(409, family_asks.ALREADY_OPEN) from exc

    def open_asks(self, sub: str, group_id: str) -> HelperAskList:
        """The group's open asks, for the "Asked Emily · waiting" tags. Active members only."""
        with self.sessions.begin() as session:
            family_asks.lapse_due(session, [group_id], self._occurs)
            member = self._active_member(session, sub, group_id)
            return HelperAskList(asks=family_asks.open_asks(session, group_id, member.member_id))

    def _ask_locked(
        self, session: Session, sub: str, group_id: str, ask_id: str
    ) -> tuple[GroupMemberRow, HelperAskRow]:
        """Membership, then the ask, in the lock order every path keeps (see `_appointment`): the
        ask is read without a lock, its appointment is locked, and only then are due asks lapsed
        and this ask re-read. Ending the ask first and adding the helper after would hold the ask
        while waiting on the appointment, against "I'll go" or a delete that hold the appointment
        while waiting on the ask: a deadlock on PostgreSQL."""
        member = self._active_member(session, sub, group_id)
        ask = family_asks.ask_in_group(session, group_id, ask_id)
        # A missing appointment means its asks have already ended: the checks below answer 409.
        with contextlib.suppress(FamilyGroupError):
            self._appointment(session, group_id, ask.appointment_id, lock=True)
        family_asks.lapse_due(session, [group_id], self._occurs)
        session.refresh(ask)
        return member, ask

    def accept_ask(self, sub: str, group_id: str, ask_id: str) -> None:
        """The asked member says yes and becomes the helper, exactly as "I'll go" (`helper_joined`
        in the feed, with them as the actor)."""
        with self.sessions.begin() as session:
            member, ask = self._ask_locked(session, sub, group_id, ask_id)
            family_asks.accept(session, ask, member)
            # An open ask's day still exists: removing it withdraws the ask.
            row = self._checked_occurrence(session, group_id, ask.appointment_id, ask.on_date)
            if self._volunteer(session, member, row, ask.on_date):
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=member.member_id,
                    kind=FamilyActivityKind.HELPER_JOINED,
                    appointment=row,
                    day=ask.on_date,
                )

    def decline_ask(self, sub: str, group_id: str, ask_id: str) -> None:
        with self.sessions.begin() as session:
            member, ask = self._ask_locked(session, sub, group_id, ask_id)
            # Checked before the day is checked, so an ended ask is 409 whatever became of it.
            family_asks.check_can_answer(ask, member)
            row = self._checked_occurrence(session, group_id, ask.appointment_id, ask.on_date)
            family_asks.decline(session, ask, member, row)

    def withdraw_ask(self, sub: str, group_id: str, ask_id: str) -> None:
        with self.sessions.begin() as session:
            member, ask = self._ask_locked(session, sub, group_id, ask_id)
            family_asks.withdraw(session, ask, member)

    @staticmethod
    def _memberships(session: Session, sub: str) -> list[GroupMemberRow]:
        return list(
            session.scalars(
                select(GroupMemberRow).where(
                    GroupMemberRow.sub == sub,
                    GroupMemberRow.status == MemberStatus.ACTIVE.value,
                )
            )
        )

    def notifications(self, sub: str, limit: int, before: str | None) -> NotificationPage:
        """The caller's notifications across all their active memberships, newest first. Empty for
        someone in no group."""
        with self.sessions.begin() as session:
            memberships = self._memberships(session, sub)
            family_asks.lapse_due(
                session, {member.group_id for member in memberships}, self._occurs
            )
            try:
                return family_asks.notifications_page(
                    session, memberships, limit=limit, before=before, occurs=self._occurs
                )
            except family_asks.UnknownCursorError as exc:
                raise FamilyGroupError(422, "That page marker is not one of yours.") from exc

    def mark_notifications_read(self, sub: str, body: NotificationReadRequest) -> None:
        with self.sessions.begin() as session:
            family_asks.mark_read(
                session,
                self._memberships(session, sub),
                body.notification_ids,
                everything=body.all,
            )

    # ── Appointment notes (per day, for the group only) ──────────────────────

    def _checked_occurrence(
        self, session: Session, group_id: str, appointment_id: str, day: date
    ) -> AppointmentRow:
        row = self._appointment(session, group_id, appointment_id)
        if not self._occurs(row, day):
            raise FamilyGroupError(404, "Appointment not found")
        return row

    def list_notes(
        self, sub: str, group_id: str, appointment_id: str, day: date
    ) -> list[AppointmentNote]:
        """The day's notes, oldest first (at most 100). A day the appointment no longer has is 404,
        so notes left on a moved day are never shown. Active members only."""
        with self.sessions() as session:
            self._active_member(session, sub, group_id)
            self._checked_occurrence(session, group_id, appointment_id, day)
            rows = session.scalars(
                select(AppointmentNoteRow)
                .where(
                    AppointmentNoteRow.appointment_id == appointment_id,
                    AppointmentNoteRow.on_date == day,
                )
                .order_by(AppointmentNoteRow.created_at, AppointmentNoteRow.note_id)
                .limit(MAX_NOTES_PER_DAY)
            ).all()
            return self._notes_out(session, rows, sub)

    @staticmethod
    def _notes_out(
        session: Session, rows: list[AppointmentNoteRow], viewer_sub: str
    ) -> list[AppointmentNote]:
        member_ids = {row.member_id for row in rows}
        authors: dict[str, tuple[str, str]] = {}
        if member_ids:
            for member, account in session.execute(
                select(GroupMemberRow, AccountRow)
                .outerjoin(AccountRow, AccountRow.sub == GroupMemberRow.sub)
                .where(GroupMemberRow.member_id.in_(member_ids))
            ):
                authors[member.member_id] = (
                    member.sub,
                    account.display_name if account else family_activity.FALLBACK_NAME,
                )
        return [
            AppointmentNote(
                note_id=row.note_id,
                appointment_id=row.appointment_id,
                occurrence_id=occurrence_id(row.appointment_id, row.on_date),
                member_id=row.member_id,
                author_name=authors.get(row.member_id, ("", family_activity.FALLBACK_NAME))[1],
                is_mine=authors.get(row.member_id, ("", ""))[0] == viewer_sub,
                text=row.text,
                created_at=family_activity.aware(row.created_at),
            )
            for row in rows
        ]

    def add_note(
        self, sub: str, group_id: str, appointment_id: str, body: AppointmentNoteRequest
    ) -> AppointmentNote:
        """Add a note to one day of an appointment. The feed records that a note was added, never
        what it said; the text goes to no log, audit event or agent."""
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            appointment = self._checked_occurrence(session, group_id, appointment_id, body.date)
            held = session.scalar(
                select(func.count())
                .select_from(AppointmentNoteRow)
                .where(
                    AppointmentNoteRow.appointment_id == appointment_id,
                    AppointmentNoteRow.on_date == body.date,
                )
            )
            if (held or 0) >= MAX_NOTES_PER_DAY:
                raise FamilyGroupError(409, "This day already has the most notes it can hold")
            row = AppointmentNoteRow(
                note_id=_id("note"),
                group_id=group_id,
                appointment_id=appointment_id,
                on_date=body.date,
                member_id=member.member_id,
                text=body.text,
                created_at=_utcnow(),
            )
            session.add(row)
            record(
                session,
                group_id=group_id,
                actor_member_id=member.member_id,
                kind=FamilyActivityKind.NOTE_ADDED,
                appointment=appointment,
                day=body.date,
            )
            session.flush()
            [note] = self._notes_out(session, [row], sub)
            return note

    def delete_note(self, sub: str, group_id: str, note_id: str) -> None:
        """Remove your own note. The feed entry that it was added stays."""
        with self.sessions.begin() as session:
            member = self._active_member(session, sub, group_id)
            row = session.get(AppointmentNoteRow, note_id)
            if row is None or row.group_id != group_id:
                raise FamilyGroupError(404, "Note not found")
            if row.member_id != member.member_id:
                raise FamilyGroupError(403, "You can only remove your own notes")
            session.delete(row)

    # ── Offline demo ─────────────────────────────────────────────────────────

    def reset_demo(self, person_id: str, today: date, members: dict[str, str]) -> None:
        """Sign-in off only: put the demo group back as it starts, schedule relative to `today`.

        `members` maps each demo account to its relationship, owner first. Anyone else who joined
        the demo group is removed, with their answers, so every demo (and e2e test) starts alike.
        Groups a demo account created that have no senior linked are removed too, and a demo
        account leaves any other unlinked group it joined: left behind, one would be the demo
        family's first group once their memberships are re-dated below.
        """
        with self.sessions.begin() as session:
            self.reset_demo_in(session, person_id, today, members)

    def reset_demo_in(
        self,
        session: Session,
        person_id: str,
        today: date,
        members: dict[str, str],
        *,
        also_creators: Iterable[str] = (),
        leave_other_unlinked_groups: bool = True,
    ) -> None:
        """`reset_demo` inside the caller's transaction, also used by `silverloop.demo_story`.

        `members` is the owner (Sarah), then John, then Emily. `also_creators` are other accounts
        whose unlinked groups go too, without making them members here. With
        `leave_other_unlinked_groups=False`, a member keeps a place in an unlinked group somebody
        else created, so that group stays exactly as it is.
        """
        unlinked = list(
            session.scalars(
                select(CareGroupRow.group_id).where(
                    CareGroupRow.person_id.is_(None),
                    CareGroupRow.created_by.in_([*members, *also_creators]),
                )
            )
        )
        if unlinked:
            # Children first, in the same order as below, then the groups themselves.
            FamilyTaskStore.delete_for_groups(session, unlinked)
            family_asks.delete_for_groups(session, unlinked)
            for table in (
                AppointmentNoteRow,
                FamilyActivityRow,
                HelperAssignmentRow,
                AvailabilityEntryRow,
                AppointmentRow,
                FamilyPinRow,
                GroupMemberRow,
            ):
                session.execute(delete(table).where(table.group_id.in_(unlinked)))
            session.execute(delete(CareGroupRow).where(CareGroupRow.group_id.in_(unlinked)))
        if leave_other_unlinked_groups:
            # A demo account that joined someone else's unlinked group leaves it (the group
            # stays), with what pointed at its membership there, so the demo group is its only one.
            joined = list(
                session.scalars(
                    select(GroupMemberRow.member_id)
                    .join(CareGroupRow, CareGroupRow.group_id == GroupMemberRow.group_id)
                    .where(
                        CareGroupRow.person_id.is_(None),
                        GroupMemberRow.sub.in_(list(members)),
                    )
                )
            )
            if joined:
                family_asks.delete_for_members(session, joined)
                session.execute(
                    delete(FamilyActivityRow).where(
                        or_(
                            FamilyActivityRow.actor_member_id.in_(joined),
                            FamilyActivityRow.subject_member_id.in_(joined),
                        )
                    )
                )
                for table in (AppointmentNoteRow, HelperAssignmentRow, AvailabilityEntryRow):
                    session.execute(delete(table).where(table.member_id.in_(joined)))
                session.execute(delete(GroupMemberRow).where(GroupMemberRow.member_id.in_(joined)))
        group = session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == person_id))
        if group is None:
            return
        group_id = group.group_id
        FamilyTaskStore.delete_for_groups(session, [group_id])
        # Notifications and asks, then notes and the feed: their rows point at members (and notes
        # at appointments), which are removed further down.
        family_asks.delete_for_groups(session, [group_id])
        for table in (
            AppointmentNoteRow,
            FamilyActivityRow,
            HelperAssignmentRow,
            AvailabilityEntryRow,
            AppointmentRow,
        ):
            session.execute(delete(table).where(table.group_id == group_id))
        session.execute(delete(FamilyPinRow).where(FamilyPinRow.group_id == group_id))
        session.execute(
            delete(GroupMemberRow).where(
                GroupMemberRow.group_id == group_id,
                GroupMemberRow.sub.not_in(list(members)),
            )
        )
        # Nobody has a current group when a demo starts.
        session.execute(
            update(GroupMemberRow)
            .where(GroupMemberRow.group_id == group_id)
            .values(last_opened_at=None)
        )
        # Created one microsecond apart so the members keep this order (and their colours).
        base = _utcnow()
        by_sub: dict[str, GroupMemberRow] = {}
        for index, (sub, relationship) in enumerate(members.items()):
            member = session.scalar(
                select(GroupMemberRow).where(
                    GroupMemberRow.group_id == group_id, GroupMemberRow.sub == sub
                )
            )
            if member is None:
                member = GroupMemberRow(member_id=_id("mem"), group_id=group_id, sub=sub)
                session.add(member)
            member.relationship = relationship
            member.role = "owner" if index == 0 else "member"
            member.status = MemberStatus.ACTIVE.value
            member.created_at = base + timedelta(microseconds=index)
            member.approved_by = next(iter(members))
            member.approved_at = base
            by_sub[sub] = member
        session.flush()
        _seed_demo_schedule(self, session, group_id, today, by_sub)
        seed_demo_tasks(session, group_id, today, next(iter(members)))


# The demo schedule: the same made-up visits the browser used to hold (`lib/family-sample.ts`).
_DEMO_APPOINTMENTS: list[tuple[str, str, str, int, str, str, str, str]] = [
    (
        "demo-doctor",
        "Doctor’s appointment",
        "medical",
        1,
        "10:00",
        "12:00",
        "Neighbourhood polyclinic",
        "Bring her NRIC and health booklet. Registration closes at 9:45 am, so aim to arrive by "
        "9:30.",
    ),
    (
        "demo-taichi",
        "Morning Tai Chi",
        "activity",
        2,
        "08:30",
        "09:30",
        "Active Ageing Centre, multi-purpose hall",
        "Comfortable shoes and a water bottle. She likes to sit near the front.",
    ),
    (
        "demo-physio",
        "Physiotherapy session",
        "therapy",
        3,
        "14:00",
        "15:00",
        "Community rehabilitation centre",
        "Her exercise sheet is in the green folder by the door.",
    ),
    (
        "demo-groceries",
        "Grocery shopping",
        "errand",
        4,
        "10:00",
        "11:30",
        "Neighbourhood supermarket",
        "She likes to choose her own fruit. Bring the trolley bag.",
    ),
    (
        "demo-kopi",
        "Kopi & Chat",
        "activity",
        4,
        "15:00",
        "16:30",
        "Active Ageing Centre, ground-floor lounge",
        "A relaxed social hour. Family are welcome to stay.",
    ),
    (
        "demo-eye",
        "Eye check-up",
        "medical",
        7,
        "09:30",
        "10:30",
        "Community eye clinic",
        "Allow about an hour. Someone should go home with her afterwards.",
    ),
    (
        "demo-karaoke",
        "Karaoke & Social Hour",
        "activity",
        9,
        "14:00",
        "16:00",
        "Active Ageing Centre, multi-purpose hall",
        "Her favourite session. She usually sings two songs.",
    ),
    (
        "demo-followup",
        "Follow-up visit",
        "medical",
        12,
        "11:00",
        "12:00",
        "Neighbourhood polyclinic",
        "Bring the notes from the last visit.",
    ),
]


def _seed_demo_schedule(
    store: FamilyCalendarStore,
    session: Session,
    group_id: str,
    today: date,
    by_sub: dict[str, GroupMemberRow],
) -> None:
    # Owner first, as `reset_demo_in` documents, so this works for either set of accounts.
    sarah, john, emily = by_sub.values()
    now = _utcnow()
    rows: dict[str, AppointmentRow] = {}
    for key, title, kind, offset, start, end, location, notes in _DEMO_APPOINTMENTS:
        row = AppointmentRow(
            appointment_id=key,  # one demo group, so the demo ids can stay readable
            group_id=group_id,
            title=title,
            kind=kind,
            start_date=today + timedelta(days=offset),
            start_time=start,
            end_time=end,
            location=location,
            notes=notes,
            repeat=RepeatRule.NONE.value,
            repeat_until=None,
            created_by=sarah.sub,
            created_at=now,
        )
        session.add(row)
        rows[key] = row
    session.flush()

    windows = [
        (john, 1, "00:00", "23:59", "available"),
        (emily, 1, "00:00", "23:59", "unavailable"),
        (emily, 4, "12:00", "17:00", "available"),
        (john, 7, "08:00", "12:00", "available"),
        (sarah, 9, "00:00", "23:59", "unavailable"),
    ]
    for member, offset, start, end, status in windows:
        session.add(
            AvailabilityEntryRow(
                entry_id=_id("avail"),
                group_id=group_id,
                member_id=member.member_id,
                on_date=today + timedelta(days=offset),
                start_time=start,
                end_time=end,
                status=status,
                created_at=now,
            )
        )
    # Sarah is free for the doctor's visit but nobody has taken it, so a first-time visitor can
    # try "I'll help" on it. The others are already shared out.
    doctor = rows["demo-doctor"]
    store._answer(session, sarah, doctor, doctor.start_date, AvailabilityStatus.AVAILABLE)
    for member, key in (
        (john, "demo-taichi"),
        (sarah, "demo-physio"),
        (emily, "demo-physio"),
        (sarah, "demo-kopi"),
    ):
        store._volunteer(session, member, rows[key], rows[key].start_date)

    # A few believable entries, backdated and consistent with the schedule above.
    taichi, physio, doctor = rows["demo-taichi"], rows["demo-physio"], rows["demo-doctor"]
    note_at = now - timedelta(hours=8)
    session.add(
        AppointmentNoteRow(
            note_id=_id("note"),
            group_id=group_id,
            appointment_id=doctor.appointment_id,
            on_date=doctor.start_date,
            member_id=sarah.member_id,
            text="I'll bring her NRIC and health booklet, they're in the blue folder.",
            created_at=note_at,
        )
    )
    seeded: list[tuple[timedelta, GroupMemberRow, dict[str, Any]]] = [
        (
            timedelta(days=3, hours=2),
            john,
            {"kind": FamilyActivityKind.CHECK_IN, "check_in_kind": CheckInKind.VISITED},
        ),
        (
            timedelta(days=2, hours=1),
            john,
            {
                "kind": FamilyActivityKind.HELPER_JOINED,
                "appointment": taichi,
                "day": taichi.start_date,
            },
        ),
        (
            timedelta(days=1, hours=4),
            sarah,
            {
                "kind": FamilyActivityKind.CHECK_IN,
                "check_in_kind": CheckInKind.CALLED,
                "note": "She sounded cheerful",
            },
        ),
        (
            timedelta(hours=20),
            sarah,
            {
                "kind": FamilyActivityKind.HELPER_JOINED,
                "appointment": physio,
                "day": physio.start_date,
            },
        ),
        (
            timedelta(hours=8),
            sarah,
            {
                "kind": FamilyActivityKind.NOTE_ADDED,
                "appointment": doctor,
                "day": doctor.start_date,
            },
        ),
        (
            timedelta(hours=5),
            emily,
            {
                "kind": FamilyActivityKind.AVAILABILITY_UPDATED,
                "day": today + timedelta(days=4),
            },
        ),
    ]
    for age, actor, fields in seeded:
        record(
            session,
            group_id=group_id,
            actor_member_id=actor.member_id,
            origin=ORIGIN_DEMO_SEED,
            at=now - age,
            **fields,
        )
