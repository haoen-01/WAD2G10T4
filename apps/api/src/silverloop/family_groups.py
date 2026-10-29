"""Family groups: family members caring for one senior, joined with 6-digit PINs.

The flow (ADR 0010):

1. Someone signs up and chooses `senior` or `family` (`onboard`). A senior gets their own person
   record with synthetic activity data, labelled synthetic, since no real device is connected.
2. A family member creates the family group with the senior's name and becomes its owner
   (`create_group`). Until the senior is linked the group has no `person_id` and sees nothing
   about the senior; members, the join PIN and the shared calendar already work.
3. The senior shows a **senior-link PIN** on their own screen (`create_link_pin`). It lasts 10
   minutes and works once. An active member entering it links the senior to their group
   (`link_senior`), or creates the group already linked (`create_group` with the PIN). Showing the
   PIN is the senior's agreement to be linked, which is why a senior can only be linked this way.
   A senior belongs to one family group.
4. Any active member can show a **join PIN** (`create_join_pin`, 7 days, reusable). Someone who
   enters it waits as `pending` until an active member approves them (`approve` / `decline`).

A 6-digit PIN has only a million values, so it is never the only protection: PINs expire, a wrong
PIN counts against the account (5 in 15 minutes locks PIN entry), and joining needs approval.
PINs are stored as SHA-256 hashes so the plain PIN is never kept; with so few values the hash
alone would not stop someone who could read the table, which only the API can.

This module owns every read and write of the family tables; FastAPI routes call it.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from silverloop.db_models import (
    AccountRow,
    CareGroupRow,
    FamilyPinRow,
    GroupMemberRow,
    PersonRow,
    PinAttemptRow,
)
from silverloop.family_activity import record
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    AccountRole,
    AuthRole,
    CareGroup,
    FamilyActivityKind,
    GroupMember,
    GroupRole,
    MemberStatus,
    MeResponse,
    MyGroup,
    PinResponse,
)
from silverloop.repository import SilverLoopRepository

SENIOR_NAME_MAX = 80

SENIOR_LINK = "senior_link"
GROUP_JOIN = "group_join"
# Long enough for an older person to read the code out and a family member to type it in.
SENIOR_LINK_TTL = timedelta(minutes=10)
GROUP_JOIN_TTL = timedelta(days=7)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW = timedelta(minutes=15)

# Who the API treats as signed in when sign-in is off (the offline demo and the e2e run). The demo
# family (Sarah, who owns Mdm Lim's group, John and Emily) and Mdm Lim herself; see
# `ensure_demo_group` and `FamilyCalendarStore.reset_demo`.
DEMO_FAMILY_SUB = "demo-family"
DEMO_JOHN_SUB = "demo-john"
DEMO_EMILY_SUB = "demo-emily"
DEMO_SENIOR_SUB = "demo-senior"
# Owner first. Sub -> (display name, relationship).
DEMO_FAMILY: dict[str, tuple[str, str]] = {
    DEMO_FAMILY_SUB: ("Sarah", "Daughter"),
    DEMO_JOHN_SUB: ("John", "Son"),
    DEMO_EMILY_SUB: ("Emily", "Granddaughter"),
}


class FamilyGroupError(Exception):
    """A request the family rules refuse. `status_code` is the HTTP status the route returns."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; everything stored here is UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _hash_pin(purpose: str, pin: str) -> str:
    return hashlib.sha256(f"{purpose}:{pin}".encode()).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def senior_name_of(group: CareGroupRow, person: PersonRow | None) -> str:
    """The name responses show: the senior's own account name once linked, else the typed one."""
    return person.display_name if person is not None else group.senior_name


_ALREADY_HAS_GROUP = (
    "This senior already has a family group. Ask one of its members for the join PIN."
)
_ALREADY_LINKED = "This family group already has a senior."
_BAD_PIN = "That PIN is not right, or it has expired."


