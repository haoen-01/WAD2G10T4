"""The family activity feed: what each member did in the group, newest first.

Append-only. `record` adds a row inside the caller's transaction, so an entry exists exactly when
the change it describes was committed; a refused action writes nothing. Only the public methods of
`FamilyGroups` and `FamilyCalendarStore` call it (never the private helpers that seed the demo).

Nothing here reaches the senior, the audit trail, the agent or any log. A check-in's note is shown
only to the group. This module must not import `policy`, `agent`, `learning` or `review_*`: the
feed can never influence a decision (tested in `test_family_activity.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from silverloop.db_models import (
    AccountRow,
    AppointmentRow,
    FamilyActivityRow,
    GroupMemberRow,
)
from silverloop.models import (
    AppointmentKind,
    CheckInKind,
    FamilyActivityEntry,
    FamilyActivityKind,
    FamilyActivityPage,
)

FALLBACK_NAME = "Family member"
ORIGIN_LIVE = "live"
ORIGIN_DEMO_SEED = "demo_seed"
# Editing the same day's free times again within this window is one entry, not many.
AVAILABILITY_DEDUPE_WINDOW = timedelta(minutes=15)


class UnknownCursorError(Exception):
    """`before` names no entry of this group."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; everything stored here is UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def record(
    session: Session,
    *,
    group_id: str,
    actor_member_id: str,
    kind: FamilyActivityKind,
    appointment: AppointmentRow | None = None,
    day: date | None = None,
    subject_member_id: str | None = None,
    check_in_kind: CheckInKind | None = None,
    note: str | None = None,
    origin: str = ORIGIN_LIVE,
    at: datetime | None = None,
) -> FamilyActivityRow:
    """Add one entry to the open transaction, snapshotting the appointment title and kind."""
    row = FamilyActivityRow(
        activity_id=f"act_{uuid4().hex[:16]}",
        group_id=group_id,
        kind=kind.value,
        actor_member_id=actor_member_id,
        subject_member_id=subject_member_id,
        appointment_id=appointment.appointment_id if appointment is not None else None,
        appointment_title=appointment.title if appointment is not None else None,
        appointment_kind=appointment.kind if appointment is not None else None,
        on_date=day,
        check_in_kind=check_in_kind.value if check_in_kind is not None else None,
        note=note,
        origin=origin,
        created_at=at or _utcnow(),
    )
    session.add(row)
    return row


def record_availability_updated(
    session: Session, *, group_id: str, actor_member_id: str, day: date
) -> FamilyActivityRow | None:
    """`availability_updated` for `day`, unless the same member already has one for that day in the
    last 15 minutes (a burst of edits reads as one entry). Skipping adds no row."""
    now = _utcnow()
    recent = session.scalar(
        select(FamilyActivityRow.activity_id)
        .where(
            FamilyActivityRow.group_id == group_id,
            FamilyActivityRow.actor_member_id == actor_member_id,
            FamilyActivityRow.kind == FamilyActivityKind.AVAILABILITY_UPDATED.value,
            FamilyActivityRow.on_date == day,
            FamilyActivityRow.created_at >= now - AVAILABILITY_DEDUPE_WINDOW,
        )
        .limit(1)
    )
    if recent is not None:
        return None
    return record(
        session,
        group_id=group_id,
        actor_member_id=actor_member_id,
        kind=FamilyActivityKind.AVAILABILITY_UPDATED,
        day=day,
        at=now,
    )


def entries_out(
    session: Session,
    rows: Sequence[FamilyActivityRow],
    viewer_sub: str,
    occurs: Callable[[AppointmentRow, date], bool],
) -> list[FamilyActivityEntry]:
    """Feed entries for `rows`, with names and `occurrence_id` worked out in two reads in all.

    `occurs(appointment, day)` says whether the appointment still has that day."""
    member_ids = {row.actor_member_id for row in rows} | {
        row.subject_member_id for row in rows if row.subject_member_id
    }
    names: dict[str, str] = {}
    subs: dict[str, str] = {}
    if member_ids:
        for member, account in session.execute(
            select(GroupMemberRow, AccountRow)
            .outerjoin(AccountRow, AccountRow.sub == GroupMemberRow.sub)
            .where(GroupMemberRow.member_id.in_(member_ids))
        ):
            subs[member.member_id] = member.sub
            names[member.member_id] = account.display_name if account else FALLBACK_NAME
    appointment_ids = {row.appointment_id for row in rows if row.appointment_id and row.on_date}
    appointments: dict[str, AppointmentRow] = {}
    if appointment_ids:
        appointments = {
            appointment.appointment_id: appointment
            for appointment in session.scalars(
                select(AppointmentRow).where(AppointmentRow.appointment_id.in_(appointment_ids))
            )
        }
    out: list[FamilyActivityEntry] = []
    for row in rows:
        occurrence: str | None = None
        if row.appointment_id and row.on_date:
            appointment = appointments.get(row.appointment_id)
            if appointment is not None and occurs(appointment, row.on_date):
                occurrence = f"{row.appointment_id}@{row.on_date.isoformat()}"
        out.append(
            FamilyActivityEntry(
                activity_id=row.activity_id,
                kind=FamilyActivityKind(row.kind),
                at=_aware(row.created_at),
                actor_member_id=row.actor_member_id,
                actor_name=names.get(row.actor_member_id, FALLBACK_NAME),
                is_me=subs.get(row.actor_member_id) == viewer_sub,
                subject_name=(
                    names.get(row.subject_member_id, FALLBACK_NAME)
                    if row.subject_member_id
                    else None
                ),
                appointment_id=row.appointment_id,
                appointment_title=row.appointment_title,
                appointment_kind=(
                    AppointmentKind(row.appointment_kind) if row.appointment_kind else None
                ),
                on_date=row.on_date,
                occurrence_id=occurrence,
                check_in_kind=CheckInKind(row.check_in_kind) if row.check_in_kind else None,
                note=row.note,
                origin="demo_seed" if row.origin == ORIGIN_DEMO_SEED else "live",
            )
        )
    return out


def page(
    session: Session,
    *,
    group_id: str,
    viewer_sub: str,
    limit: int,
    before: str | None,
    occurs: Callable[[AppointmentRow, date], bool],
) -> FamilyActivityPage:
    """The newest `limit` entries (keyset on `(created_at, activity_id)`, descending), after the
    entry `before` when given. Raises `UnknownCursorError` for a cursor not in this group."""
    query = select(FamilyActivityRow).where(FamilyActivityRow.group_id == group_id)
    if before is not None:
        cursor = session.get(FamilyActivityRow, before)
        if cursor is None or cursor.group_id != group_id:
            raise UnknownCursorError(before)
        at = _aware(cursor.created_at)
        query = query.where(
            or_(
                FamilyActivityRow.created_at < at,
                and_(
                    FamilyActivityRow.created_at == at,
                    FamilyActivityRow.activity_id < cursor.activity_id,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(
                FamilyActivityRow.created_at.desc(), FamilyActivityRow.activity_id.desc()
            ).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return FamilyActivityPage(
        entries=entries_out(session, rows, viewer_sub, occurs),
        next_before=rows[-1].activity_id if more else None,
    )
