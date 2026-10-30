"""`pnpm demo:story`, against a temporary SQLite database and a stand-in Supabase admin API."""

from __future__ import annotations

import io
import re
import sys
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from silverloop import demo_story
from silverloop.config import Settings
from silverloop.db_models import (
    AccountRow,
    AppointmentNoteRow,
    AppointmentRow,
    AuditEventRow,
    AvailabilityEntryRow,
    Base,
    CareGroupRow,
    DecisionEvidenceRow,
    FamilyActivityRow,
    FamilyPinRow,
    GroupMemberRow,
    HelperAssignmentRow,
    InterventionRow,
)
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_groups import DEMO_FAMILY, DEMO_FAMILY_SUB, DEMO_SENIOR_SUB, FamilyGroups
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.main import create_app, resets_demo_family_on_start
from silverloop.models import AppointmentRequest, CheckInKind, CheckInRequest
from silverloop.sql_repository import SqlAlchemyRepository

JWT_SECRET = "story-test-secret-key-at-least-32-bytes"
SUPABASE_URL = "https://project.supabase.co"
SECRET_KEY = "not-a-real-admin-key-Zq91"
DISPLAY_NAMES = {
    "sarah": "Sarah",
    "john": "John",
    "emily": "Emily",
    "weiming": "Wei Ming",
    "aisha": "Aisha",
}
OUTSIDER = "someone-else"


