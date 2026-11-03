"""The demo login setup script, against an in-memory stand-in for the Supabase admin API."""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError

from silverloop import setup_demo_accounts as setup
from silverloop.config import Settings
from silverloop.db_models import AccountRow, CareGroupRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

JWT_SECRET = "setup-test-secret-key-at-least-32-bytes"
SUPABASE_URL = "https://project.supabase.co"

FAMILY = {
    "sarah@silverloop.demo": "Sarah",
    "john@silverloop.demo": "John",
    "emily@silverloop.demo": "Emily",
    "weiming@silverloop.demo": "Wei Ming",
    "aisha@silverloop.demo": "Aisha",
}
PASSWORD_ENVS = {
    "SENIOR_PASSWORD": "pw-senior-Zq81",
    "COORDINATOR_PASSWORD": "pw-coordinator-Zq82",
    "DEMO_OPERATOR_PASSWORD": "pw-operator-Zq83",
    "SARAH_PASSWORD": "pw-sarah-Zq84",
    "JOHN_PASSWORD": "pw-john-Zq85",
    "EMILY_PASSWORD": "pw-emily-Zq86",
    "WEIMING_PASSWORD": "pw-weiming-Zq87",
    "AISHA_PASSWORD": "pw-aisha-Zq88",
}
OVERRIDABLE_EMAILS = {
    "SENIOR_EMAIL": "senior@silverloop.demo",
    "COORDINATOR_EMAIL": "coordinator@silverloop.demo",
    "DEMO_OPERATOR_EMAIL": "demo-operator@silverloop.demo",
}


