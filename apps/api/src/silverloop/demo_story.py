"""Admin command: put the signed-in demo into its starting state, for the real demo logins.

Usage:
    pnpm demo:story

The signed-in logins (`sarah`, `john`, `emily`, `weiming`, `aisha`, `senior`) are real Supabase
users, so the seeded `demo-*` members mean nothing to them. This plays Mdm Lim's two days through
the real `advance`, gives her family group to the real family, adds a second group for the made-up
Mr Tan, and reads the result back. It is not part of `pnpm demo:offline`.

Re-running gives the same end state. Everything about Mdm Lim and the people here is synthetic. The
story never sets a password or a role: `setup_demo_accounts` owns those.

Not atomic as a whole: `reset`, each `advance` and the outcome commit on their own, and all the
family group writes are one transaction. A failure part-way through Mdm Lim's run leaves her on a
newer, unfinished run with the groups as they were; a failure in the group transaction changes no
group. Running it again repairs both.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from silverloop.config import Settings
from silverloop.db_models import (
    AccountRow,
    AppointmentRow,
    AuthUserPersonLinkRow,
    CareGroupRow,
    FamilyPinRow,
    GroupMemberRow,
    HelperAssignmentRow,
    PersonRow,
)
from silverloop.family_activity import ORIGIN_DEMO_SEED, record
from silverloop.family_calendar import _DEMO_APPOINTMENTS, FamilyCalendarStore
from silverloop.family_groups import (
    DEMO_FAMILY,
    GROUP_JOIN,
    GROUP_JOIN_TTL,
    SENIOR_NAME_MAX,
    FamilyGroups,
    _id,
)
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.models import AccountRole, FamilyActivityKind, MemberStatus, OutcomeKind, RepeatRule
from silverloop.runtime import RuntimeConfigurationError, validate_runtime
from silverloop.setup_demo_accounts import _find_user_by_email, _supabase_admin
from silverloop.sql_repository import SqlAlchemyRepository

LOGINS = ("sarah", "john", "emily", "weiming", "aisha", "senior")
EMAIL_DOMAIN = "silverloop.demo"
FAMILY_LOGINS = tuple(login for login in LOGINS if login != "senior")

NUDGE_TITLE = "Five-minute movement option"
WAITING_TITLE = "Chair Mobility & Balance"
SECOND_SENIOR = "Mr Tan"

# Mdm Lim's family, then Mr Tan's. The owner comes first in each.
_LIM_FAMILY = {"sarah": "Daughter", "john": "Son", "emily": "Granddaughter"}
_TAN_FAMILY = {"sarah": "Niece", "weiming": "Son", "aisha": "Niece"}
_DAYS = ("demo-story-day-1", "demo-story-day-2")
_SEEDED_LIM_FEED_ENTRIES = 6


class StoryFailed(Exception):
    """The story could not finish, or finished in the wrong state. The message is safe to print."""


@dataclass(frozen=True)
class Landing:
    lim_group_id: str
    tan_group_id: str
    join_pin_expires_on: date


def _refuse(message: str) -> SystemExit:
    print(f"Error: {message}", file=sys.stderr)
    return SystemExit(1)


def _refuse_wrong_environment(settings: Settings) -> None:
    if settings.app_env == "production":
        raise _refuse(
            "refusing to run the demo story while APP_ENV=production. Nothing was changed."
        )
    if not settings.auth_enabled:
        raise _refuse(
            "the demo story is for the signed-in app, and AUTH_ENABLED=false. Nothing was changed. "
            "`pnpm demo:offline` sets up its own demo and does not need this command."
        )
    try:
        validate_runtime(settings)
    except RuntimeConfigurationError as exc:
        raise _refuse(f"{exc} Nothing was changed.") from exc


def _run_setup_first(what: str) -> SystemExit:
    return _refuse(
        f"{what}. Run `setup_demo_accounts` first (see docs/supabase.md). Nothing was changed."
    )


def _look_up_logins() -> dict[str, str]:
    """Each login's real sub, by its fixed address: seeded accounts share the display names."""
    supabase_url = os.environ.get("SUPABASE_URL", "")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not supabase_url or not secret_key:
        raise _refuse(
            "SUPABASE_URL and SUPABASE_SECRET_KEY must both be set. Nothing was changed. "
            "`pnpm demo:story` reads them from the repository's .env."
        )
    subs: dict[str, str] = {}
    missing: list[str] = []
    try:
        with _supabase_admin(supabase_url, secret_key) as admin:
            for login in LOGINS:
                user = _find_user_by_email(admin, f"{login}@{EMAIL_DOMAIN}")
                if user is None:
                    missing.append(login)
                    continue
                expected_role = "senior" if login == "senior" else None
                if (user.get("app_metadata") or {}).get("role") != expected_role:
                    raise _run_setup_first(f"The login `{login}` has the wrong role")
                subs[login] = user["id"]
    except httpx.HTTPError as exc:
        # The type alone: never a request, a URL or a header.
        raise _refuse(
            f"could not read the logins from Supabase ({type(exc).__name__}). Nothing was changed."
        ) from exc
    if missing:
        raise _run_setup_first(f"These logins are missing: {', '.join(missing)}")
    return subs