class FakeSupabaseAdmin:
    """Answers only the read the story may make. Any write fails the test."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.writes: list[str] = []
        self.failing = False

    def add(self, login: str, role: str | None = None) -> dict:
        user = {
            "id": str(uuid4()),
            "email": f"{login}@silverloop.demo",
            "app_metadata": {"role": role} if role else {},
        }
        self.users[login] = user
        return user

    def sub(self, login: str) -> str:
        return self.users[login]["id"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.failing:
            return httpx.Response(500)
        if request.method != "GET":
            self.writes.append(request.method)
            return httpx.Response(405)
        page = int(request.url.params["page"])
        size = int(request.url.params["per_page"])
        listed = list(self.users.values())[(page - 1) * size : page * size]
        return httpx.Response(200, json={"users": listed})


def _settings(database_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": database_url,
        "silverloop_runtime_profile": "offline",
        "auth_enabled": True,
        "llm_enabled": False,
        "supabase_url": SUPABASE_URL,
        "supabase_jwt_secret": JWT_SECRET,
    }
    return Settings(**{**values, **overrides})


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / 'story.db').as_posix()}"


@pytest.fixture
def repo(database_url: str) -> Iterator[SqlAlchemyRepository]:
    repository = SqlAlchemyRepository(database_url, settings=_settings(database_url))
    repository.create_schema_for_tests()
    repository.reset()
    yield repository
    repository.close()


@pytest.fixture
def admin(
    monkeypatch: pytest.MonkeyPatch, repo: SqlAlchemyRepository, database_url: str
) -> FakeSupabaseAdmin:
    """All six logins set up as `setup_demo_accounts` leaves them. Nothing can reach a network."""
    fake = FakeSupabaseAdmin()
    family = FamilyGroups(repo.sessions, repo)
    for login, name in DISPLAY_NAMES.items():
        fake.add(login)
        family.provision_family_account(fake.sub(login), name)
    fake.add("senior", role="senior")
    repo.upsert_person_link(fake.sub("senior"), DEMO_PERSON_ID, "setup_demo_accounts")

    monkeypatch.setattr(
        demo_story,
        "_supabase_admin",
        lambda *_: httpx.Client(
            transport=httpx.MockTransport(fake.handle), base_url="https://admin.invalid"
        ),
    )
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(demo_story, "Settings", lambda: _settings(database_url))
    return fake


@pytest.fixture
def client(repo: SqlAlchemyRepository, database_url: str) -> Iterator[TestClient]:
    settings = _settings(database_url)
    with TestClient(create_app(repo, settings=settings, migrate_on_start=False)) as test_client:
        yield test_client


def _headers(admin: FakeSupabaseAdmin, login: str) -> dict[str, str]:
    user = admin.users[login]
    claims = {
        "sub": user["id"],
        "iss": SUPABASE_URL + "/auth/v1",
        "aud": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "app_metadata": user["app_metadata"],
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def _groups(client: TestClient, admin: FakeSupabaseAdmin, login: str) -> list[dict]:
    response = client.get("/v1/me", headers=_headers(admin, login))
    assert response.status_code == 200, response.text
    return response.json()["groups"]


def _group_id(client: TestClient, admin: FakeSupabaseAdmin, login: str, senior: str) -> str:
    return next(
        group["group_id"]
        for group in _groups(client, admin, login)
        if group["senior_name"] == senior
    )


def _waiting(client: TestClient, admin: FakeSupabaseAdmin) -> list[str]:
    response = client.get("/v1/interventions", headers=_headers(admin, "senior"))
    assert response.status_code == 200, response.text
    return [row["title"] for row in response.json() if row["status"] == "proposed"]


def _snapshot(repo: SqlAlchemyRepository, admin: FakeSupabaseAdmin) -> dict[str, object]:
    """Everything about the end state that should not depend on when, or how often, it ran."""
    names = {user["id"]: login for login, user in admin.users.items()}
    with repo.sessions() as session:
        groups = {}
        for group in session.scalars(select(CareGroupRow)):
            members = session.scalars(
                select(GroupMemberRow).where(GroupMemberRow.group_id == group.group_id)
            ).all()
            by_id = {member.member_id: names.get(member.sub, member.sub) for member in members}

            def rows(model: type, group_id: str = group.group_id) -> list:
                return list(session.scalars(select(model).where(model.group_id == group_id)))

            groups[group.senior_name] = {
                "creator": names.get(group.created_by),
                "linked": group.person_id,
                "linked_by": names.get(group.linked_by),
                "members": sorted(
                    (by_id[m.member_id], m.relationship, m.role, m.status, bool(m.last_opened_at))
                    for m in members
                ),
                "appointments": sorted(
                    (a.title, a.kind, a.start_date, a.start_time, names.get(a.created_by))
                    for a in rows(AppointmentRow)
                ),
                "availability": sorted(
                    (by_id[a.member_id], a.on_date, a.start_time, a.status, a.appointment_id or "")
                    if not (a.appointment_id or "").startswith("appt_")
                    else (by_id[a.member_id], a.on_date, a.start_time, a.status, "appt")
                    for a in rows(AvailabilityEntryRow)
                ),
                "helpers": sorted(
                    (by_id[h.member_id], h.on_date) for h in rows(HelperAssignmentRow)
                ),
                "notes": sorted((by_id[n.member_id], n.text) for n in rows(AppointmentNoteRow)),
                "feed": sorted(
                    (by_id[f.actor_member_id], f.kind, f.on_date, f.note, f.origin)
                    for f in rows(FamilyActivityRow)
                ),
                "pins": len(rows(FamilyPinRow)),
            }
    interventions = repo.list_interventions(person_id=DEMO_PERSON_ID)
    return {
        "groups": groups,
        "interventions": [(row.title, row.status, row.outcome) for row in interventions],
    }


# ── AC1, AC2: what each real login sees ───────────────────────────────────────


def test_sarah_lands_on_mdm_lim_and_also_has_mr_tan(
    admin: FakeSupabaseAdmin, client: TestClient
) -> None:
    demo_story.main()

    groups = _groups(client, admin, "sarah")
    assert [
        (g["senior_name"], g["my_role"], g["my_status"], g["last_opened"], g["member_count"])
        for g in groups
    ] == [
        ("Mdm Lim", "owner", "active", True, 3),
        ("Mr Tan", "owner", "active", False, 3),
    ]
    assert groups[0]["person_id"] == DEMO_PERSON_ID
    assert groups[1]["person_id"] is None


@pytest.mark.parametrize("login", ["john", "emily"])
def test_john_and_emily_see_mdm_lims_schedule_and_feed(
    admin: FakeSupabaseAdmin, client: TestClient, login: str
) -> None:
    demo_story.main()
    headers = _headers(admin, login)

    groups = _groups(client, admin, login)
    assert [(g["senior_name"], g["my_role"], g["last_opened"]) for g in groups] == [
        ("Mdm Lim", "member", False)
    ]
    today = local_date(datetime.now(UTC))
    calendar = client.get(
        f"/v1/people/{DEMO_PERSON_ID}/calendar",
        params={"from_date": today, "to_date": today + timedelta(days=14)},
        headers=headers,
    )
    assert calendar.status_code == 200, calendar.text
    body = calendar.json()
    assert len(body["appointments"]) == 8
    assert {m["display_name"] for m in body["members"]} == {"Sarah", "John", "Emily"}
    feed = client.get(f"/v1/groups/{groups[0]['group_id']}/activity", headers=headers)
    assert feed.status_code == 200, feed.text
    assert len(feed.json()["entries"]) == 6


@pytest.mark.parametrize("login", ["weiming", "aisha"])
def test_wei_ming_and_aisha_see_only_mr_tan(
    admin: FakeSupabaseAdmin, client: TestClient, login: str
) -> None:
    demo_story.main()
    groups = _groups(client, admin, login)
    assert [(g["senior_name"], g["my_role"], g["last_opened"]) for g in groups] == [
        ("Mr Tan", "member", False)
    ]
    # An unlinked group sees nothing about a senior, and they are not in Mdm Lim's.
    today = local_date(datetime.now(UTC))
    calendar = client.get(
        f"/v1/people/{DEMO_PERSON_ID}/calendar",
        params={"from_date": today, "to_date": today},
        headers=_headers(admin, login),
    )
    assert calendar.status_code == 404


def test_the_seeded_demo_family_leaves_mdm_lims_group(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    _seed_the_sign_in_off_family(repo)
    demo_story.main()

    with repo.sessions() as session:
        lim = session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == DEMO_PERSON_ID))
        subs = set(
            session.scalars(
                select(GroupMemberRow.sub).where(GroupMemberRow.group_id == lim.group_id)
            )
        )
        assert subs == {admin.sub("sarah"), admin.sub("john"), admin.sub("emily")}
        assert lim.created_by == lim.linked_by == admin.sub("sarah")
        creators = set(
            session.scalars(
                select(AppointmentRow.created_by).where(AppointmentRow.group_id == lim.group_id)
            )
        )
        assert creators == {admin.sub("sarah")}
    roster = client.get(f"/v1/groups/{lim.group_id}", headers=_headers(admin, "sarah")).json()
    assert [(m["display_name"], m["relationship"], m["role"]) for m in roster["members"]] == [
        ("Sarah", "Daughter", "owner"),
        ("John", "Son", "member"),
        ("Emily", "Granddaughter", "member"),
    ]


def test_mr_tans_group_has_its_pin_appointments_and_one_entry(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    demo_story.main()
    headers = _headers(admin, "sarah")
    group_id = _group_id(client, admin, "sarah", "Mr Tan")

    roster = client.get(f"/v1/groups/{group_id}", headers=headers).json()
    assert [(m["display_name"], m["relationship"], m["role"]) for m in roster["members"]] == [
        ("Sarah", "Niece", "owner"),
        ("Wei Ming", "Son", "member"),
        ("Aisha", "Niece", "member"),
    ]
    today = local_date(datetime.now(UTC))
    with repo.sessions() as session:
        appointments = list(
            session.scalars(select(AppointmentRow).where(AppointmentRow.group_id == group_id))
        )
        assert len(appointments) == 2
        assert all(today < row.start_date <= today + timedelta(days=7) for row in appointments)
        helpers = list(
            session.scalars(
                select(HelperAssignmentRow).where(HelperAssignmentRow.group_id == group_id)
            )
        )
        assert len(helpers) == 1  # one taken, one still needing a helper
        pin = session.scalar(select(FamilyPinRow).where(FamilyPinRow.group_id == group_id))
        assert pin is not None and pin.purpose == "group_join"
        expires = pin.expires_at.replace(tzinfo=UTC)
        assert expires > datetime.now(UTC)
    feed = client.get(f"/v1/groups/{group_id}/activity", headers=headers).json()["entries"]
    assert [entry["kind"] for entry in feed] == ["helper_joined"]
    # Any member can show a fresh Join PIN, which is how one gets a new one after 7 days.
    fresh = client.post(f"/v1/groups/{group_id}/join-pin", headers=_headers(admin, "aisha"))
    assert fresh.status_code == 200, fresh.text


# ── AC3: real decisions, with the LLM off ─────────────────────────────────────


def test_the_senior_sees_the_suggestion_waiting_and_the_nudge_answered(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    demo_story.main()

    assert _waiting(client, admin) == ["Chair Mobility & Balance"]
    rows = client.get("/v1/interventions", headers=_headers(admin, "senior")).json()
    nudge = next(row for row in rows if row["title"] == "Five-minute movement option")
    assert (nudge["decision"], nudge["outcome"]) == ("gentle_nudge", "deferred")
    chair = next(row for row in rows if row["title"] == "Chair Mobility & Balance")
    assert (chair["decision"], chair["outcome"]) == ("programme_suggestion", None)

    with repo.sessions() as session:
        run_id = session.scalar(
            select(InterventionRow.run_id).where(
                InterventionRow.intervention_id == nudge["intervention_id"]
            )
        )
        for row in (nudge, chair):
            stored = session.get(InterventionRow, row["intervention_id"])
            evidence = session.get(DecisionEvidenceRow, stored.decision_evidence_id)
            assert evidence is not None and evidence.evidence_id
        audited = list(
            session.execute(
                select(AuditEventRow.event_type, AuditEventRow.decision, AuditEventRow.actor).where(
                    AuditEventRow.run_id == run_id
                )
            )
        )
    assert [row for row in audited if row.event_type == "demo_reset"]
    decisions = {row.decision for row in audited}
    assert {"gentle_nudge", "programme_suggestion"} <= decisions
    answered = [row for row in audited if "outcome" in row.event_type]
    assert [row.actor for row in answered] == [admin.sub("senior")]


def test_the_llm_stays_off_even_when_the_environment_turns_it_on(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    from silverloop.agent import planner

    def no_provider(*_: object, **__: object) -> None:
        raise AssertionError("the planner tried to reach a provider")

    monkeypatch.setattr(planner, "planner_transport", no_provider)
    monkeypatch.setattr(
        demo_story,
        "Settings",
        lambda: _settings(
            database_url, llm_enabled=True, llm_provider="anthropic", llm_api_key="x"
        ),
    )
    built: list[Settings] = []
    real_repository = demo_story.SqlAlchemyRepository

    def recording(url: str, **kwargs: object) -> SqlAlchemyRepository:
        built.append(kwargs["settings"])  # type: ignore[arg-type]
        return real_repository(url, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(demo_story, "SqlAlchemyRepository", recording)

    demo_story.main()

    assert [settings.llm_enabled for settings in built] == [False]
    rows = client.get("/v1/interventions", headers=_headers(admin, "senior")).json()
    for row in rows:
        assert row["evidence"]["agent"]["mode"] == "fallback_disabled"
    assert _waiting(client, admin) == ["Chair Mobility & Balance"]


# ── AC4: re-running ───────────────────────────────────────────────────────────


def test_running_twice_gives_the_same_end_state(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository
) -> None:
    demo_story.main()
    first = _snapshot(repo, admin)
    demo_story.main()
    assert _snapshot(repo, admin) == first
    with repo.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CareGroupRow)) == 2


def test_a_re_run_clears_what_people_did_in_both_groups(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    demo_story.main()
    clean = _snapshot(repo, admin)
    family = FamilyGroups(repo.sessions, repo)
    calendar = FamilyCalendarStore(repo.sessions)
    lim = _group_id(client, admin, "sarah", "Mdm Lim")
    tan = _group_id(client, admin, "sarah", "Mr Tan")
    # An extra member in each, some activity, a different landing, and a stray unlinked group.
    for group_id in (lim, tan):
        pin = family.create_join_pin(admin.sub("sarah"), group_id).pin
        family.join_group(OUTSIDER + group_id, pin, "Friend")
        calendar.check_in(
            admin.sub("sarah"), group_id, CheckInRequest(kind=CheckInKind.VISITED, note="Tea")
        )
    calendar.create_appointment(
        admin.sub("aisha"),
        tan,
        AppointmentRequest(
            title="Extra",
            kind="activity",
            date=date.today() + timedelta(days=3),
            start="10:00",
            end="11:00",
        ),
    )
    family.open_group(admin.sub("sarah"), tan)
    family.create_group(admin.sub("weiming"), "Son", senior_name="Stray")

    demo_story.main()

    assert _snapshot(repo, admin) == clean


def test_a_failed_run_can_simply_be_run_again(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    demo_story.main()
    clean = _snapshot(repo, admin)
    real = demo_story._seed_mr_tan

    def fails_half_way(*args: object, **kwargs: object) -> None:
        real(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("database went away: postgresql://user:hunter2@db.invalid/x")

    monkeypatch.setattr(demo_story, "_seed_mr_tan", fails_half_way)
    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "safe to run this again" in captured.err
    assert "hunter2" not in captured.out + captured.err

    # The group transaction rolled back whole: the groups are as they were.
    after_failure = _snapshot(repo, admin)
    assert after_failure["groups"] == clean["groups"]

    monkeypatch.setattr(demo_story, "_seed_mr_tan", real)
    demo_story.main()
    assert _snapshot(repo, admin) == clean


# ── AC5: other people's groups ────────────────────────────────────────────────


def _full_row_dump(repo: SqlAlchemyRepository, group_id: str) -> dict[str, list[dict]]:
    with repo.sessions() as session:
        dump: dict[str, list[dict]] = {}
        for table in Base.metadata.sorted_tables:
            if "group_id" not in table.c:
                continue
            rows = session.execute(select(table).where(table.c.group_id == group_id)).mappings()
            dump[table.name] = sorted(
                (dict(row) for row in rows), key=lambda row: str(sorted(row.items(), key=str))
            )
        return dump


def test_another_accounts_groups_are_untouched(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository
) -> None:
    family = FamilyGroups(repo.sessions, repo)
    calendar = FamilyCalendarStore(repo.sessions)
    other_person = "person-other"
    repo.reset(person_id=other_person, allow_new_person=True)
    unlinked = family.create_group(OUTSIDER, "Son", senior_name="Mdm Ong").group_id
    pin = family.create_join_pin(OUTSIDER, unlinked).pin
    family.join_group("outsider-friend", pin, "Friend")
    calendar.check_in(OUTSIDER, unlinked, CheckInRequest(kind=CheckInKind.CALLED))
    link_pin = family.create_link_pin("other-senior", other_person).pin
    linked = family.create_group(OUTSIDER, "Son", senior_pin=link_pin).group_id
    before = (_full_row_dump(repo, unlinked), _full_row_dump(repo, linked))

    demo_story.main()
    demo_story.main()

    assert (_full_row_dump(repo, unlinked), _full_row_dump(repo, linked)) == before


def test_a_login_in_someone_elses_group_stops_success_and_the_group_stays(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, capsys: pytest.CaptureFixture[str]
) -> None:
    """The two rules meet here: that group stays exactly as it is, including Sarah's place in it, so
    she has three groups, not two. The command says so instead of printing success."""
    family = FamilyGroups(repo.sessions, repo)
    theirs = family.create_group(OUTSIDER, "Son", senior_name="Mdm Ong").group_id
    pin = family.create_join_pin(OUTSIDER, theirs).pin
    family.join_group(admin.sub("sarah"), pin, "Friend")
    before = _full_row_dump(repo, theirs)

    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()

    assert exit_info.value.code == 1
    assert "`sarah`" in capsys.readouterr().err
    assert _full_row_dump(repo, theirs) == before


def test_other_unlinked_groups_of_demo_accounts_go_with_their_children(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    family = FamilyGroups(repo.sessions, repo)
    calendar = FamilyCalendarStore(repo.sessions)
    stray = family.create_group(admin.sub("john"), "Son", senior_name="Stray").group_id
    calendar.check_in(admin.sub("john"), stray, CheckInRequest(kind=CheckInKind.CALLED))
    seeded = family.create_group(DEMO_FAMILY_SUB, "Son", senior_name="Seeded").group_id

    demo_story.main()

    with repo.sessions() as session:
        assert session.get(CareGroupRow, stray) is None
        assert session.get(CareGroupRow, seeded) is None
        for model in (GroupMemberRow, FamilyActivityRow):
            count = session.scalar(
                select(func.count()).select_from(model).where(model.group_id == stray)
            )
            assert count == 0
    assert [g["senior_name"] for g in _groups(client, admin, "john")] == ["Mdm Lim"]


# ── AC6: refusals ─────────────────────────────────────────────────────────────


def _everything(repo: SqlAlchemyRepository) -> dict[str, int]:
    with repo.sessions() as session:
        return {
            table.name: session.scalar(select(func.count()).select_from(table)) or 0
            for table in Base.metadata.sorted_tables
        }


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"app_env": "production"}, "APP_ENV=production"),
        ({"auth_enabled": False}, "AUTH_ENABLED=false"),
    ],
)
def test_the_wrong_environment_is_refused_before_anything_is_written(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    database_url: str,
    overrides: dict[str, object],
    expected: str,
) -> None:
    before = _everything(repo)
    monkeypatch.setattr(demo_story, "Settings", lambda: _settings(database_url, **overrides))
    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()
    assert exit_info.value.code == 1
    assert expected in capsys.readouterr().err
    assert _everything(repo) == before


@pytest.mark.parametrize("login", ["sarah", "john", "emily", "weiming", "aisha", "senior"])
def test_a_missing_login_is_refused_before_anything_is_written(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    capsys: pytest.CaptureFixture[str],
    login: str,
) -> None:
    del admin.users[login]
    before = _everything(repo)
    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert login in err and "setup_demo_accounts" in err
    assert _everything(repo) == before


def test_a_display_name_never_stands_in_for_the_login(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, capsys: pytest.CaptureFixture[str]
) -> None:
    """The seeded `demo-family` is also called Sarah, and it does not count."""
    _seed_the_sign_in_off_family(repo)
    del admin.users["sarah"]
    with pytest.raises(SystemExit):
        demo_story.main()
    assert "setup_demo_accounts" in capsys.readouterr().err


def test_a_login_with_no_family_account_or_senior_link_is_refused(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, capsys: pytest.CaptureFixture[str]
) -> None:
    with repo.sessions.begin() as session:
        session.delete(session.get(AccountRow, admin.sub("emily")))
    before = _everything(repo)
    with pytest.raises(SystemExit):
        demo_story.main()
    assert "`emily`" in capsys.readouterr().err
    assert _everything(repo) == before


def test_an_unreachable_admin_api_is_refused_with_no_secret_in_the_message(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, capsys: pytest.CaptureFixture[str]
) -> None:
    admin.failing = True
    before = _everything(repo)
    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert SECRET_KEY not in captured.out + captured.err
    assert _everything(repo) == before


def test_missing_supabase_settings_are_refused(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SUPABASE_SECRET_KEY")
    with pytest.raises(SystemExit):
        demo_story.main()
    assert "SUPABASE_SECRET_KEY" in capsys.readouterr().err


# ── Consent, mutes and earlier answers ────────────────────────────────────────


def test_reset_restores_consent_a_tester_revoked(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    repo.set_consent(False, "Testing a revocation", "tester", person_id=DEMO_PERSON_ID)
    assert repo.person_state(person_id=DEMO_PERSON_ID).consent_active is False

    demo_story.main()

    assert repo.person_state(person_id=DEMO_PERSON_ID).consent_active is True
    assert _waiting(client, admin) == ["Chair Mobility & Balance"]


@pytest.mark.parametrize(
    "candidate_key_part",
    ["gentle_nudge", "programme_suggestion"],
)
def test_a_mute_that_stops_a_suggestion_stops_success_and_stays(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    capsys: pytest.CaptureFixture[str],
    candidate_key_part: str,
) -> None:
    demo_story.main()
    capsys.readouterr()
    rows = repo.list_interventions(person_id=DEMO_PERSON_ID)
    target = next(row for row in rows if row.decision.value == candidate_key_part)
    repo.set_candidate_preference(
        target.candidate_key, True, "not for me", "senior", person_id=DEMO_PERSON_ID
    )

    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "Demo story ready" not in captured.out
    assert "muted" in captured.err
    still = {
        pref.candidate_key
        for pref in repo.list_candidate_preferences(person_id=DEMO_PERSON_ID)
        if pref.suppressed
    }
    assert target.candidate_key in still


def _answer_the_waiting_suggestion(repo: SqlAlchemyRepository, answer: str) -> None:
    waiting = next(
        row for row in repo.list_interventions(person_id=DEMO_PERSON_ID) if row.status == "proposed"
    )
    repo.record_outcome(waiting.intervention_id, answer, "senior", person_id=DEMO_PERSON_ID)


@pytest.mark.parametrize("answer", ["accepted", "deferred"])
def test_a_rehearsal_that_answers_kindly_can_be_run_again(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
    answer: str,
) -> None:
    demo_story.main()
    _answer_the_waiting_suggestion(repo, answer)
    capsys.readouterr()

    demo_story.main()

    assert "Demo story ready" in capsys.readouterr().out
    assert _waiting(client, admin) == ["Chair Mobility & Balance"]


@pytest.mark.parametrize("answer", ["declined", "no_response"])
def test_an_earlier_refusal_changes_the_ranking_and_stops_success(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    capsys: pytest.CaptureFixture[str],
    answer: str,
) -> None:
    """Outcomes are append-only and outlive a reset, so "Sheltered Morning Walk" now ranks first.
    The command must say so: it may not delete the answer or call this success."""
    demo_story.main()
    _answer_the_waiting_suggestion(repo, answer)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "Demo story ready" not in captured.out
    assert "earlier answer" in captured.err
    assert "Sheltered Morning Walk" in captured.err


def test_an_earlier_no_to_the_nudge_stops_success(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo.reset(person_id=DEMO_PERSON_ID)
    nudge = repo.advance("activity_declines", "x", person_id=DEMO_PERSON_ID).created_intervention
    repo.record_outcome(nudge.intervention_id, "declined", "senior", person_id=DEMO_PERSON_ID)

    with pytest.raises(SystemExit) as exit_info:
        demo_story.main()

    assert exit_info.value.code == 1
    assert "Day 1 did not offer" in capsys.readouterr().err


# ── AC7, AC8: start-up and sign-in off ────────────────────────────────────────


def _seed_the_sign_in_off_family(repo: SqlAlchemyRepository) -> None:
    FamilyGroups(repo.sessions, repo).ensure_demo_group()
    FamilyCalendarStore(repo.sessions).reset_demo(
        DEMO_PERSON_ID,
        local_date(datetime.now(UTC)),
        {sub: relationship for sub, (_, relationship) in DEMO_FAMILY.items()},
    )


@pytest.mark.parametrize(
    ("auth_enabled", "url", "expected"),
    [
        (False, "sqlite+pysqlite:///:memory:", True),
        (False, "postgresql+psycopg://u@h/d", False),
        (True, "sqlite+pysqlite:///:memory:", False),
        (True, "postgresql+psycopg://u@h/d", False),
    ],
)
def test_the_start_up_reset_runs_only_on_sqlite_with_sign_in_off(
    auth_enabled: bool, url: str, expected: bool
) -> None:
    repository = SimpleNamespace(engine=SimpleNamespace(url=make_url(url)))
    settings = SimpleNamespace(auth_enabled=auth_enabled)
    assert resets_demo_family_on_start(settings, repository) is expected


def test_starting_with_sign_in_off_on_a_server_database_leaves_the_family_alone(
    repo: SqlAlchemyRepository, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real lifespan, with the repository reporting a PostgreSQL engine."""
    with repo.sessions.begin() as session:
        session.add(
            AccountRow(
                sub="family",
                role="family",
                display_name="Ana",
                created_at=datetime.now(UTC),
            )
        )
    group_id = (
        FamilyGroups(repo.sessions, repo)
        .create_group("family", "Son", senior_name="Their senior")
        .group_id
    )
    before = _full_row_dump(repo, group_id)
    monkeypatch.setattr(repo, "engine", SimpleNamespace(url=make_url("postgresql+psycopg://u@h/d")))
    settings = _settings(database_url, auth_enabled=False)
    resets: list[str] = []
    monkeypatch.setattr(FamilyGroups, "ensure_demo_group", lambda _: resets.append("ensure"))
    monkeypatch.setattr(FamilyCalendarStore, "reset_demo", lambda *_: resets.append("reset"))

    with TestClient(create_app(repo, settings=settings, migrate_on_start=False)):
        pass

    assert resets == []
    assert _full_row_dump(repo, group_id) == before