class FakeSupabaseAdmin:
    """Keeps users like the admin API: `app_metadata` merges on update, and null removes a key."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}

    def by_email(self, email: str) -> dict:
        return next(user for user in self.users.values() if user["email"] == email)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/users":
            page = int(request.url.params["page"])
            size = int(request.url.params["per_page"])
            listed = list(self.users.values())[(page - 1) * size : page * size]
            return httpx.Response(200, json={"users": listed})
        body = json.loads(request.content)
        if request.method == "POST" and path == "/users":
            user = {
                "id": str(uuid4()),
                "email": body["email"],
                "password": body["password"],
                "app_metadata": dict(body.get("app_metadata", {})),
            }
            self.users[user["id"]] = user
            return httpx.Response(200, json=user)
        if request.method == "PUT" and path.startswith("/users/"):
            user = self.users[path.removeprefix("/users/")]
            user["password"] = body["password"]
            for key, value in body.get("app_metadata", {}).items():
                if value is None:
                    user["app_metadata"].pop(key, None)
                else:
                    user["app_metadata"][key] = value
            return httpx.Response(200, json=user)
        return httpx.Response(404, json={"msg": "unexpected call"})


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch, repo: SqlAlchemyRepository) -> FakeSupabaseAdmin:
    """Points the script at the stand-in and the test database; nothing can reach a network."""
    fake = FakeSupabaseAdmin()
    monkeypatch.setattr(
        setup,
        "_supabase_admin",
        lambda *_: httpx.Client(
            transport=httpx.MockTransport(fake.handle), base_url="https://admin.invalid"
        ),
    )
    monkeypatch.setattr(setup, "SqlAlchemyRepository", lambda _url: repo)
    monkeypatch.setattr(
        setup, "Settings", lambda: SimpleNamespace(app_env="test", database_url="unused")
    )
    monkeypatch.setattr(setup.sys, "argv", ["setup_demo_accounts"])
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "not-a-real-key")
    for name in OVERRIDABLE_EMAILS:
        monkeypatch.delenv(name, raising=False)
    for name, value in PASSWORD_ENVS.items():
        monkeypatch.setenv(name, value)
    return fake


@pytest.fixture
def client(repo: SqlAlchemyRepository) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=JWT_SECRET,
    )
    return TestClient(create_app(repo, settings=settings, migrate_on_start=False))


def _headers_for(user: dict) -> dict[str, str]:
    """The token Supabase would issue this user: its `app_metadata` is copied in as it stands."""
    claims = {
        "sub": user["id"],
        "iss": SUPABASE_URL + "/auth/v1",
        "aud": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "app_metadata": user["app_metadata"],
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def _account_count(repo: SqlAlchemyRepository) -> int:
    with repo.sessions() as session:
        return session.scalar(select(func.count()).select_from(AccountRow)) or 0


def _assert_all_family_accounts_exist(admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository) -> None:
    for email, name in FAMILY.items():
        user = admin.by_email(email)
        assert "role" not in user["app_metadata"]
        with repo.sessions() as session:
            row = session.get(AccountRow, user["id"])
            assert (row.role, row.display_name) == ("family", name)


@pytest.mark.parametrize(("email", "name"), FAMILY.items())
def test_each_family_login_is_a_working_family_account(
    admin: FakeSupabaseAdmin, client: TestClient, email: str, name: str
) -> None:
    setup.main()

    headers = _headers_for(admin.by_email(email))
    me = client.get("/v1/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["needs_onboarding"] is False
    assert me.json()["display_name"] == name
    assert me.json()["role"] == "family"
    assert me.json()["groups"] == []

    # What the sign-in form reads next: this decides which view the account may open.
    auth_me = client.get("/v1/auth/me", headers=headers)
    assert auth_me.status_code == 200, auth_me.text
    assert auth_me.json()["role"] == "family"
    # Already set up, exactly like someone who finished onboarding.
    onboard = client.post(
        "/v1/me/onboard", json={"role": "senior", "display_name": "Other"}, headers=headers
    )
    assert onboard.status_code == 409


def test_family_logins_carry_no_role_in_app_metadata(admin: FakeSupabaseAdmin) -> None:
    setup.main()
    for email in FAMILY:
        assert "role" not in admin.by_email(email)["app_metadata"]


def test_setup_creates_no_family_groups(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository
) -> None:
    with repo.sessions() as session:
        before = session.scalar(select(func.count()).select_from(CareGroupRow))
    setup.main()
    with repo.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CareGroupRow)) == before


def test_running_again_updates_rather_than_duplicates(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup.main()
    subs = {user["email"]: user["id"] for user in admin.users.values()}
    assert len(subs) == 8
    assert _account_count(repo) == 5

    monkeypatch.setenv("SARAH_PASSWORD", "pw-sarah-changed-Zq89")
    setup.main()

    assert {user["email"]: user["id"] for user in admin.users.values()} == subs
    assert _account_count(repo) == 5
    assert admin.by_email("sarah@silverloop.demo")["password"] == "pw-sarah-changed-Zq89"


def test_running_again_repairs_a_family_account_that_drifted(
    admin: FakeSupabaseAdmin, client: TestClient, repo: SqlAlchemyRepository
) -> None:
    setup.main()
    user = admin.by_email("weiming@silverloop.demo")
    user["app_metadata"]["role"] = "senior"
    with repo.sessions.begin() as session:
        row = session.get(AccountRow, user["id"])
        row.role = "senior"
        row.display_name = "Someone else"

    setup.main()

    me = client.get("/v1/me", headers=_headers_for(user)).json()
    assert (me["role"], me["display_name"]) == ("family", "Wei Ming")


def test_no_password_appears_in_output(
    admin: FakeSupabaseAdmin, capsys: pytest.CaptureFixture[str]
) -> None:
    setup.main()
    setup.main()  # both the create and the update path
    captured = capsys.readouterr()
    for password in PASSWORD_ENVS.values():
        assert password not in captured.out
        assert password not in captured.err


def test_typed_passwords_stay_hidden_and_a_blank_one_skips_the_account(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SARAH_PASSWORD")
    monkeypatch.delenv("JOHN_PASSWORD")
    prompts: list[str] = []

    def typed(prompt: str) -> str:
        prompts.append(prompt)
        return "pw-typed-Zq90" if "sarah@" in prompt else ""

    monkeypatch.setattr(setup.getpass, "getpass", typed)
    setup.main()

    captured = capsys.readouterr()
    assert "pw-typed-Zq90" not in captured.out + captured.err + "".join(prompts)
    assert admin.by_email("sarah@silverloop.demo")["password"] == "pw-typed-Zq90"
    assert not any(user["email"] == "john@silverloop.demo" for user in admin.users.values())
    assert _account_count(repo) == 4


def test_existing_demo_accounts_keep_their_role_in_app_metadata(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, client: TestClient
) -> None:
    for _ in range(2):
        setup.main()
        for email, role in {
            "senior@silverloop.demo": "senior",
            "coordinator@silverloop.demo": "coordinator",
            "demo-operator@silverloop.demo": "demo_operator",
        }.items():
            user = admin.by_email(email)
            assert user["app_metadata"] == {"role": role}
            auth_me = client.get("/v1/auth/me", headers=_headers_for(user))
            assert auth_me.json()["role"] == role
            with repo.sessions() as session:
                assert session.get(AccountRow, user["id"]) is None

    senior = admin.by_email("senior@silverloop.demo")
    assert repo.lookup_person_for_sub(senior["id"]) == DEMO_PERSON_ID


def test_a_family_email_override_cannot_take_over_a_real_account(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = {
        "id": "real-user",
        "email": "mei@example.com",
        "password": "her-own-password",
        "app_metadata": {"role": "coordinator"},
    }
    admin.users[real["id"]] = dict(real, app_metadata=dict(real["app_metadata"]))
    with repo.sessions.begin() as session:
        session.add(
            AccountRow(
                sub=real["id"],
                role="senior",
                display_name="Mei",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    monkeypatch.setenv("SARAH_EMAIL", real["email"])
    monkeypatch.setenv("JOHN_EMAIL", real["email"])

    setup.main()

    assert admin.users[real["id"]] == real
    with repo.sessions() as session:
        row = session.get(AccountRow, real["id"])
        assert (row.role, row.display_name) == ("senior", "Mei")
    _assert_all_family_accounts_exist(admin, repo)


def test_family_email_overrides_cannot_swap_two_family_accounts(
    admin: FakeSupabaseAdmin, repo: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SARAH_EMAIL", "john@silverloop.demo")
    monkeypatch.setenv("JOHN_EMAIL", "sarah@silverloop.demo")

    setup.main()

    _assert_all_family_accounts_exist(admin, repo)
    assert admin.by_email("sarah@silverloop.demo")["password"] == PASSWORD_ENVS["SARAH_PASSWORD"]
    assert admin.by_email("john@silverloop.demo")["password"] == PASSWORD_ENVS["JOHN_PASSWORD"]


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize(("env_key", "fixed_email"), OVERRIDABLE_EMAILS.items())
def test_a_blank_email_override_counts_as_unset(
    admin: FakeSupabaseAdmin,
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    fixed_email: str,
    blank: str,
) -> None:
    no_email = {"id": "phone-user", "email": "", "password": "theirs", "app_metadata": {}}
    admin.users[no_email["id"]] = dict(no_email, app_metadata={})
    monkeypatch.setenv(env_key, blank)

    setup.main()

    assert admin.users[no_email["id"]] == no_email
    assert admin.by_email(fixed_email)["id"] != no_email["id"]
    assert sum(user["email"].strip() == "" for user in admin.users.values()) == 1


def test_a_filled_in_override_still_applies_to_the_three_existing_accounts(
    admin: FakeSupabaseAdmin, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SENIOR_EMAIL", "other-senior@silverloop.demo")

    setup.main()

    assert admin.by_email("other-senior@silverloop.demo")["app_metadata"] == {"role": "senior"}
    assert not any(user["email"] == "senior@silverloop.demo" for user in admin.users.values())


# cp1252 is the redirected-output encoding on Windows, where the arrow crashed the run. It does have
# an ellipsis and an em dash, so strict ASCII is what proves those two are gone as well.
@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_output_survives_an_encoding_without_unicode_punctuation(
    admin: FakeSupabaseAdmin,
    repo: SqlAlchemyRepository,
    monkeypatch: pytest.MonkeyPatch,
    encoding: str,
) -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict")
    err = io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    # A blank typed password takes the "Skipping" line, which goes to stderr.
    monkeypatch.delenv("JOHN_PASSWORD")
    monkeypatch.setattr(setup.getpass, "getpass", lambda _prompt: "")

    setup.main()

    out.flush()
    assert b"Setup complete." in out.buffer.getvalue()
    err.flush()
    assert b"Skipping john@silverloop.demo" in err.buffer.getvalue()
    assert _account_count(repo) == 4


@pytest.mark.parametrize("missing", ["auth_user_person_links", "accounts"])
@pytest.mark.parametrize("error_type", [OperationalError, ProgrammingError])
def test_a_missing_table_gets_the_migration_message(
    admin: FakeSupabaseAdmin,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
    error_type: type[OperationalError] | type[ProgrammingError],
) -> None:
    """SQLite reports a missing table as OperationalError; psycopg as ProgrammingError."""

    class StubConnection:
        def __enter__(self) -> StubConnection:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            if f"FROM {missing} " in str(statement):
                raise error_type(str(statement), {}, Exception(f"no such table: {missing}"))

    monkeypatch.setattr(
        setup,
        "SqlAlchemyRepository",
        lambda _url: SimpleNamespace(engine=SimpleNamespace(connect=StubConnection)),
    )

    with pytest.raises(SystemExit) as exit_info:
        setup.main()

    assert exit_info.value.code == 1
    assert "alembic upgrade head" in capsys.readouterr().err
    assert admin.users == {}


def test_running_again_keeps_a_family_accounts_group_and_owner_role(
    admin: FakeSupabaseAdmin, client: TestClient
) -> None:
    setup.main()
    headers = _headers_for(admin.by_email("sarah@silverloop.demo"))
    created = client.post(
        "/v1/groups",
        json={"senior_name": "Mdm Tan", "relationship": "Daughter"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["group_id"]
    opened = client.post(f"/v1/groups/{group_id}/open", headers=headers)
    assert opened.status_code == 204, opened.text

    setup.main()

    me = client.get("/v1/me", headers=headers).json()
    assert [
        (group["group_id"], group["my_role"], group["last_opened"]) for group in me["groups"]
    ] == [(group_id, "owner", True)]


def test_production_is_refused_before_anything_is_touched(
    admin: FakeSupabaseAdmin, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        setup, "Settings", lambda: SimpleNamespace(app_env="production", database_url="unused")
    )
    with pytest.raises(SystemExit) as exit_info:
        setup.main()
    assert exit_info.value.code == 1
    assert "refusing to provision" in capsys.readouterr().err
    assert admin.users == {}


def test_allow_production_still_works(
    admin: FakeSupabaseAdmin, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        setup, "Settings", lambda: SimpleNamespace(app_env="production", database_url="unused")
    )
    monkeypatch.setattr(setup.sys, "argv", ["setup_demo_accounts", "--allow-production"])
    setup.main()
    assert len(admin.users) == 8
