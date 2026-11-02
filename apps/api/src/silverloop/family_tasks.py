"""Tasks: a one-off, daily or weekly reminder for the senior, kept by their family group and
ticked done day by day. Mirrors the browser's `lib/tasks.ts`, so both agree on a task's days.

* A task belongs to the family group, so it exists before the senior is linked.
* A repeating task is stored once; its days are worked out on read. "Weekly" is every seven days
  from `start_date`. `repeat_until` is inclusive.
* A tick is one day of a task ticked done (one row per task and day); un-ticking deletes it. A
  future day cannot be ticked. Through the senior's route only today can be; through the group's
  route an active member can also tick a past day.
* Editing changes the whole schedule and keeps every tick; a tick that is no longer one of the
  task's days is kept but not returned. Deleting removes the task and all its ticks.
* Any active member adds, changes or deletes tasks; anyone else gets 404, as for the group itself.

Nothing here writes to the family activity feed, and nothing in `advance`, the policy, review cases
or outreach reads a task: a missed tick triggers nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from silverloop.db_models import AccountRow, CareGroupRow, GroupMemberRow, TaskRow, TaskTickRow
from silverloop.family_groups import FamilyGroupError
from silverloop.models import (
    MemberStatus,
    Task,
    TaskKind,
    TaskList,
    TaskRepeat,
    TaskRequest,
    TaskTick,
)

MAX_RANGE_DAYS = 400


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def occurs_on(row: TaskRow, day: date) -> bool:
    """Whether `row` happens on `day` (the same rule as `occursOn` in `lib/tasks.ts`)."""
    if day < row.start_date:
        return False
    if row.repeat == TaskRepeat.NONE:
        return day == row.start_date
    if row.repeat_until is not None and day > row.repeat_until:
        return False
    return row.repeat == TaskRepeat.DAILY or (day - row.start_date).days % 7 == 0


def _apply(row: TaskRow, body: TaskRequest) -> None:
    row.title = body.title.strip()
    row.kind = body.kind.value
    row.start_date = body.start_date
    row.time = body.time
    row.repeat = body.repeat.value
    # A one-off task has no last day.
    row.repeat_until = body.repeat_until if body.repeat != TaskRepeat.NONE else None
    row.notes = body.notes.strip()


class FamilyTaskStore:
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

    @staticmethod
    def _task(session: Session, group_id: str, task_id: str) -> TaskRow:
        row = session.get(TaskRow, task_id)
        if row is None or row.group_id != group_id:
            raise FamilyGroupError(404, "Task not found")
        return row

    # ── Reading ──────────────────────────────────────────────────────────────

    @staticmethod
    def _check_range(lo: date, hi: date) -> None:
        if hi < lo or (hi - lo).days > MAX_RANGE_DAYS:
            raise FamilyGroupError(422, f"Ask for at most {MAX_RANGE_DAYS} days at a time.")

    def person_tasks(self, person_id: str, lo: date, hi: date) -> TaskList:
        """The tasks of the senior `person_id`: their family group's, or none when they have no
        group yet. Who may read them is checked by the route."""
        self._check_range(lo, hi)
        with self.sessions() as session:
            group = session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == person_id))
            if group is None:
                return TaskList(
                    person_id=person_id,
                    group_id=None,
                    from_date=lo,
                    to_date=hi,
                    tasks=[],
                    ticks=[],
                )
            return self._list(session, group, lo, hi)

    def group_tasks(self, sub: str, group_id: str, lo: date, hi: date) -> TaskList:
        """The family group's tasks, whether or not its senior is linked yet. Active members
        only."""
        self._check_range(lo, hi)
        with self.sessions() as session:
            self._active_member(session, sub, group_id)
            group = session.get(CareGroupRow, group_id)
            if group is None:  # pragma: no cover - membership implies the group
                raise FamilyGroupError(404, "Group not found")
            return self._list(session, group, lo, hi)

    @staticmethod
    def _list(session: Session, group: CareGroupRow, lo: date, hi: date) -> TaskList:
        rows = session.scalars(
            select(TaskRow)
            .where(TaskRow.group_id == group.group_id)
            .order_by(TaskRow.time, TaskRow.created_at)
        ).all()
        by_id = {row.task_id: row for row in rows}
        tick_rows = session.scalars(
            select(TaskTickRow)
            .where(
                TaskTickRow.group_id == group.group_id,
                TaskTickRow.day >= lo,
                TaskTickRow.day <= hi,
            )
            .order_by(TaskTickRow.day)
        ).all()
        # A tick left behind by an edit (no longer one of the task's days) is kept, not shown.
        ticks = [
            tick
            for tick in tick_rows
            if tick.task_id in by_id and occurs_on(by_id[tick.task_id], tick.day)
        ]
        subs = {row.created_by for row in rows} | {tick.done_by for tick in ticks}
        names = (
            dict(
                session.execute(
                    select(AccountRow.sub, AccountRow.display_name).where(AccountRow.sub.in_(subs))
                ).all()
            )
            if subs
            else {}
        )
        return TaskList(
            person_id=group.person_id,
            group_id=group.group_id,
            from_date=lo,
            to_date=hi,
            tasks=[_task_out(row, names.get(row.created_by)) for row in rows],
            ticks=[
                TaskTick(
                    task_id=tick.task_id,
                    day=tick.day,
                    done_by_name=names.get(tick.done_by),
                    done_at=tick.done_at,
                )
                for tick in ticks
            ],
        )

    # ── Adding, changing and deleting ────────────────────────────────────────

    def create_task(self, sub: str, group_id: str, body: TaskRequest) -> Task:
        with self.sessions.begin() as session:
            self._active_member(session, sub, group_id)
            now = _utcnow()
            row = TaskRow(
                task_id=_id("task"),
                group_id=group_id,
                created_by=sub,
                created_at=now,
                updated_at=now,
            )
            _apply(row, body)
            session.add(row)
            session.flush()
            return _task_out(row, _name(session, sub))

    def update_task(self, sub: str, group_id: str, task_id: str, body: TaskRequest) -> Task:
        """Change the whole schedule. Ticks stay; the last write wins."""
        with self.sessions.begin() as session:
            self._active_member(session, sub, group_id)
            row = self._task(session, group_id, task_id)
            _apply(row, body)
            row.updated_at = _utcnow()
            session.flush()
            return _task_out(row, _name(session, row.created_by))

    def delete_task(self, sub: str, group_id: str, task_id: str) -> None:
        """Remove the task, every day of it, and all its ticks."""
        with self.sessions.begin() as session:
            self._active_member(session, sub, group_id)
            row = self._task(session, group_id, task_id)
            session.execute(delete(TaskTickRow).where(TaskTickRow.task_id == row.task_id))
            session.delete(row)

    # ── Ticking a day done ───────────────────────────────────────────────────

    def set_group_day(
        self, sub: str, group_id: str, task_id: str, day: date, done: bool, today: date
    ) -> None:
        """An active member ticks (or un-ticks) today or a past day."""
        with self.sessions.begin() as session:
            self._active_member(session, sub, group_id)
            self._set_day(session, sub, group_id, task_id, day, done, today)

    def set_person_day(
        self, sub: str, person_id: str, task_id: str, day: date, done: bool, today: date
    ) -> None:
        """The senior's route: today only. Who may use it is checked by the route."""
        if day != today:
            raise FamilyGroupError(422, "Only today's tasks can be ticked off here.")
        with self.sessions.begin() as session:
            group = session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == person_id))
            if group is None:
                raise FamilyGroupError(404, "Task not found")
            self._set_day(session, sub, group.group_id, task_id, day, done, today)

    def _set_day(
        self,
        session: Session,
        sub: str,
        group_id: str,
        task_id: str,
        day: date,
        done: bool,
        today: date,
    ) -> None:
        row = self._task(session, group_id, task_id)
        if day > today:
            raise FamilyGroupError(422, "A task cannot be ticked off before its day.")
        if not occurs_on(row, day):
            raise FamilyGroupError(422, "That task is not on that day.")
        tick = session.scalar(
            select(TaskTickRow).where(TaskTickRow.task_id == task_id, TaskTickRow.day == day)
        )
        if done and tick is None:
            session.add(
                TaskTickRow(
                    tick_id=_id("tick"),
                    group_id=group_id,
                    task_id=task_id,
                    day=day,
                    done_by=sub,
                    done_at=_utcnow(),
                )
            )
        elif not done and tick is not None:
            session.delete(tick)

    # ── The demo ─────────────────────────────────────────────────────────────

    @staticmethod
    def delete_for_groups(session: Session, group_ids: list[str]) -> None:
        """Every task and tick of these groups, for the demo reset (ticks first)."""
        session.execute(delete(TaskTickRow).where(TaskTickRow.group_id.in_(group_ids)))
        session.execute(delete(TaskRow).where(TaskRow.group_id.in_(group_ids)))