def test_starting_with_sign_in_off_on_sqlite_still_seeds_the_demo_family(
    repo: SqlAlchemyRepository, database_url: str
) -> None:
    settings = _settings(database_url, auth_enabled=False)
    with TestClient(create_app(repo, settings=settings, migrate_on_start=False)):
        pass
    with repo.sessions() as session:
        group = session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == DEMO_PERSON_ID))
        assert group is not None and group.created_by == DEMO_FAMILY_SUB
        subs = list(
            session.scalars(
                select(GroupMemberRow.sub)
                .where(GroupMemberRow.group_id == group.group_id)
                .order_by(GroupMemberRow.created_at)
            )
        )
        assert subs == list(DEMO_FAMILY)
        created_by = set(session.scalars(select(AppointmentRow.created_by)))
        assert created_by == {DEMO_FAMILY_SUB}
    assert repo.lookup_person_for_sub(DEMO_SENIOR_SUB) == DEMO_PERSON_ID


def test_the_demo_reset_route_still_seeds_the_demo_family(
    repo: SqlAlchemyRepository, database_url: str
) -> None:
    settings = _settings(database_url, auth_enabled=False)
    with TestClient(create_app(repo, settings=settings, migrate_on_start=False)) as test_client:
        response = test_client.post("/v1/demo/reset")
        assert response.status_code == 200, response.text
    with repo.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AppointmentRow)) == 8