def _check_accounts(repository: SqlAlchemyRepository, subs: dict[str, str]) -> None:
    """The rows `setup_demo_accounts` writes. Without them a login would land on onboarding."""
    with repository.sessions() as session:
        for login in FAMILY_LOGINS:
            account = session.get(AccountRow, subs[login])
            if account is None or account.role != AccountRole.FAMILY.value:
                raise _run_setup_first(f"The login `{login}` has no family account")
        link = session.scalar(
            select(AuthUserPersonLinkRow.person_id).where(
                AuthUserPersonLinkRow.sub == subs["senior"]
            )
        )
    if link != DEMO_PERSON_ID:
        raise _run_setup_first("The login `senior` is not linked to Mdm Lim")


def _muted_labels(repository: SqlAlchemyRepository) -> list[str]:
    return [
        preference.label
        for preference in repository.list_candidate_preferences(person_id=DEMO_PERSON_ID)
        if preference.suppressed
    ]


def _play_mdm_lim(repository: SqlAlchemyRepository, senior_sub: str) -> None:
    """Two real days, deliberately through the same methods the routes use, so the policy decides
    and every decision has its evidence and audit rows. `reset` also starts the new run with active
    consent; standing mutes and senior statements carry over, and the story leaves those alone."""
    repository.reset(person_id=DEMO_PERSON_ID)
    day_1 = repository.advance("activity_declines", _DAYS[0], person_id=DEMO_PERSON_ID)
    nudge = day_1.created_intervention
    if nudge is None or nudge.title != NUDGE_TITLE:
        raise StoryFailed(
            f'Day 1 did not offer "{NUDGE_TITLE}" (decision: {day_1.state.last_decision.value}). '
            f"{_mute_hint(repository)}"
        )
    repository.record_outcome(
        nudge.intervention_id, OutcomeKind.DEFERRED, senior_sub, person_id=DEMO_PERSON_ID
    )
    repository.advance("activity_declines", _DAYS[1], person_id=DEMO_PERSON_ID)


def _mute_hint(repository: SqlAlchemyRepository) -> str:
    muted = _muted_labels(repository)
    if not muted:
        return (
            "No suggestion is muted, so an earlier answer probably changed the ranking: answers "
            "are kept across runs and the story cannot remove them (see docs/supabase.md)."
        )
    return (
        f"Mdm Lim has muted: {', '.join(muted)}. A mute is her own standing instruction, so the "
        "story does not lift it. Lift it signed in as `senior` (see docs/supabase.md), then run "
        "this again."
    )