# The demo senior's sample checklist (made up, as `lib/daily-tasks.ts` held it in the browser),
# every day from the reset day. Care+ never suggests a medicine, dose or time.
DEMO_TASKS: list[tuple[str, str, TaskKind, str, str]] = [
    ("task-bp-morning", "Blood pressure tablet", TaskKind.MEDICINE, "08:00", "With breakfast"),
    ("task-vitamin", "Vitamin D supplement", TaskKind.MEDICINE, "08:00", ""),
    ("task-water", "Drink a glass of water", TaskKind.TASK, "10:00", ""),
    ("task-stretch", "Light stretching", TaskKind.TASK, "17:00", ""),
    ("task-bp-evening", "Blood pressure tablet", TaskKind.MEDICINE, "20:00", "After dinner"),
]


def seed_demo_tasks(session: Session, group_id: str, today: date, created_by: str) -> None:
    now = _utcnow()
    for index, (key, title, kind, time, notes) in enumerate(DEMO_TASKS):
        session.add(
            TaskRow(
                task_id=key,  # one demo group, so the demo ids can stay readable
                group_id=group_id,
                title=title,
                kind=kind.value,
                start_date=today,
                time=time,
                repeat=TaskRepeat.DAILY.value,
                repeat_until=None,
                notes=notes,
                created_by=created_by,
                # Apart, so tasks at the same time keep this order.
                created_at=now + timedelta(microseconds=index),
                updated_at=now,
            )
        )


def _name(session: Session, sub: str) -> str | None:
    account = session.get(AccountRow, sub)
    return account.display_name if account else None


def _task_out(row: TaskRow, added_by_name: str | None) -> Task:
    return Task(
        task_id=row.task_id,
        title=row.title,
        kind=TaskKind(row.kind),
        start_date=row.start_date,
        time=row.time,
        repeat=TaskRepeat(row.repeat),
        repeat_until=row.repeat_until,
        notes=row.notes,
        added_by_name=added_by_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
