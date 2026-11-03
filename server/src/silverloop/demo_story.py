"""Admin command: put the signed-in demo into its starting state, for the real demo logins.

Usage:
    pnpm demo:story

The signed-in logins (`sarah`, `john`, `emily`, `weiming`, `aisha`, `senior`) are real Supabase
users, so the seeded `demo-*` members mean nothing to them. This plays Mdm Lim's two days through
the real `advance`, gives her family group to the real family, adds a second group for the made-up
Mr Tan, and reads the result back. It is not part of `pnpm demo:offline`.

Re-running gives the same groups and the same shape of story. Which programme suggestion is waiting
is the real ranking's choice: Mdm Lim's earlier answers are kept across runs, so it can differ, and
it is printed. Everything about Mdm Lim and the people here is synthetic. The story never sets a
password or a role: `setup_demo_accounts` owns those.

Not atomic as a whole: `reset`, each `advance` and the outcome commit on their own, and all the
family group writes are one transaction. A failure part-way through Mdm Lim's run leaves her on a
newer, unfinished run with the groups as they were; a failure in the group transaction changes no
group. Running it again repairs both, unless the policy itself decided otherwise (`_play_mdm_lim`).
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
    DecisionEvidenceRow,
    FamilyPinRow,
    GroupMemberRow,
    HelperAssignmentRow,
    InterventionRow,
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
from silverloop.models import (
    AccountRole,
    AdvanceResponse,
    Decision,
    FamilyActivityKind,
    MemberStatus,
    OutcomeKind,
    PolicyGate,
    RepeatRule,
)
from silverloop.runtime import RuntimeConfigurationError, validate_runtime
from silverloop.setup_demo_accounts import _find_user_by_email, _supabase_admin
from silverloop.sql_repository import SqlAlchemyRepository

LOGINS = ("sarah", "john", "emily", "weiming", "aisha", "senior")
EMAIL_DOMAIN = "silverloop.demo"
FAMILY_LOGINS = tuple(login for login in LOGINS if login != "senior")

SECOND_SENIOR = "Mr Tan"
# The seeded accounts' subs all start with this; a real login's sub is a UUID.
_SEEDED_SUB_PREFIX = "demo-"

# Mdm Lim's family, then Mr Tan's. The owner comes first in each.
_LIM_FAMILY = {"sarah": "Daughter", "john": "Son", "emily": "Granddaughter"}
_TAN_FAMILY = {"sarah": "Niece", "weiming": "Son", "aisha": "Niece"}
_DAYS = ("demo-story-day-1", "demo-story-day-2")
_SEEDED_LIM_FEED_ENTRIES = 6


class StoryFailed(Exception):
    """The story could not finish, or finished in the wrong state. The message is safe to print."""

    def __init__(self, message: str, *, running_again_can_help: bool = False) -> None:
        super().__init__(message)
        self.running_again_can_help = running_again_can_help


@dataclass(frozen=True)
class Landing:
    lim_group_id: str
    tan_group_id: str
    join_pin_expires_on: date


@dataclass(frozen=True)
class MdmLimStory:
    """What the policy and the ranking chose. `nudge_title` is `None` when she has muted every
    nudge, so day 1 offered nothing to answer."""

    suggestion_title: str
    nudge_title: str | None


@dataclass(frozen=True, order=True)
class OtherGroup:
    """A group outside the story that a login belongs to. Order is the order it is printed in."""

    senior_name: str
    creator: str


@dataclass(frozen=True)
class StoryResult:
    landing: Landing
    mdm_lim: MdmLimStory
    # Each login that also has a place in a group outside the story, whoever created it.
    other_groups: dict[str, list[OtherGroup]]


def _plain(text: str) -> str:
    """Typed names on one line, in ASCII: they must not break a warning, or a console's encoding."""
    return text.encode("unicode_escape").decode("ascii")


def _creator_label(session: Session, created_by: str, subs: dict[str, str]) -> str:
    """The login if the creator has one. Otherwise the display name with the sub, because seeded
    accounts share their display names with the logins, or the sub alone if there is no name."""
    for login, sub in subs.items():
        if sub == created_by:
            return f"`{login}`"
    account = session.get(AccountRow, created_by)
    if account is None or not account.display_name:
        return _plain(created_by)
    return f"{_plain(account.display_name)} ({_plain(created_by)})"


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


def _refuse_stale_schema(repository: SqlAlchemyRepository, profile: str) -> None:
    """The check `/ready` makes, before anything is read from or written to the story's tables."""
    readiness = repository.readiness(profile)
    if not readiness.database_connected:
        raise _refuse("could not connect to the database. Check DATABASE_URL. Nothing was changed.")
    if readiness.migration_revision != readiness.expected_migration_revision:
        raise _refuse(
            f"the database is at Alembic revision {readiness.migration_revision or 'none'} and "
            f"this code needs {readiness.expected_migration_revision}. Start the API once, or run "
            "`alembic upgrade head` in server/, then run this again. Nothing was changed."
        )


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