# ── AC9: output and dates ─────────────────────────────────────────────────────


def test_no_secret_and_no_pin_in_the_output(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pins: list[str] = []
    real = FamilyGroups._issue_pin

    def keep(self: FamilyGroups, *args: object, **kwargs: object) -> object:
        response = real(self, *args, **kwargs)  # type: ignore[arg-type]
        pins.append(response.pin)
        return response

    monkeypatch.setattr(FamilyGroups, "_issue_pin", keep)
    demo_story.main()

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Demo story ready" in captured.out
    assert SECRET_KEY not in output
    assert JWT_SECRET not in output
    assert pins and pins[0] not in output
    assert not re.search(r"password", output, re.IGNORECASE)
    for user in admin.users.values():
        assert user["id"] not in output


def test_no_password_or_role_is_ever_written_to_supabase(admin: FakeSupabaseAdmin) -> None:
    before = {login: dict(user) for login, user in admin.users.items()}
    demo_story.main()
    assert admin.writes == []
    assert admin.users == before


def test_simulation_dates_stay_out_of_the_family_feed(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    demo_story.main()
    today = local_date(datetime.now(UTC))
    for senior in ("Mdm Lim", "Mr Tan"):
        group_id = _group_id(client, admin, "sarah", senior)
        entries = client.get(
            f"/v1/groups/{group_id}/activity", headers=_headers(admin, "sarah")
        ).json()["entries"]
        assert entries
        for entry in entries:
            at = datetime.fromisoformat(entry["at"]).date()
            assert abs((at - today).days) <= 5
            assert entry["kind"] not in {"suggestion", "intervention"}
            if entry["on_date"] is not None:
                on_date = date.fromisoformat(entry["on_date"])
                assert abs((on_date - today).days) <= 14


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_output_survives_an_encoding_without_unicode_punctuation(
    admin: FakeSupabaseAdmin, monkeypatch: pytest.MonkeyPatch, encoding: str
) -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    demo_story.main()
    out.flush()
    assert b"Demo story ready" in out.buffer.getvalue()