def _write_groups(
    repository: SqlAlchemyRepository,
    family: FamilyGroups,
    calendar: FamilyCalendarStore,
    subs: dict[str, str],
    today: date,
) -> Landing:
    """Every group write, in one transaction."""
    sarah = subs["sarah"]
    with repository.sessions.begin() as session:
        lim_group = session.scalar(
            select(CareGroupRow).where(CareGroupRow.person_id == DEMO_PERSON_ID)
        )
        now = datetime.now(UTC)
        if lim_group is None:
            person = session.get(PersonRow, DEMO_PERSON_ID)
            person_name = person.display_name if person is not None else "Mdm Lim"
            lim_group = CareGroupRow(
                group_id=_id("grp"),
                person_id=DEMO_PERSON_ID,
                senior_name=person_name[:SENIOR_NAME_MAX],
                linked_via="demo_seed",
                linked_at=now,
                linked_by=sarah,
                created_by=sarah,
                created_at=now,
            )
            session.add(lim_group)
            session.flush()
        lim_group.created_by = sarah
        lim_group.linked_by = sarah

        calendar.reset_demo_in(
            session,
            DEMO_PERSON_ID,
            today,
            {subs[login]: relationship for login, relationship in _LIM_FAMILY.items()},
            # Removes earlier Mr Tan groups and anything else these accounts left unlinked.
            also_creators=[subs["weiming"], subs["aisha"], *DEMO_FAMILY],
            leave_other_unlinked_groups=False,
        )
        # Sample tasks go here once `family_tasks.seed_demo_tasks` (issue #13) is on this branch.
        tan_group_id, pin_expires = _seed_mr_tan(session, family, calendar, subs, today)
        # Last, and so later than Mr Tan's creation: this is the group Sarah lands on.
        session.scalars(
            select(GroupMemberRow).where(
                GroupMemberRow.group_id == lim_group.group_id, GroupMemberRow.sub == sarah
            )
        ).one().last_opened_at = datetime.now(UTC)
        return Landing(lim_group.group_id, tan_group_id, pin_expires)


def _seed_mr_tan(
    session: Session,
    family: FamilyGroups,
    calendar: FamilyCalendarStore,
    subs: dict[str, str],
    today: date,
) -> tuple[str, date]:
    """Mr Tan is made up and no senior is linked, so this group sees nothing about a senior. It
    uses the row shapes `create_group` and `create_appointment` write."""
    sarah = subs["sarah"]
    now = datetime.now(UTC)
    group_id = _id("grp")
    session.add(
        CareGroupRow(
            group_id=group_id,
            person_id=None,
            senior_name=SECOND_SENIOR,
            linked_via=None,
            linked_at=None,
            linked_by=None,
            created_by=sarah,
            created_at=now,
        )
    )
    session.flush()
    members: dict[str, GroupMemberRow] = {}
    for index, (login, relationship) in enumerate(_TAN_FAMILY.items()):
        member = GroupMemberRow(
            member_id=_id("mem"),
            group_id=group_id,
            sub=subs[login],
            relationship=relationship,
            role="owner" if index == 0 else "member",
            status=MemberStatus.ACTIVE.value,
            created_at=now + timedelta(microseconds=index),
            approved_by=sarah,
            approved_at=now,
        )
        session.add(member)
        members[login] = member
    session.flush()

    def appointment(
        title: str, kind: str, offset: int, start: str, end: str, where: str, notes: str
    ) -> AppointmentRow:
        row = AppointmentRow(
            appointment_id=_id("appt"),
            group_id=group_id,
            title=title,
            kind=kind,
            start_date=today + timedelta(days=offset),
            start_time=start,
            end_time=end,
            location=where,
            notes=notes,
            repeat=RepeatRule.NONE.value,
            repeat_until=None,
            created_by=sarah,
            created_at=now,
        )
        session.add(row)
        return row

    clinic = appointment(
        "Eye clinic visit",
        "medical",
        2,
        "09:30",
        "10:30",
        "Community eye clinic",
        "He has the appointment letter. Someone should go home with him afterwards.",
    )
    appointment(
        "Grocery shopping",
        "errand",
        5,
        "10:00",
        "11:30",
        "Neighbourhood supermarket",
        "He likes to choose his own fruit. Bring the trolley bag.",
    )
    session.flush()
    calendar._volunteer(session, members["weiming"], clinic, clinic.start_date)
    record(
        session,
        group_id=group_id,
        actor_member_id=members["weiming"].member_id,
        kind=FamilyActivityKind.HELPER_JOINED,
        appointment=clinic,
        day=clinic.start_date,
        origin=ORIGIN_DEMO_SEED,
        at=now - timedelta(hours=3),
    )
    pin = family._issue_pin(
        session, purpose=GROUP_JOIN, created_by=sarah, ttl=GROUP_JOIN_TTL, group_id=group_id
    )
    return group_id, local_date(pin.expires_at)