def _not_as_planned(
    day: int, wanted: str, result: AdvanceResponse, repository: SqlAlchemyRepository
) -> StoryFailed:
    state = result.state
    return StoryFailed(
        f"Day {day} did not offer {wanted}: the policy decided {state.last_decision.value} "
        f"({state.decided_by_gate.value}). {' '.join(state.rationale)} {_mute_hint(repository)}"
    )


def _play_mdm_lim(repository: SqlAlchemyRepository, senior_sub: str) -> MdmLimStory:
    """Two real days, deliberately through the same methods the routes use, so the policy decides
    and every decision has its evidence and audit rows. `reset` also starts the new run with active
    consent; standing mutes and senior statements carry over, and the story leaves those alone.

    The ranking picks which nudge and which suggestion, from everything she has answered before.
    A nudge she has wholly muted is her instruction and the story carries on without one: the
    decision stays at the severity rung and `_resolve_decision_state` lowers it to `NO_ACTION`.
    Any other decision on either day ends the story, because running it again would decide the
    same thing."""
    repository.reset(person_id=DEMO_PERSON_ID)
    day_1 = repository.advance("activity_declines", _DAYS[0], person_id=DEMO_PERSON_ID)
    nudge = day_1.created_intervention
    if nudge is not None and day_1.state.last_decision == Decision.GENTLE_NUDGE:
        repository.record_outcome(
            nudge.intervention_id, OutcomeKind.DEFERRED, senior_sub, person_id=DEMO_PERSON_ID
        )
    elif not (
        nudge is None
        and day_1.state.last_decision == Decision.NO_ACTION
        and day_1.state.decided_by_gate == PolicyGate.SEVERITY_PERSISTENCE
    ):
        raise _not_as_planned(1, "a nudge", day_1, repository)

    day_2 = repository.advance("activity_declines", _DAYS[1], person_id=DEMO_PERSON_ID)
    suggestion = day_2.created_intervention
    if suggestion is None or day_2.state.last_decision != Decision.PROGRAMME_SUGGESTION:
        raise _not_as_planned(2, "a programme suggestion", day_2, repository)
    return MdmLimStory(suggestion.title, nudge.title if nudge is not None else None)


def _mute_hint(repository: SqlAlchemyRepository) -> str:
    muted = _muted_labels(repository)
    if not muted:
        return "Nothing is muted, so running this again will decide the same thing."
    return (
        f"Mdm Lim has muted: {', '.join(muted)}. A mute is her own instruction, or follows three "
        "of her declines, so the story does not lift it. Lift it signed in as `senior` (see "
        "docs/supabase.md), then run this again."
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
        # Only the seeded family's link is replaced. `linked_via` and `linked_at` stay on any link,
        # so a link somebody really made keeps saying who made it.
        if (lim_group.linked_by or "").startswith(_SEEDED_SUB_PREFIX):
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
        # `reset_demo_in` also seeds Mdm Lim's sample tasks (`family_tasks.seed_demo_tasks`).
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
    mdm_lim: MdmLimStory,
) -> dict[str, list[OtherGroup]]:
    """Raises if the end state is wrong; returns the logins that are also in a group outside it."""
    group_problems, other_groups = _group_problems(repository, family, calendar, subs, landing)
    problems = [*_mdm_lim_problems(repository, mdm_lim), *group_problems]
    if problems:
        raise StoryFailed(
            "The end state is wrong:\n  - " + "\n  - ".join(problems),
            running_again_can_help=True,
        )
    return other_groups


def _mdm_lim_problems(repository: SqlAlchemyRepository, mdm_lim: MdmLimStory) -> list[str]:
    problems: list[str] = []
    state = repository.person_state(person_id=DEMO_PERSON_ID)
    if not state.consent_active:
        problems.append("Mdm Lim's consent is not active.")
    if state.last_decision != Decision.PROGRAMME_SUGGESTION:
        problems.append(f"Mdm Lim's state reads {state.last_decision.value}.")
    interventions = repository.list_interventions(person_id=DEMO_PERSON_ID)
    waiting = [row for row in interventions if row.status == "proposed"]
    if (
        [row.title for row in waiting] != [mdm_lim.suggestion_title]
        or waiting[0].decision != Decision.PROGRAMME_SUGGESTION
        or not (waiting[0].candidate_key or "").startswith("programme:")
        or not _recorded_as_programme_suggestion(repository, waiting[0].intervention_id)
    ):
        problems.append(
            "Expected exactly one programme suggestion waiting, from a recorded "
            f"programme_suggestion decision, and found {[row.title for row in waiting]}."
        )
    nudges = [row for row in interventions if row.decision == Decision.GENTLE_NUDGE]
    if mdm_lim.nudge_title is None:
        if nudges:
            problems.append("No nudge should have been offered.")
    elif (
        len(nudges) != 1
        or nudges[0].title != mdm_lim.nudge_title
        or nudges[0].outcome != OutcomeKind.DEFERRED.value
    ):
        problems.append(f'"{mdm_lim.nudge_title}" should be answered once, with "Maybe later".')
    return problems


