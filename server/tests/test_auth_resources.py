"""Resource-scoping tests — person ownership, cross-person access, mapping."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

JWT_SECRET = "resource-test-secret"
SUPABASE_URL = "https://project.supabase.co"


def _token(sub: str, role: str = "senior") -> str:
    return jwt.encode(
        {
            "sub": sub,
            "iss": SUPABASE_URL + "/auth/v1",
            "aud": "authenticated",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "app_metadata": {"role": role},
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _bearer(sub: str, role: str = "senior") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub, role)}"}


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    r = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    r.create_schema_for_tests()
    r.reset()
    return r


def _make_client(repo: SqlAlchemyRepository) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=JWT_SECRET,
    )
    app = create_app(repo, settings=settings, migrate_on_start=False)
    return TestClient(app, raise_server_exceptions=False)


# ── Unmapped senior gets 403 ──────────────────────────────────────────────────


def test_senior_without_person_link_gets_403(repo: SqlAlchemyRepository) -> None:
    client = _make_client(repo)
    resp = client.get("/v1/people/mdm-lim/state", headers=_bearer("unmapped-user"))
    assert resp.status_code == 403


# ── Mapped senior can access their person ────────────────────────────────────


def test_mapped_senior_accesses_own_person(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice", "mdm-lim", "test")
    client = _make_client(repo)
    resp = client.get("/v1/people/mdm-lim/state", headers=_bearer("alice"))
    assert resp.status_code == 200


# ── Cross-person path returns 404 not 403 ─────────────────────────────────────


def test_senior_wrong_person_path_returns_404(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice", "mdm-lim", "test")
    client = _make_client(repo)
    resp = client.get("/v1/people/other-person/state", headers=_bearer("alice"))
    assert resp.status_code == 404


def test_mapped_senior_accesses_own_metrics(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice", "mdm-lim", "test")
    client = _make_client(repo)
    resp = client.get("/v1/people/mdm-lim/metrics", headers=_bearer("alice"))
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_senior_wrong_person_metrics_returns_404(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice", "mdm-lim", "test")
    client = _make_client(repo)
    resp = client.get("/v1/people/other-person/metrics", headers=_bearer("alice"))
    assert resp.status_code == 404


def test_senior_consent_wrong_person_returns_404(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice", "mdm-lim", "test")
    client = _make_client(repo)
    resp = client.post(
        "/v1/people/other-person/consent",
        headers=_bearer("alice"),
        json={"active": True, "reason": "Test."},
    )
    assert resp.status_code == 404


# ── Mapping uniqueness / idempotency ─────────────────────────────────────────


def test_upsert_person_link_is_idempotent(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice", "mdm-lim", "test")
    repo.upsert_person_link("alice", "mdm-lim", "test")  # second call must not raise
    assert repo.lookup_person_for_sub("alice") == "mdm-lim"


def test_lookup_returns_none_for_unknown_sub(repo: SqlAlchemyRepository) -> None:
    assert repo.lookup_person_for_sub("nobody") is None


# ── Actor ID written to audit evidence ────────────────────────────────────────


def test_consent_records_real_actor_sub(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice-sub", "mdm-lim", "test")
    client = _make_client(repo)
    resp = client.post(
        "/v1/people/mdm-lim/consent",
        headers=_bearer("alice-sub"),
        json={"active": False, "reason": "Test withdrawal."},
    )
    assert resp.status_code == 200
    audit_actor = resp.json()["audit_event"]["actor"]
    assert audit_actor == "alice-sub"


def test_outcome_records_real_actor_sub(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("alice-sub", "mdm-lim", "test")

    # Generate an intervention via demo operator
    demo_settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
    )
    demo_app = create_app(repo, settings=demo_settings, migrate_on_start=False)
    demo_client = TestClient(demo_app, raise_server_exceptions=False)
    advance = demo_client.post("/v1/simulation/advance", json={"event": "activity_declines"})
    assert advance.status_code == 200
    intervention = advance.json().get("created_intervention")
    if intervention is None:
        pytest.skip("No intervention created for this advance event")

    # Record outcome as authenticated senior
    auth_client = _make_client(repo)
    resp = auth_client.post(
        f"/v1/interventions/{intervention['intervention_id']}/outcome",
        headers=_bearer("alice-sub"),
        json={"outcome": "accepted"},
    )
    assert resp.status_code == 200
    assert resp.json()["audit_event"]["actor"] == "alice-sub"


# ── Demo reset response shape ─────────────────────────────────────────────────


def test_reset_response_contains_checksum(repo: SqlAlchemyRepository) -> None:
    demo_settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
    )
    app = create_app(repo, settings=demo_settings, migrate_on_start=False)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/v1/demo/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert "seed" in data
    assert "scenario_version" in data
    assert "fixture_checksum" in data
    assert len(data["fixture_checksum"]) == 16


def test_reset_checksum_is_deterministic(repo: SqlAlchemyRepository) -> None:
    demo_settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
    )
    app = create_app(repo, settings=demo_settings, migrate_on_start=False)
    client = TestClient(app, raise_server_exceptions=False)
    first = client.post("/v1/demo/reset").json()["fixture_checksum"]
    second = client.post("/v1/demo/reset").json()["fixture_checksum"]
    assert first == second