def _verify(
    repository: SqlAlchemyRepository,
    family: FamilyGroups,
    calendar: FamilyCalendarStore,
    subs: dict[str, str],
    landing: Landing,
) -> None:
    problems = [
        *_mdm_lim_problems(repository),
        *_group_problems(repository, family, calendar, subs, landing),
    ]
    if problems:
        raise StoryFailed("The end state is wrong:\n  - " + "\n  - ".join(problems))


def _mdm_lim_problems(repository: SqlAlchemyRepository) -> list[str]:
    problems: list[str] = []
    state = repository.person_state(person_id=DEMO_PERSON_ID)
    if not state.consent_active:
        problems.append("Mdm Lim's consent is not active.")
    interventions = repository.list_interventions(person_id=DEMO_PERSON_ID)
    waiting = [row.title for row in interventions if row.status == "proposed"]
    if waiting != [WAITING_TITLE]:
        problems.append(
            f'Expected only "{WAITING_TITLE}" waiting, found {waiting}. {_mute_hint(repository)}'
        )
    nudges = [row for row in interventions if row.title == NUDGE_TITLE]
    if len(nudges) != 1 or nudges[0].outcome != OutcomeKind.DEFERRED.value:
        problems.append(f'"{NUDGE_TITLE}" should be answered once, with "Maybe later".')
    return problems