def _recorded_as_programme_suggestion(
    repository: SqlAlchemyRepository, intervention_id: str
) -> bool:
    with repository.sessions() as session:
        recorded = session.scalar(
            select(DecisionEvidenceRow.decision)
            .join(
                InterventionRow,
                InterventionRow.decision_evidence_id == DecisionEvidenceRow.evidence_id,
            )
            .where(InterventionRow.intervention_id == intervention_id)
        )
    return recorded == Decision.PROGRAMME_SUGGESTION.value


def _group_problems(
    repository: SqlAlchemyRepository,
    family: FamilyGroups,
    calendar: FamilyCalendarStore,
    subs: dict[str, str],
    landing: Landing,
) -> tuple[list[str], dict[str, list[OtherGroup]]]:
    problems: list[str] = []
    other_groups: dict[str, list[OtherGroup]] = {}
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
        found = [
            (group.group_id, group.last_opened, group.member_count)
            for group in groups
            if group.group_id in (lim, tan)
        ]
        if found != expected:
            problems.append(f"`{login}` has the wrong demo groups.")
        # The story leaves these alone and no route lets the login leave: somebody else's group, or
        # a linked group of its own, since only unlinked ones are removed.
        extras = [group for group in groups if group.group_id not in (lim, tan)]
        if extras:
            with repository.sessions() as session:
                other_groups[login] = sorted(
                    OtherGroup(
                        _plain(group.senior_name),
                        _creator_label(
                            session,
                            session.get(CareGroupRow, group.group_id).created_by,
                            subs,
                        ),
                    )
                    for group in extras
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
    return problems, other_groups


def run(settings: Settings) -> StoryResult:
    """Everything after the environment checks. The LLM is off whatever the environment says, and
    live weather with it: the deterministic ranker and the scripted events decide."""
    story_settings = settings.model_copy(
        update={"llm_enabled": False, "external_context_enabled": False}
    )
    _refuse_wrong_environment(story_settings)
    repository = SqlAlchemyRepository(
        story_settings.database_url,
        seed=story_settings.demo_seed,
        scenario_version=story_settings.demo_scenario_version,
        settings=story_settings,
    )
    try:
        _refuse_stale_schema(repository, story_settings.silverloop_runtime_profile)
        subs = _look_up_logins()
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
        mdm_lim = _play_mdm_lim(repository, subs["senior"])
        landing = _write_groups(repository, family, calendar, subs, local_date(datetime.now(UTC)))
        other_groups = _verify(repository, family, calendar, subs, landing, mdm_lim)
        return StoryResult(landing, mdm_lim, other_groups)
    finally:
        repository.close()


def main() -> None:
    settings = Settings()
    try:
        result = run(settings)
    except StoryFailed as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if exc.running_again_can_help:
            print("It is safe to run this again.", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        # The type alone: a database error's text can carry connection details.
        print(
            f"Error: the story stopped ({type(exc).__name__}). It is safe to run this again.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    for login, groups in result.other_groups.items():
        listed = "; ".join(f'"{group.senior_name}", created by {group.creator}' for group in groups)
        print(
            f"Warning: `{login}` is also in {len(groups)} group(s) outside the story: {listed}. "
            "The story left them untouched, so this login sees them too.",
            file=sys.stderr,
        )
    mdm_lim = result.mdm_lim
    print("Demo story ready (synthetic data).")
    print(f'  Mdm Lim: "{mdm_lim.suggestion_title}" is waiting.')
    if mdm_lim.nudge_title is None:
        print("  Day 1 offered no nudge, because she has muted every nudge.")
    else:
        print(f'  Day 1 offered "{mdm_lim.nudge_title}", answered "Maybe later".')
    print("  Mdm Lim's group: Sarah (owner), John, Emily. Sarah lands here.")
    print(
        "  Mr Tan's group: Sarah (owner), Wei Ming, Aisha. "
        f"Its Join PIN lasts until {result.landing.join_pin_expires_on.isoformat()}; "
        "a member can show a new one at any time."
    )


if __name__ == "__main__":
    main()
