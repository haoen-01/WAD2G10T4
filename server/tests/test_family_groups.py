"""Accounts and family groups: sign up, link a senior with their PIN, join with approval."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from silverloop import family_groups
from silverloop.config import Settings
from silverloop.family_groups import SENIOR_LINK_TTL
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

JWT_SECRET = "family-test-secret-key-at-least-32-bytes"
SUPABASE_URL = "https://project.supabase.co"


def _headers(sub: str, role: str | None = None) -> dict[str, str]:
    """A Supabase token. No role is a self-registered account; its role lives in `accounts`."""
    claims: dict = {
        "sub": sub,
        "iss": SUPABASE_URL + "/auth/v1",
        "aud": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "app_metadata": {"role": role} if role else {},
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


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


def _onboard(client: TestClient, sub: str, role: str, name: str) -> dict:
    response = client.post(
        "/v1/me/onboard", json={"role": role, "display_name": name}, headers=_headers(sub)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _senior_pin(client: TestClient, sub: str) -> str:
    response = client.post("/v1/me/link-pin", headers=_headers(sub))
    assert response.status_code == 200, response.text
    return response.json()["pin"]


def _group_with_owner(client: TestClient) -> str:
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    _onboard(client, "family-a", "family", "Wei Ling")
    response = client.post(
        "/v1/groups",
        json={"senior_pin": _senior_pin(client, "senior-1"), "relationship": "Daughter"},
        headers=_headers("family-a"),
    )
    assert response.status_code == 201, response.text
    return response.json()["group_id"]


def _join_pin(client: TestClient, group_id: str, sub: str = "family-a") -> str:
    response = client.post(f"/v1/groups/{group_id}/join-pin", headers=_headers(sub))
    assert response.status_code == 200, response.text
    return response.json()["pin"]


# ── Sign-up ───────────────────────────────────────────────────────────────────


def test_a_new_account_must_choose_a_role_before_anything_else(client: TestClient) -> None:
    me = client.get("/v1/me", headers=_headers("new-user"))
    assert me.status_code == 200
    assert me.json()["needs_onboarding"] is True
    assert me.json()["role"] is None
    assert client.get("/v1/auth/me", headers=_headers("new-user")).status_code == 403


def test_a_senior_gets_their_own_record_with_synthetic_activity(client: TestClient) -> None:
    me = _onboard(client, "senior-1", "senior", "Mdm Tan")
    assert me["role"] == "senior"
    assert me["display_name"] == "Mdm Tan"
    person_id = me["person_id"]
    assert person_id

    state = client.get(f"/v1/people/{person_id}/state", headers=_headers("senior-1"))
    assert state.status_code == 200, state.text
    assert state.json()["display_name"] == "Mdm Tan"
    metrics = client.get(f"/v1/people/{person_id}/metrics", headers=_headers("senior-1"))
    assert metrics.status_code == 200
    assert metrics.json()
    assert {row["source"] for row in metrics.json()} == {"synthetic"}


def test_an_account_chooses_its_role_only_once(client: TestClient) -> None:
    _onboard(client, "family-a", "family", "Wei Ling")
    again = client.post(
        "/v1/me/onboard",
        json={"role": "senior", "display_name": "Wei Ling"},
        headers=_headers("family-a"),
    )
    assert again.status_code == 409
    provisioned = client.post(
        "/v1/me/onboard",
        json={"role": "family", "display_name": "X"},
        headers=_headers("coordinator-1", role="coordinator"),
    )
    assert provisioned.status_code == 409


def test_roles_keep_to_their_own_routes(client: TestClient) -> None:
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    _onboard(client, "family-a", "family", "Wei Ling")
    assert client.post("/v1/me/link-pin", headers=_headers("family-a")).status_code == 403
    create = client.post(
        "/v1/groups",
        json={"senior_pin": "123456", "relationship": "Son"},
        headers=_headers("senior-1"),
    )
    assert create.status_code == 403


# ── Creating a group with the senior's PIN ────────────────────────────────────


def test_the_senior_pin_creates_the_group_and_its_owner(client: TestClient) -> None:
    group_id = _group_with_owner(client)
    group = client.get(f"/v1/groups/{group_id}", headers=_headers("family-a")).json()
    assert group["senior_name"] == "Mdm Tan"
    [owner] = group["members"]
    assert owner["role"] == "owner"
    assert owner["status"] == "active"
    assert owner["is_me"] is True
    assert owner["display_name"] == "Wei Ling"

    me = client.get("/v1/me", headers=_headers("family-a")).json()
    assert [(g["group_id"], g["my_status"]) for g in me["groups"]] == [(group_id, "active")]


def test_a_senior_pin_works_once_and_a_senior_has_one_group(client: TestClient) -> None:
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    _onboard(client, "family-a", "family", "Wei Ling")
    _onboard(client, "family-b", "family", "Jun")
    pin = _senior_pin(client, "senior-1")
    first = client.post(
        "/v1/groups",
        json={"senior_pin": pin, "relationship": "Daughter"},
        headers=_headers("family-a"),
    )
    assert first.status_code == 201
    reused = client.post(
        "/v1/groups", json={"senior_pin": pin, "relationship": "Son"}, headers=_headers("family-b")
    )
    assert reused.status_code == 400
    second = client.post(
        "/v1/groups",
        json={"senior_pin": _senior_pin(client, "senior-1"), "relationship": "Son"},
        headers=_headers("family-b"),
    )
    assert second.status_code == 409


def test_a_new_senior_pin_replaces_the_old_one(client: TestClient) -> None:
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    _onboard(client, "family-a", "family", "Wei Ling")
    old = _senior_pin(client, "senior-1")
    new = _senior_pin(client, "senior-1")
    if old == new:  # one in a million: the same digits were drawn twice
        return
    stale = client.post(
        "/v1/groups", json={"senior_pin": old, "relationship": "Son"}, headers=_headers("family-a")
    )
    assert stale.status_code == 400


def test_a_senior_pin_lasts_ten_minutes(client: TestClient) -> None:
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    before = datetime.now(UTC)
    response = client.post("/v1/me/link-pin", headers=_headers("senior-1"))
    assert response.status_code == 200, response.text
    expires_at = datetime.fromisoformat(response.json()["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    assert (
        timedelta(minutes=9, seconds=55) < expires_at - before <= timedelta(minutes=10, seconds=5)
    )


def test_an_expired_senior_pin_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    _onboard(client, "family-a", "family", "Wei Ling")
    pin = _senior_pin(client, "senior-1")
    later = datetime.now(UTC) + SENIOR_LINK_TTL + timedelta(seconds=1)
    monkeypatch.setattr(family_groups, "_utcnow", lambda: later)
    response = client.post(
        "/v1/groups", json={"senior_pin": pin, "relationship": "Son"}, headers=_headers("family-a")
    )
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_pins_are_six_ascii_digits(client: TestClient) -> None:
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    pin = _senior_pin(client, "senior-1")
    assert len(pin) == 6 and pin.isascii() and pin.isdigit()
    _onboard(client, "family-a", "family", "Wei Ling")
    for bad in ["12345", "1234567", "12a456", "١٢٣٤٥٦"]:
        response = client.post(
            "/v1/groups",
            json={"senior_pin": bad, "relationship": "Son"},
            headers=_headers("family-a"),
        )
        assert response.status_code == 422, bad


# ── Joining with approval ─────────────────────────────────────────────────────


def test_a_joiner_waits_for_approval(client: TestClient) -> None:
    group_id = _group_with_owner(client)
    _onboard(client, "family-b", "family", "Jun")
    joined = client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Son"},
        headers=_headers("family-b"),
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["my_status"] == "pending"
    assert joined.json()["senior_name"] == "Mdm Tan"
    # Pending: cannot see the group or invite anyone yet.
    assert client.get(f"/v1/groups/{group_id}", headers=_headers("family-b")).status_code == 404
    assert (
        client.post(f"/v1/groups/{group_id}/join-pin", headers=_headers("family-b")).status_code
        == 404
    )

    group = client.get(f"/v1/groups/{group_id}", headers=_headers("family-a")).json()
    pending = next(m for m in group["members"] if m["status"] == "pending")
    assert pending["display_name"] == "Jun"
    approved = client.post(
        f"/v1/groups/{group_id}/members/{pending['member_id']}/approve",
        headers=_headers("family-a"),
    )
    assert approved.status_code == 200
    assert {m["status"] for m in approved.json()["members"]} == {"active"}
    assert client.get(f"/v1/groups/{group_id}", headers=_headers("family-b")).status_code == 200


def test_a_declined_request_is_removed_and_can_ask_again(client: TestClient) -> None:
    group_id = _group_with_owner(client)
    _onboard(client, "family-b", "family", "Jun")
    pin = _join_pin(client, group_id)
    client.post(
        "/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=_headers("family-b")
    )
    group = client.get(f"/v1/groups/{group_id}", headers=_headers("family-a")).json()
    pending = next(m for m in group["members"] if m["status"] == "pending")
    declined = client.post(
        f"/v1/groups/{group_id}/members/{pending['member_id']}/decline",
        headers=_headers("family-a"),
    )
    assert declined.status_code == 200
    assert len(declined.json()["members"]) == 1
    again = client.post(
        "/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=_headers("family-b")
    )
    assert again.status_code == 200


def test_joining_twice_is_refused(client: TestClient) -> None:
    group_id = _group_with_owner(client)
    _onboard(client, "family-b", "family", "Jun")
    pin = _join_pin(client, group_id)
    body = {"pin": pin, "relationship": "Son"}
    assert (
        client.post("/v1/groups/join", json=body, headers=_headers("family-b")).status_code == 200
    )
    assert (
        client.post("/v1/groups/join", json=body, headers=_headers("family-b")).status_code == 409
    )


def test_only_active_members_can_approve(client: TestClient) -> None:
    group_id = _group_with_owner(client)
    _onboard(client, "family-b", "family", "Jun")
    _onboard(client, "family-c", "family", "Mei")
    pin = _join_pin(client, group_id)
    for sub in ("family-b", "family-c"):
        client.post(
            "/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=_headers(sub)
        )
    group = client.get(f"/v1/groups/{group_id}", headers=_headers("family-a")).json()
    c = next(m for m in group["members"] if m["display_name"] == "Mei")
    # B is still pending, so cannot let C in; an outsider cannot either.
    _onboard(client, "outsider", "family", "Stranger")
    for sub in ("family-b", "outsider"):
        response = client.post(
            f"/v1/groups/{group_id}/members/{c['member_id']}/approve", headers=_headers(sub)
        )
        assert response.status_code == 404


def test_repeated_wrong_pins_lock_pin_entry(client: TestClient) -> None:
    group_id = _group_with_owner(client)
    _onboard(client, "family-b", "family", "Jun")
    real = _join_pin(client, group_id)
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        response = client.post(
            "/v1/groups/join",
            json={"pin": wrong, "relationship": "Son"},
            headers=_headers("family-b"),
        )
        assert response.status_code == 400
    locked = client.post(
        "/v1/groups/join", json={"pin": real, "relationship": "Son"}, headers=_headers("family-b")
    )
    assert locked.status_code == 429


# ── Sign-in off (the offline demo) ────────────────────────────────────────────


def test_the_offline_demo_has_a_family_already_in_mdm_lims_group(
    repo: SqlAlchemyRepository,
) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
    )
    with TestClient(create_app(repo, settings=settings, migrate_on_start=False)) as demo:
        family = demo.get("/v1/me").json()
        assert family["role"] == "family"
        assert [g["person_id"] for g in family["groups"]] == ["mdm-lim"]

        senior = demo.get("/v1/me", headers={"X-Demo-Sub": "demo-senior"}).json()
        assert senior["role"] == "senior"
        assert senior["person_id"] == "mdm-lim"

        group_id = family["groups"][0]["group_id"]
        pin = demo.post(f"/v1/groups/{group_id}/join-pin").json()["pin"]
        newcomer = {"X-Demo-Sub": "demo-family-2"}
        joined = demo.post(
            "/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=newcomer
        )
        assert joined.json()["my_status"] == "pending"