def _group_problems(
    repository: SqlAlchemyRepository,
    family: FamilyGroups,
    calendar: FamilyCalendarStore,
    subs: dict[str, str],
    landing: Landing,
) -> list[str]:
    problems: list[str] = []
    lim, tan = landing.lim_group_id, landing.tan_group_id

    expected_groups = {
        "sarah": [(lim, True, 3), (tan, False, 3)],
        "john": [(lim, False, 3)],
        "emily": [(lim, False, 3)],
        "weiming": [(tan, False, 3)],
        "aisha": [(tan, False, 3)],
    }
    for login, expected in expected_groups.items():
        groups = family.me(subs[login], None, None).groups
        found = [(group.group_id, group.last_opened, group.member_count) for group in groups]
        if found != expected:
            problems.append(
                f"`{login}` should have {len(expected)} group(s) and has {len(found)}, or a "
                "group is wrong. A group another account created is left alone, so if the login "
                "joined one, it must leave that group itself."
            )

    with repository.sessions() as session:
        for group_id, name, roster in (
            (lim, "Mdm Lim's", _LIM_FAMILY),
            (tan, "Mr Tan's", _TAN_FAMILY),
        ):
            members = session.scalars(
                select(GroupMemberRow).where(GroupMemberRow.group_id == group_id)
            ).all()
            found_members = {(row.sub, row.relationship, row.status, row.role) for row in members}
            owner = next(iter(roster))
            expected_members = {
                (
                    subs[login],
                    relationship,
                    MemberStatus.ACTIVE.value,
                    "owner" if login == owner else "member",
                )
                for login, relationship in roster.items()
            }
            if found_members != expected_members:
                problems.append(f"{name} group has the wrong members.")
            opened = {row.sub for row in members if row.last_opened_at is not None}
            if opened != ({subs["sarah"]} if group_id == lim else set()):
                problems.append(f"{name} group has the wrong last-opened members.")
            group = session.get(CareGroupRow, group_id)
            if group is None or group.created_by != subs["sarah"]:
                problems.append(f"{name} group is not owned by Sarah.")

        def count(row: type, group_id: str) -> int:
            return (
                session.scalar(
                    select(func.count()).select_from(row).where(row.group_id == group_id)
                )
                or 0
            )

        if count(AppointmentRow, lim) != len(_DEMO_APPOINTMENTS):
            problems.append("Mdm Lim's group has the wrong appointments.")
        if count(AppointmentRow, tan) != 2 or count(HelperAssignmentRow, tan) != 1:
            problems.append("Mr Tan's group has the wrong appointments or helpers.")
        if count(FamilyPinRow, tan) != 1:
            problems.append("Mr Tan's group has no Join PIN.")
        unlinked = session.scalar(
            select(func.count())
            .select_from(CareGroupRow)
            .where(
                CareGroupRow.person_id.is_(None),
                CareGroupRow.created_by.in_([subs[login] for login in FAMILY_LOGINS]),
            )
        )
        if unlinked != 1:
            problems.append("The demo accounts should have created exactly one unlinked group.")

    if len(calendar.activity(subs["sarah"], lim, 50, None).entries) != _SEEDED_LIM_FEED_ENTRIES:
        problems.append("Mdm Lim's group has the wrong feed.")
    if len(calendar.activity(subs["sarah"], tan, 50, None).entries) != 1:
        problems.append("Mr Tan's group has the wrong feed.")
    return problems


def run(settings: Settings) -> Landing:
    """Everything after the environment checks. The LLM is off whatever the environment says, and
    live weather with it: the deterministic ranker and the scripted events decide."""
    story_settings = settings.model_copy(
        update={"llm_enabled": False, "external_context_enabled": False}
    )
    _refuse_wrong_environment(story_settings)
    subs = _look_up_logins()
    repository = SqlAlchemyRepository(
        story_settings.database_url,
        seed=story_settings.demo_seed,
        scenario_version=story_settings.demo_scenario_version,
        settings=story_settings,
    )
    try:
        try:
            _check_accounts(repository, subs)
        # SQLite reports a missing table as OperationalError; psycopg as ProgrammingError.
        except (OperationalError, ProgrammingError) as exc:
            raise _refuse(
                "could not read the accounts from the database. Check DATABASE_URL and that "
                "'alembic upgrade head' has run. Nothing was changed."
            ) from exc
        family = FamilyGroups(repository.sessions, repository)
        calendar = FamilyCalendarStore(repository.sessions)
        _play_mdm_lim(repository, subs["senior"])
        landing = _write_groups(repository, family, calendar, subs, local_date(datetime.now(UTC)))
        _verify(repository, family, calendar, subs, landing)
        return landing
    finally:
        repository.close()


def main() -> None:
    settings = Settings()
    try:
        landing = run(settings)
    except StoryFailed as exc:
        print(f"Error: {exc}\nIt is safe to run this again.", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        # The type alone: a database error's text can carry connection details.
        print(
            f"Error: the story stopped ({type(exc).__name__}). It is safe to run this again.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    print("Demo story ready (synthetic data).")
    print(f'  Mdm Lim: "{WAITING_TITLE}" is waiting; "{NUDGE_TITLE}" was answered "Maybe later".')
    print("  Mdm Lim's group: Sarah (owner), John, Emily. Sarah lands here.")
    print(
        "  Mr Tan's group: Sarah (owner), Wei Ming, Aisha. "
        f"Its Join PIN lasts until {landing.join_pin_expires_on.isoformat()}; "
        "a member can show a new one at any time."
    )


if __name__ == "__main__":
    main()
