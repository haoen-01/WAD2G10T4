"""Asks: one family member asking another, by name, to take one day of an appointment that needs a
helper, and the in-app notifications about it (issue #16).

* A group has at most one **open** ask per appointment day (`uq_helper_asks_open_day`). An open ask
  ends exactly once: `accepted`, `declined`, `withdrawn`, `lapsed` or `closed`. Every ending is a
  compare-and-set on `state = 'open'`, and its notification (and feed line, if any) is written only
  when that one row changed, so two requests racing to end the same ask cannot both succeed.
* There is no scheduler: `lapse_due` ends the open asks whose day has started. It runs in every
  ask route, in "I'll go", before an appointment edit or delete, and in `GET /v1/me/notifications`
  (ADR 0014).
* A notification goes only to the member it concerns (the asked member on an ask or a withdrawal,
  the asker on a yes, a no or a lapse, both on a close), never to whoever acted, never to the
  senior and never to the whole group (the feed covers that).
* "Needs a helper" means no **active** member is going (`_needs_helper`); a day with an open ask
  still needs one.

Session-level functions only: every one runs inside the caller's transaction. Route entry points
are thin methods on `FamilyCalendarStore`, which owns the appointments and passes `occurs` (whether
an appointment still has a day). The hooks there run only in its public methods, never in the
private helpers that seed the demo.

Nothing here reaches the audit trail, the agent or any log. This module must not import
`family_calendar`, `policy`, `agent`, `learning` or `review_*` (tested in `test_family_asks.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from silverloop.db_models import (
    AccountRow,
    AppointmentRow,
    CareGroupRow,
    GroupMemberRow,
    HelperAskRow,
    HelperAssignmentRow,
    NotificationRow,
    PersonRow,
)
from silverloop.family_activity import FALLBACK_NAME, aware, record
from silverloop.family_groups import FamilyGroupError, senior_name_of
from silverloop.local_time import at_local, local_date
from silverloop.models import (
    FamilyActivityKind,
    HelperAsk,
    HelperAskState,
    MemberStatus,
    NotificationItem,
    NotificationKind,
    NotificationPage,
)

Occurs = Callable[[AppointmentRow, date], bool]

OPEN = HelperAskState.OPEN.value
ALREADY_OPEN = "Someone has already been asked for this day"
ALREADY_ENDED = "This ask has already ended"


class UnknownCursorError(Exception):
    """`before` names no notification of the caller's."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def occurrence_id(appointment_id: str, day: date) -> str:
    # The same shape as `family_calendar.occurrence_id`, which this module must not import.
    return f"{appointment_id}@{day.isoformat()}"


def starts_at(appointment: AppointmentRow, day: date) -> datetime:
    """When the appointment starts on `day`, as a UTC instant: its start time is Singapore time."""
    hour, minute = appointment.start_time.split(":")
    return at_local(day, int(hour), int(minute))


# ── Reading and checking ─────────────────────────────────────────────────────


def open_ask(session: Session, appointment_id: str, day: date) -> HelperAskRow | None:
    return session.scalar(
        select(HelperAskRow).where(
            HelperAskRow.appointment_id == appointment_id,
            HelperAskRow.on_date == day,
            HelperAskRow.state == OPEN,
        )
    )


def ask_in_group(session: Session, group_id: str, ask_id: str) -> HelperAskRow:
    ask = session.get(HelperAskRow, ask_id)
    if ask is None or ask.group_id != group_id:
        raise FamilyGroupError(404, "Ask not found")
    return ask


def _active_helper_ids(session: Session, appointment: AppointmentRow, day: date) -> set[str]:
    return set(
        session.scalars(
            select(HelperAssignmentRow.member_id)
            .join(GroupMemberRow, GroupMemberRow.member_id == HelperAssignmentRow.member_id)
            .where(
                HelperAssignmentRow.appointment_id == appointment.appointment_id,
                HelperAssignmentRow.on_date == day,
                GroupMemberRow.status == MemberStatus.ACTIVE.value,
            )
        )
    )


def _needs_helper(session: Session, appointment: AppointmentRow, day: date) -> bool:
    """No active member is going. The one definition of "needs a helper" on the server."""
    return not _active_helper_ids(session, appointment, day)


def _names(session: Session, member_ids: Iterable[str]) -> dict[str, str]:
    wanted = set(member_ids)
    if not wanted:
        return {}
    return {
        member.member_id: account.display_name if account else FALLBACK_NAME
        for member, account in session.execute(
            select(GroupMemberRow, AccountRow)
            .outerjoin(AccountRow, AccountRow.sub == GroupMemberRow.sub)
            .where(GroupMemberRow.member_id.in_(wanted))
        )
    }