class FamilyGroups:
    def __init__(self, sessions: sessionmaker[Session], repository: SilverLoopRepository) -> None:
        self.sessions = sessions
        self.repository = repository

    # ── Accounts ──────────────────────────────────────────────────────────────

    def account_role(self, sub: str) -> AuthRole | None:
        with self.sessions() as session:
            row = session.get(AccountRow, sub)
            return AuthRole(row.role) if row else None

    def onboard(
        self, sub: str, token_role: AuthRole | None, role: AccountRole, display_name: str
    ) -> MeResponse:
        name = display_name.strip()
        if not name:
            raise FamilyGroupError(422, "Please enter your name.")
        if token_role is not None or self.account_role(sub) is not None:
            raise FamilyGroupError(409, "This account is already set up.")
        person_id: str | None = None
        if role is AccountRole.SENIOR:
            # Synthetic history, labelled as such by the adapter: no real device is connected yet.
            person_id = f"person-{uuid4().hex[:12]}"
            self.repository.reset(person_id=person_id, allow_new_person=True)
        try:
            with self.sessions.begin() as session:
                session.add(
                    AccountRow(sub=sub, role=role.value, display_name=name, created_at=_utcnow())
                )
                if person_id is not None:
                    person = session.get(PersonRow, person_id)
                    if person is not None:
                        person.display_name = name
        except IntegrityError as exc:
            raise FamilyGroupError(409, "This account is already set up.") from exc
        if person_id is not None:
            self.repository.upsert_person_link(sub, person_id, "self_onboarding")
        return self.me(sub, AuthRole(role.value), person_id)

    def me(self, sub: str, role: AuthRole | None, person_id: str | None) -> MeResponse:
        with self.sessions() as session:
            account = session.get(AccountRow, sub)
            rows = session.execute(
                select(GroupMemberRow, CareGroupRow, PersonRow)
                .join(CareGroupRow, CareGroupRow.group_id == GroupMemberRow.group_id)
                # Outer: a group with no senior linked yet is listed too.
                .outerjoin(PersonRow, PersonRow.person_id == CareGroupRow.person_id)
                .where(GroupMemberRow.sub == sub)
                .order_by(GroupMemberRow.created_at)
            ).all()
            display_name = account.display_name if account else None
            if display_name is None and person_id is not None:
                person = session.get(PersonRow, person_id)
                display_name = person.display_name if person else None
        resolved = role or (AuthRole(account.role) if account else None)
        return MeResponse(
            sub=sub,
            role=resolved,
            display_name=display_name,
            person_id=person_id,
            needs_onboarding=resolved is None,
            groups=[
                MyGroup(
                    group_id=group.group_id,
                    person_id=group.person_id,
                    senior_name=senior_name_of(group, person),
                    my_role=GroupRole(member.role),
                    my_status=MemberStatus(member.status),
                )
                for member, group, person in rows
            ],
        )

    # ── PINs ──────────────────────────────────────────────────────────────────

    def _issue_pin(
        self,
        session: Session,
        *,
        purpose: str,
        created_by: str,
        ttl: timedelta,
        person_id: str | None = None,
        group_id: str | None = None,
    ) -> PinResponse:
        now = _utcnow()
        # One live PIN per senior / per group: a new one replaces the old. Expired and used PINs
        # of this kind are cleared too, which also frees their hashes for reuse.
        target = (
            FamilyPinRow.person_id == person_id
            if person_id is not None
            else FamilyPinRow.group_id == group_id
        )
        session.execute(
            delete(FamilyPinRow).where(
                FamilyPinRow.purpose == purpose,
                or_(target, FamilyPinRow.expires_at <= now, FamilyPinRow.used_at.is_not(None)),
            )
        )
        for _ in range(50):
            pin = f"{secrets.randbelow(1_000_000):06d}"
            pin_hash = _hash_pin(purpose, pin)
            taken = session.scalar(
                select(FamilyPinRow.pin_id).where(
                    FamilyPinRow.purpose == purpose, FamilyPinRow.pin_hash == pin_hash
                )
            )
            if taken is None:
                break
        else:  # pragma: no cover - a million values, a handful live
            raise FamilyGroupError(503, "Could not make a new PIN. Please try again.")
        expires_at = now + ttl
        session.add(
            FamilyPinRow(
                pin_id=_id("pin"),
                purpose=purpose,
                pin_hash=pin_hash,
                person_id=person_id,
                group_id=group_id,
                created_by=created_by,
                created_at=now,
                expires_at=expires_at,
            )
        )
        return PinResponse(pin=pin, expires_at=expires_at)

    def _redeem_pin(self, sub: str, purpose: str, pin: str) -> FamilyPinRow:
        """The live PIN matching `pin`, recording the attempt either way. Raises when the account
        is locked out or the PIN does not match."""
        now = _utcnow()
        with self.sessions.begin() as session:
            # Attempts only count for the lockout window, so older ones are not kept.
            session.execute(
                delete(PinAttemptRow).where(PinAttemptRow.attempted_at <= now - LOCKOUT_WINDOW)
            )
            failures = session.scalar(
                select(func.count())
                .select_from(PinAttemptRow)
                .where(
                    PinAttemptRow.sub == sub,
                    PinAttemptRow.succeeded.is_(False),
                    PinAttemptRow.attempted_at > now - LOCKOUT_WINDOW,
                )
            )
            if (failures or 0) >= MAX_FAILED_ATTEMPTS:
                locked = True
                row = None
            else:
                locked = False
                row = session.scalar(
                    select(FamilyPinRow).where(
                        FamilyPinRow.purpose == purpose,
                        FamilyPinRow.pin_hash == _hash_pin(purpose, pin),
                        FamilyPinRow.expires_at > now,
                        FamilyPinRow.used_at.is_(None),
                    )
                )
                session.add(PinAttemptRow(sub=sub, succeeded=row is not None, attempted_at=now))
        if locked:
            raise FamilyGroupError(
                429, "Too many wrong PINs. Please wait 15 minutes, then try again."
            )
        if row is None:
            raise FamilyGroupError(400, "That PIN is not right, or it has expired.")
        return row

    def create_link_pin(self, sub: str, person_id: str) -> PinResponse:
        with self.sessions.begin() as session:
            return self._issue_pin(
                session,
                purpose=SENIOR_LINK,
                created_by=sub,
                ttl=SENIOR_LINK_TTL,
                person_id=person_id,
            )

    # ── Groups ────────────────────────────────────────────────────────────────

    def create_group(
        self,
        sub: str,
        relationship: str,
        *,
        senior_name: str | None = None,
        senior_pin: str | None = None,
    ) -> CareGroup:
        """A new family group owned by the caller. With `senior_pin` (the PIN on the senior's
        screen) the senior is linked at once and their own account name wins; with only
        `senior_name` the group starts with no senior linked."""
        pin_row = self._redeem_pin(sub, SENIOR_LINK, senior_pin) if senior_pin is not None else None
        person_id = pin_row.person_id if pin_row is not None else None
        if pin_row is not None and person_id is None:  # pragma: no cover - always names a person
            raise FamilyGroupError(400, _BAD_PIN)
        typed = (senior_name or "").strip()[:SENIOR_NAME_MAX]
        if pin_row is None and not typed:  # the request model already refuses this
            raise FamilyGroupError(422, "Enter the senior's name, or the PIN on their screen.")
        now = _utcnow()
        group_id = _id("grp")
        try:
            with self.sessions.begin() as session:
                if pin_row is not None:
                    if session.scalar(
                        select(CareGroupRow).where(CareGroupRow.person_id == person_id)
                    ):
                        raise FamilyGroupError(409, _ALREADY_HAS_GROUP)
                    stored = session.get(FamilyPinRow, pin_row.pin_id)
                    if stored is None or stored.used_at is not None:
                        raise FamilyGroupError(400, _BAD_PIN)
                    stored.used_at = now
                    person = session.get(PersonRow, person_id)
                    if person is not None:
                        # Only the read-through name is ever shown; this keeps the column honest.
                        typed = person.display_name[:SENIOR_NAME_MAX]
                session.add(
                    CareGroupRow(
                        group_id=group_id,
                        person_id=person_id,
                        senior_name=typed,
                        linked_via="senior_link_pin" if person_id is not None else None,
                        linked_at=now if person_id is not None else None,
                        linked_by=sub if person_id is not None else None,
                        created_by=sub,
                        created_at=now,
                    )
                )
                session.flush()
                owner_id = _id("mem")
                session.add(
                    GroupMemberRow(
                        member_id=owner_id,
                        group_id=group_id,
                        sub=sub,
                        relationship=relationship.strip(),
                        role=GroupRole.OWNER.value,
                        status=MemberStatus.ACTIVE.value,
                        created_at=now,
                        approved_by=sub,
                        approved_at=now,
                    )
                )
                session.flush()  # the member row first: the feed entry points at it
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=owner_id,
                    kind=FamilyActivityKind.GROUP_CREATED,
                    at=now,
                )
        except IntegrityError as exc:
            # Two family members redeeming PINs for the same senior at once.
            raise FamilyGroupError(409, "This senior already has a family group.") from exc
        return self.group(sub, group_id)

    def link_senior(self, sub: str, group_id: str, senior_pin: str) -> CareGroup:
        """Link the senior whose PIN this is to a group that has none yet. Any active member may.

        Membership is checked before the PIN is looked at, so someone outside the group cannot use
        this to try PINs. A wrong PIN counts toward the lockout (`_redeem_pin` commits the attempt
        on its own). Every refusal after that is raised inside the one transaction, so the PIN is
        only used up when the link is made."""
        with self.sessions() as session:
            self._require_active_member(session, sub, group_id)
        pin_row = self._redeem_pin(sub, SENIOR_LINK, senior_pin)
        person_id = pin_row.person_id
        if person_id is None:  # pragma: no cover - a senior-link PIN always names a person
            raise FamilyGroupError(400, _BAD_PIN)
        now = _utcnow()
        try:
            with self.sessions.begin() as session:
                member = self._require_active_member(session, sub, group_id)
                # Never says which group: that is not the caller's to know.
                if session.scalar(
                    select(CareGroupRow.group_id).where(CareGroupRow.person_id == person_id)
                ):
                    raise FamilyGroupError(409, _ALREADY_HAS_GROUP)
                linked = session.execute(
                    update(CareGroupRow)
                    .where(CareGroupRow.group_id == group_id, CareGroupRow.person_id.is_(None))
                    .values(
                        person_id=person_id,
                        linked_via="senior_link_pin",
                        linked_at=now,
                        linked_by=sub,
                    )
                ).rowcount
                if linked != 1:
                    raise FamilyGroupError(409, _ALREADY_LINKED)
                used = session.execute(
                    update(FamilyPinRow)
                    .where(FamilyPinRow.pin_id == pin_row.pin_id, FamilyPinRow.used_at.is_(None))
                    .values(used_at=now)
                ).rowcount
                if used != 1:
                    raise FamilyGroupError(400, _BAD_PIN)
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=member.member_id,
                    kind=FamilyActivityKind.SENIOR_LINKED,
                    at=now,
                )
        except IntegrityError as exc:
            # Two groups linking the same senior at once: the unique `person_id` lets one win.
            raise FamilyGroupError(409, _ALREADY_HAS_GROUP) from exc
        return self.group(sub, group_id)

    def rename_senior(self, sub: str, group_id: str, senior_name: str) -> CareGroup:
        """Fix the typed name while no senior is linked. Once linked the name is the senior's own,
        so changing it here is refused."""
        name = senior_name.strip()[:SENIOR_NAME_MAX]
        if not name:  # the request model already refuses this
            raise FamilyGroupError(422, "Please enter the senior's name.")
        with self.sessions.begin() as session:
            member = self._require_active_member(session, sub, group_id)
            group = session.get(CareGroupRow, group_id)
            if group is None:  # pragma: no cover - membership implies the group
                raise FamilyGroupError(404, "Group not found")
            if group.person_id is not None:
                person = session.get(PersonRow, group.person_id)
                raise FamilyGroupError(
                    409, f"The name now comes from {senior_name_of(group, person)}'s own account."
                )
            if group.senior_name != name:
                renamed = session.execute(
                    update(CareGroupRow)
                    .where(CareGroupRow.group_id == group_id, CareGroupRow.person_id.is_(None))
                    .values(senior_name=name)
                ).rowcount
                if renamed != 1:  # linked since it was read
                    raise FamilyGroupError(409, "The name now comes from the senior's own account.")
                record(
                    session,
                    group_id=group_id,
                    actor_member_id=member.member_id,
                    kind=FamilyActivityKind.SENIOR_RENAMED,
                )
        return self.group(sub, group_id)

    def join_group(self, sub: str, pin: str, relationship: str) -> MyGroup:
        pin_row = self._redeem_pin(sub, GROUP_JOIN, pin)
        group_id = pin_row.group_id
        if group_id is None:  # pragma: no cover - a join PIN always names a group
            raise FamilyGroupError(400, "That PIN is not right, or it has expired.")
        try:
            with self.sessions.begin() as session:
                existing = session.scalar(
                    select(GroupMemberRow).where(
                        GroupMemberRow.group_id == group_id, GroupMemberRow.sub == sub
                    )
                )
                if existing is not None:
                    raise FamilyGroupError(409, "You have already joined this group.")
                session.add(
                    GroupMemberRow(
                        member_id=_id("mem"),
                        group_id=group_id,
                        sub=sub,
                        relationship=relationship.strip(),
                        role=GroupRole.MEMBER.value,
                        status=MemberStatus.PENDING.value,
                        created_at=_utcnow(),
                    )
                )
                group = session.get(CareGroupRow, group_id)
                person = (
                    session.get(PersonRow, group.person_id)
                    if group is not None and group.person_id is not None
                    else None
                )
        except IntegrityError as exc:
            raise FamilyGroupError(409, "You have already joined this group.") from exc
        return MyGroup(
            group_id=group_id,
            person_id=group.person_id if group else None,
            senior_name=senior_name_of(group, person) if group else "",
            my_role=GroupRole.MEMBER,
            my_status=MemberStatus.PENDING,
        )

    def _require_active_member(self, session: Session, sub: str, group_id: str) -> GroupMemberRow:
        """The caller's membership. 404, not 403, for anyone who is not an active member: whether
        a group exists is not theirs to know."""
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

    def group(self, sub: str, group_id: str) -> CareGroup:
        with self.sessions() as session:
            self._require_active_member(session, sub, group_id)
            group = session.get(CareGroupRow, group_id)
            if group is None:  # pragma: no cover - membership implies the group
                raise FamilyGroupError(404, "Group not found")
            person = (
                session.get(PersonRow, group.person_id) if group.person_id is not None else None
            )
            rows = session.execute(
                select(GroupMemberRow, AccountRow)
                .outerjoin(AccountRow, AccountRow.sub == GroupMemberRow.sub)
                .where(GroupMemberRow.group_id == group_id)
                .order_by(GroupMemberRow.created_at)
            ).all()
        return CareGroup(
            group_id=group.group_id,
            person_id=group.person_id,
            senior_name=senior_name_of(group, person),
            members=[
                GroupMember(
                    member_id=member.member_id,
                    display_name=account.display_name if account else "Family member",
                    relationship=member.relationship,
                    role=GroupRole(member.role),
                    status=MemberStatus(member.status),
                    is_me=member.sub == sub,
                    joined_at=_aware(member.created_at),
                )
                for member, account in rows
            ],
        )

    def create_join_pin(self, sub: str, group_id: str) -> PinResponse:
        with self.sessions.begin() as session:
            self._require_active_member(session, sub, group_id)
            return self._issue_pin(
                session,
                purpose=GROUP_JOIN,
                created_by=sub,
                ttl=GROUP_JOIN_TTL,
                group_id=group_id,
            )

    def _pending_member(self, session: Session, group_id: str, member_id: str) -> GroupMemberRow:
        member = session.get(GroupMemberRow, member_id)
        if member is None or member.group_id != group_id:
            raise FamilyGroupError(404, "Member not found")
        if member.status != MemberStatus.PENDING.value:
            raise FamilyGroupError(409, "This person is already in the group.")
        return member

    def approve(self, sub: str, group_id: str, member_id: str) -> CareGroup:
        with self.sessions.begin() as session:
            approver = self._require_active_member(session, sub, group_id)
            member = self._pending_member(session, group_id, member_id)
            member.status = MemberStatus.ACTIVE.value
            member.approved_by = sub
            member.approved_at = _utcnow()
            record(
                session,
                group_id=group_id,
                actor_member_id=approver.member_id,
                kind=FamilyActivityKind.MEMBER_APPROVED,
                subject_member_id=member.member_id,
            )
        return self.group(sub, group_id)

    def decline(self, sub: str, group_id: str, member_id: str) -> CareGroup:
        with self.sessions.begin() as session:
            decliner = self._require_active_member(session, sub, group_id)
            session.delete(self._pending_member(session, group_id, member_id))
            # No subject and no name: someone who was turned away is not kept in the feed.
            record(
                session,
                group_id=group_id,
                actor_member_id=decliner.member_id,
                kind=FamilyActivityKind.MEMBER_DECLINED,
            )
        return self.group(sub, group_id)

    # ── Offline demo ──────────────────────────────────────────────────────────

    def ensure_demo_group(self) -> None:
        """Sign-in off only: the demo family's accounts, Mdm Lim's senior account, and her family
        group owned by Sarah, so the demo opens straight into a working family view. Idempotent;
        `FamilyCalendarStore.reset_demo` fills in the other members and the schedule."""
        with self.sessions.begin() as session:
            person = session.get(PersonRow, DEMO_PERSON_ID)
            if person is None:
                return
            accounts = {sub: (name, AccountRole.FAMILY) for sub, (name, _) in DEMO_FAMILY.items()}
            accounts[DEMO_SENIOR_SUB] = (person.display_name, AccountRole.SENIOR)
            for sub, (name, role) in accounts.items():
                if session.get(AccountRow, sub) is None:
                    session.add(
                        AccountRow(
                            sub=sub, role=role.value, display_name=name, created_at=_utcnow()
                        )
                    )
            if (
                session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == DEMO_PERSON_ID))
                is None
            ):
                now = _utcnow()
                session.add(
                    CareGroupRow(
                        group_id=_id("grp"),
                        person_id=DEMO_PERSON_ID,
                        senior_name=person.display_name[:SENIOR_NAME_MAX],
                        linked_via="demo_seed",
                        linked_at=now,
                        linked_by=DEMO_FAMILY_SUB,
                        created_by=DEMO_FAMILY_SUB,
                        created_at=now,
                    )
                )
        self.repository.upsert_person_link(DEMO_SENIOR_SUB, DEMO_PERSON_ID, "demo_seed")