def ask_out(session: Session, ask: HelperAskRow, viewer_member_id: str) -> HelperAsk:
    return asks_out(session, [ask], viewer_member_id)[0]


def asks_out(
    session: Session, asks: Sequence[HelperAskRow], viewer_member_id: str
) -> list[HelperAsk]:
    names = _names(session, [m for ask in asks for m in (ask.asker_member_id, ask.asked_member_id)])
    out: list[HelperAsk] = []
    for ask in asks:
        is_open = ask.state == OPEN
        out.append(
            HelperAsk(
                ask_id=ask.ask_id,
                occurrence_id=occurrence_id(ask.appointment_id, ask.on_date),
                appointment_id=ask.appointment_id,
                on_date=ask.on_date,
                asker_member_id=ask.asker_member_id,
                asker_name=names.get(ask.asker_member_id, FALLBACK_NAME),
                asked_member_id=ask.asked_member_id,
                asked_name=names.get(ask.asked_member_id, FALLBACK_NAME),
                created_at=aware(ask.created_at),
                state=HelperAskState(ask.state),
                can_answer=is_open and viewer_member_id == ask.asked_member_id,
                can_withdraw=is_open and viewer_member_id == ask.asker_member_id,
            )
        )
    return out


def open_asks(session: Session, group_id: str, viewer_member_id: str) -> list[HelperAsk]:
    """The group's open asks, oldest first. Call `lapse_due` first."""
    rows = session.scalars(
        select(HelperAskRow)
        .where(HelperAskRow.group_id == group_id, HelperAskRow.state == OPEN)
        .order_by(HelperAskRow.created_at, HelperAskRow.ask_id)
    ).all()
    return asks_out(session, rows, viewer_member_id)


# ── Ending an ask, and who is told ───────────────────────────────────────────


def _notify(
    session: Session,
    ask: HelperAskRow,
    kind: NotificationKind,
    recipients: Iterable[str],
    *,
    actor_member_id: str | None,
    at: datetime,
) -> None:
    """One notification per recipient, never to the member who acted."""
    for member_id in dict.fromkeys(recipients):
        if member_id == actor_member_id:
            continue
        session.add(
            NotificationRow(
                notification_id=_id("ntf"),
                group_id=ask.group_id,
                recipient_member_id=member_id,
                kind=kind.value,
                ask_id=ask.ask_id,
                created_at=at,
                read_at=None,
            )
        )


def _end(
    session: Session,
    ask: HelperAskRow,
    state: HelperAskState,
    *,
    by: str | None,
    at: datetime,
) -> bool:
    """Compare-and-set `open` -> `state`. Returns whether this call ended it (exactly one row)."""
    result = session.execute(
        update(HelperAskRow)
        .where(HelperAskRow.ask_id == ask.ask_id, HelperAskRow.state == OPEN)
        .values(state=state.value, ended_at=at, ended_by_member_id=by)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.refresh(ask)
        return False
    session.refresh(ask)
    return True


def lapse_due(session: Session, group_ids: Collection[str], occurs: Occurs) -> None:
    """End the open asks of `group_ids` whose day has started: `lapsed` (the asker is told), or
    `withdrawn` (the asked member is told) when the appointment or that day of it is gone.

    Compares the appointment's current start time (Singapore) with now, so an ask whose time
    changed lapses at the new start."""
    if not group_ids:
        return
    now = _utcnow()
    # In `ask_id` order, so concurrent lapses update (and lock) the same rows in the same order.
    due = session.scalars(
        select(HelperAskRow)
        .where(
            HelperAskRow.group_id.in_(list(group_ids)),
            HelperAskRow.state == OPEN,
            HelperAskRow.on_date <= local_date(now),
        )
        .order_by(HelperAskRow.ask_id)
    ).all()
    if not due:
        return
    appointments = {
        row.appointment_id: row
        for row in session.scalars(
            select(AppointmentRow).where(
                AppointmentRow.appointment_id.in_({ask.appointment_id for ask in due})
            )
        )
    }
    for ask in due:
        appointment = appointments.get(ask.appointment_id)
        if appointment is None or not occurs(appointment, ask.on_date):
            if _end(session, ask, HelperAskState.WITHDRAWN, by=None, at=now):
                _notify(
                    session,
                    ask,
                    NotificationKind.ASK_WITHDRAWN,
                    [ask.asked_member_id],
                    actor_member_id=None,
                    at=now,
                )
        elif starts_at(appointment, ask.on_date) <= now and _end(
            session, ask, HelperAskState.LAPSED, by=None, at=now
        ):
            _notify(
                session,
                ask,
                NotificationKind.ASK_LAPSED,
                [ask.asker_member_id],
                actor_member_id=None,
                at=now,
            )


# ── The ask routes ───────────────────────────────────────────────────────────


def create(
    session: Session,
    *,
    asker: GroupMemberRow,
    appointment: AppointmentRow,
    day: date,
    asked_member_id: str,
) -> HelperAskRow:
    """Ask `asked_member_id` to take `day`. The caller has checked that `asker` is active and that
    the appointment has that day. 422 for yourself, someone not active in this group (the senior
    never is), a current helper, a day that has started or no longer needs a helper; 409 when
    someone has already been asked. Racing asks also end in 409 at the unique index (the store
    turns that `IntegrityError` into the same message)."""
    if asked_member_id == asker.member_id:
        raise FamilyGroupError(422, "You can't ask yourself")
    asked = session.get(GroupMemberRow, asked_member_id)
    if (
        asked is None
        or asked.group_id != appointment.group_id
        or asked.status != MemberStatus.ACTIVE.value
    ):
        raise FamilyGroupError(422, "Ask an active member of this family group")
    helpers = _active_helper_ids(session, appointment, day)
    if asked_member_id in helpers:
        raise FamilyGroupError(422, "They are already going")
    now = _utcnow()
    if starts_at(appointment, day) <= now:
        raise FamilyGroupError(422, "This day has already started")
    if helpers:
        raise FamilyGroupError(422, "This day no longer needs a helper")
    if open_ask(session, appointment.appointment_id, day) is not None:
        raise FamilyGroupError(409, ALREADY_OPEN)
    ask = HelperAskRow(
        ask_id=_id("ask"),
        group_id=appointment.group_id,
        appointment_id=appointment.appointment_id,
        appointment_title=appointment.title,
        on_date=day,
        asker_member_id=asker.member_id,
        asked_member_id=asked_member_id,
        state=OPEN,
        created_at=now,
        ended_at=None,
        ended_by_member_id=None,
    )
    session.add(ask)
    _notify(
        session,
        ask,
        NotificationKind.ASK_RECEIVED,
        [asked_member_id],
        actor_member_id=asker.member_id,
        at=now,
    )
    record(
        session,
        group_id=appointment.group_id,
        actor_member_id=asker.member_id,
        kind=FamilyActivityKind.HELPER_ASKED,
        appointment=appointment,
        day=day,
        subject_member_id=asked_member_id,
        at=now,
    )
    return ask


def check_can_answer(ask: HelperAskRow, member: GroupMemberRow) -> None:
    """Only the asked member says yes or no (else 403); an ended ask is 409."""
    if member.member_id != ask.asked_member_id:
        raise FamilyGroupError(403, "Only the member who was asked can answer")
    if ask.state != OPEN:
        raise FamilyGroupError(409, ALREADY_ENDED)


def check_can_withdraw(ask: HelperAskRow, member: GroupMemberRow) -> None:
    """Only the asker withdraws (else 403); an ended ask is 409."""
    if member.member_id != ask.asker_member_id:
        raise FamilyGroupError(403, "Only the member who asked can withdraw")
    if ask.state != OPEN:
        raise FamilyGroupError(409, ALREADY_ENDED)


def accept(session: Session, ask: HelperAskRow, member: GroupMemberRow) -> None:
    """The asked member says yes; the asker is told. The caller then adds them as the helper and
    records `helper_joined`, as "I'll go" does."""
    check_can_answer(ask, member)
    now = _utcnow()
    if not _end(session, ask, HelperAskState.ACCEPTED, by=member.member_id, at=now):
        raise FamilyGroupError(409, ALREADY_ENDED)
    _notify(
        session,
        ask,
        NotificationKind.ASK_ACCEPTED,
        [ask.asker_member_id],
        actor_member_id=member.member_id,
        at=now,
    )


def decline(
    session: Session, ask: HelperAskRow, member: GroupMemberRow, appointment: AppointmentRow
) -> None:
    """The asked member says no: the day needs a helper again, the asker is told, and the feed
    says so (`helper_declined`)."""
    check_can_answer(ask, member)
    now = _utcnow()
    if not _end(session, ask, HelperAskState.DECLINED, by=member.member_id, at=now):
        raise FamilyGroupError(409, ALREADY_ENDED)
    _notify(
        session,
        ask,
        NotificationKind.ASK_DECLINED,
        [ask.asker_member_id],
        actor_member_id=member.member_id,
        at=now,
    )
    record(
        session,
        group_id=ask.group_id,
        actor_member_id=member.member_id,
        kind=FamilyActivityKind.HELPER_DECLINED,
        appointment=appointment,
        day=ask.on_date,
        at=now,
    )


def withdraw(session: Session, ask: HelperAskRow, member: GroupMemberRow) -> None:
    """The asker takes the ask back; the asked member is told. Nothing in the feed."""
    check_can_withdraw(ask, member)
    now = _utcnow()
    if not _end(session, ask, HelperAskState.WITHDRAWN, by=member.member_id, at=now):
        raise FamilyGroupError(409, ALREADY_ENDED)
    _notify(
        session,
        ask,
        NotificationKind.ASK_WITHDRAWN,
        [ask.asked_member_id],
        actor_member_id=member.member_id,
        at=now,
    )


# ── Hooks from the calendar's public methods ─────────────────────────────────


def on_volunteer(
    session: Session,
    member: GroupMemberRow,
    appointment: AppointmentRow,
    day: date,
    occurs: Occurs,
) -> None:
    """ "I'll go" ends the day's open ask: `accepted` when the volunteer is the asked member (the
    asker is told), otherwise `closed` (the asker and the asked member are told, minus whoever
    volunteered). An ask whose day has started lapses first instead."""
    lapse_due(session, [appointment.group_id], occurs)
    ask = open_ask(session, appointment.appointment_id, day)
    if ask is None:
        return
    now = _utcnow()
    if member.member_id == ask.asked_member_id:
        if _end(session, ask, HelperAskState.ACCEPTED, by=member.member_id, at=now):
            _notify(
                session,
                ask,
                NotificationKind.ASK_ACCEPTED,
                [ask.asker_member_id],
                actor_member_id=member.member_id,
                at=now,
            )
    elif _end(session, ask, HelperAskState.CLOSED, by=member.member_id, at=now):
        _notify(
            session,
            ask,
            NotificationKind.ASK_CLOSED,
            [ask.asker_member_id, ask.asked_member_id],
            actor_member_id=member.member_id,
            at=now,
        )


def withdraw_for_appointment(
    session: Session,
    appointment: AppointmentRow,
    actor_member_id: str,
    occurs: Occurs | None = None,
) -> None:
    """The appointment, or some of its days, are gone: every open ask on it (with `occurs`, every
    one whose day it no longer has) is `withdrawn`, and the asked member is told unless they made
    the change."""
    now = _utcnow()
    for ask in session.scalars(
        select(HelperAskRow).where(
            HelperAskRow.appointment_id == appointment.appointment_id,
            HelperAskRow.state == OPEN,
        )
    ).all():
        if occurs is not None and occurs(appointment, ask.on_date):
            continue
        if _end(session, ask, HelperAskState.WITHDRAWN, by=actor_member_id, at=now):
            _notify(
                session,
                ask,
                NotificationKind.ASK_WITHDRAWN,
                [ask.asked_member_id],
                actor_member_id=actor_member_id,
                at=now,
            )


# ── Notifications ────────────────────────────────────────────────────────────


def _member_ids(memberships: Sequence[GroupMemberRow]) -> list[str]:
    return [member.member_id for member in memberships]


def notifications_page(
    session: Session,
    memberships: Sequence[GroupMemberRow],
    *,
    limit: int,
    before: str | None,
    occurs: Occurs,
) -> NotificationPage:
    """The newest `limit` notifications to any of `memberships` (keyset on `(created_at,
    notification_id)`, descending), after `before` when given. Raises `UnknownCursorError` for a
    cursor that is not one of them. Call `lapse_due` first."""
    member_ids = _member_ids(memberships)
    if before is not None:
        cursor = session.get(NotificationRow, before)
        if cursor is None or cursor.recipient_member_id not in member_ids:
            raise UnknownCursorError(before)
    if not member_ids:
        return NotificationPage(items=[], unread_count=0, next_before=None)
    query = select(NotificationRow).where(NotificationRow.recipient_member_id.in_(member_ids))
    if before is not None:
        at = aware(cursor.created_at)
        query = query.where(
            or_(
                NotificationRow.created_at < at,
                and_(
                    NotificationRow.created_at == at,
                    NotificationRow.notification_id < cursor.notification_id,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(
                NotificationRow.created_at.desc(), NotificationRow.notification_id.desc()
            ).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    unread = session.scalar(
        select(func.count())
        .select_from(NotificationRow)
        .where(
            NotificationRow.recipient_member_id.in_(member_ids),
            NotificationRow.read_at.is_(None),
        )
    )
    return NotificationPage(
        items=_notifications_out(session, rows, occurs),
        unread_count=unread or 0,
        next_before=rows[-1].notification_id if more else None,
    )


def _notifications_out(
    session: Session, rows: Sequence[NotificationRow], occurs: Occurs
) -> list[NotificationItem]:
    """Notification items with a fixed number of reads in all, however many rows."""
    if not rows:
        return []
    asks = {
        ask.ask_id: ask
        for ask in session.scalars(
            select(HelperAskRow).where(HelperAskRow.ask_id.in_({row.ask_id for row in rows}))
        )
    }
    appointments = {
        appointment.appointment_id: appointment
        for appointment in session.scalars(
            select(AppointmentRow).where(
                AppointmentRow.appointment_id.in_({ask.appointment_id for ask in asks.values()})
            )
        )
    }
    names = _names(
        session,
        [
            member_id
            for ask in asks.values()
            for member_id in (ask.asker_member_id, ask.asked_member_id, ask.ended_by_member_id)
            if member_id
        ],
    )
    labels: dict[str, str] = {}
    for group, person in session.execute(
        select(CareGroupRow, PersonRow)
        .outerjoin(PersonRow, PersonRow.person_id == CareGroupRow.person_id)
        .where(CareGroupRow.group_id.in_({row.group_id for row in rows}))
    ):
        labels[group.group_id] = senior_name_of(group, person)
    out: list[NotificationItem] = []
    for row in rows:
        ask = asks[row.ask_id]
        appointment = appointments.get(ask.appointment_id)
        live = appointment is not None and occurs(appointment, ask.on_date)
        out.append(
            NotificationItem(
                notification_id=row.notification_id,
                kind=NotificationKind(row.kind),
                created_at=aware(row.created_at),
                read=row.read_at is not None,
                group_id=row.group_id,
                group_label=labels.get(row.group_id, ""),
                ask_id=ask.ask_id,
                ask_state=HelperAskState(ask.state),
                occurrence_id=(occurrence_id(ask.appointment_id, ask.on_date) if live else None),
                appointment_title=appointment.title if appointment else ask.appointment_title,
                on_date=ask.on_date,
                start=appointment.start_time if live and appointment else None,
                asker_name=names.get(ask.asker_member_id, FALLBACK_NAME),
                asked_name=names.get(ask.asked_member_id, FALLBACK_NAME),
                ended_by_name=(
                    names.get(ask.ended_by_member_id, FALLBACK_NAME)
                    if ask.ended_by_member_id
                    else None
                ),
                is_open_for_me=(
                    ask.state == OPEN and row.recipient_member_id == ask.asked_member_id
                ),
            )
        )
    return out


def mark_read(
    session: Session,
    memberships: Sequence[GroupMemberRow],
    notification_ids: Sequence[str],
    *,
    everything: bool,
) -> None:
    """Mark the caller's own unread notifications read: the ones named, or all. Ids that are not
    the caller's are ignored."""
    member_ids = _member_ids(memberships)
    if not member_ids:
        return
    query = (
        update(NotificationRow)
        .where(
            NotificationRow.recipient_member_id.in_(member_ids),
            NotificationRow.read_at.is_(None),
        )
        .values(read_at=_utcnow())
        .execution_options(synchronize_session=False)
    )
    if not everything:
        query = query.where(NotificationRow.notification_id.in_(list(notification_ids)))
    session.execute(query)


# ── Offline demo ─────────────────────────────────────────────────────────────


def delete_for_groups(session: Session, group_ids: Collection[str]) -> None:
    """The demo reset: every notification and ask of these groups, notifications first (they point
    at the asks)."""
    ids = list(group_ids)
    if not ids:
        return
    session.execute(delete(NotificationRow).where(NotificationRow.group_id.in_(ids)))
    session.execute(delete(HelperAskRow).where(HelperAskRow.group_id.in_(ids)))


def delete_for_members(session: Session, member_ids: Collection[str]) -> None:
    """The demo reset, before these memberships are deleted: the asks that involve them (as asker,
    asked member or whoever ended it), the notifications about those asks, and any notification to
    them."""
    ids = list(member_ids)
    if not ids:
        return
    ask_ids = list(
        session.scalars(
            select(HelperAskRow.ask_id).where(
                or_(
                    HelperAskRow.asker_member_id.in_(ids),
                    HelperAskRow.asked_member_id.in_(ids),
                    HelperAskRow.ended_by_member_id.in_(ids),
                )
            )
        )
    )
    session.execute(
        delete(NotificationRow).where(
            or_(
                NotificationRow.recipient_member_id.in_(ids),
                NotificationRow.ask_id.in_(ask_ids),
            )
        )
    )
    if ask_ids:
        session.execute(delete(HelperAskRow).where(HelperAskRow.ask_id.in_(ask_ids)))
