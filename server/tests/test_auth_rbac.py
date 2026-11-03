"""Role-based access control tests — every protected route × every role."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

# ── Helpers ───────────────────────────────────────────────────────────────────


JWT_SECRET = "rbac-test-secret-key"
SUPABASE_URL = "https://project.supabase.co"


def _token(role: str, sub: str = "user-001") -> str:
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


def _bearer(role: str, sub: str = "user-001") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role, sub)}"}


@pytest.fixture
def repo_with_link() -> SqlAlchemyRepository:
    repo = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repo.create_schema_for_tests()
    repo.reset()
    repo.upsert_person_link("user-001", "mdm-lim", "test")
    return repo


@pytest.fixture
def auth_client(repo_with_link: SqlAlchemyRepository) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=JWT_SECRET,
    )
    app = create_app(repo_with_link, settings=settings, migrate_on_start=False)
    return TestClient(app, raise_server_exceptions=False)


# ── /v1/auth/me ───────────────────────────────────────────────────────────────


def test_me_senior(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/auth/me", headers=_bearer("senior")).status_code == 200


def test_me_coordinator(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/auth/me", headers=_bearer("coordinator")).status_code == 200


def test_me_demo_operator(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/auth/me", headers=_bearer("demo_operator")).status_code == 200


def test_me_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/auth/me").status_code == 401


# ── /v1/people/{id}/state ─────────────────────────────────────────────────────


def test_state_senior_ok(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/people/mdm-lim/state", headers=_bearer("senior")).status_code == 200


def test_state_coordinator_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/people/mdm-lim/state", headers=_bearer("coordinator"))
    assert response.status_code == 403


def test_state_demo_operator_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/people/mdm-lim/state", headers=_bearer("demo_operator"))
    assert response.status_code == 403


def test_state_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/people/mdm-lim/state").status_code == 401


# ── /v1/people/{id}/consent ───────────────────────────────────────────────────


def test_consent_senior_ok(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/v1/people/mdm-lim/consent",
        headers=_bearer("senior"),
        json={"active": True, "reason": "Re-enabling consent."},
    )
    assert resp.status_code == 200


def test_consent_coordinator_forbidden(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/v1/people/mdm-lim/consent",
        headers=_bearer("coordinator"),
        json={"active": True, "reason": "x"},
    )
    assert resp.status_code == 403


def test_consent_demo_operator_forbidden(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/v1/people/mdm-lim/consent",
        headers=_bearer("demo_operator"),
        json={"active": True, "reason": "x"},
    )
    assert resp.status_code == 403


# ── /v1/simulation/advance ────────────────────────────────────────────────────


def test_advance_demo_operator_ok(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/v1/simulation/advance",
        headers=_bearer("demo_operator"),
        json={"event": "activity_declines"},
    )
    assert resp.status_code == 200


def test_advance_senior_forbidden(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/v1/simulation/advance",
        headers=_bearer("senior"),
        json={"event": "activity_declines"},
    )
    assert resp.status_code == 403


def test_advance_coordinator_forbidden(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/v1/simulation/advance",
        headers=_bearer("coordinator"),
        json={"event": "activity_declines"},
    )
    assert resp.status_code == 403


def test_advance_unauthenticated(auth_client: TestClient) -> None:
    resp = auth_client.post("/v1/simulation/advance", json={"event": "activity_declines"})
    assert resp.status_code == 401


# ── /v1/interventions ─────────────────────────────────────────────────────────


def test_interventions_senior_ok(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/interventions", headers=_bearer("senior")).status_code == 200


def test_interventions_coordinator_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/interventions", headers=_bearer("coordinator")).status_code == 403


def test_interventions_demo_operator_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/interventions", headers=_bearer("demo_operator")).status_code == 403


# ── /v1/demo/reset ────────────────────────────────────────────────────────────


def test_reset_demo_operator_ok(auth_client: TestClient) -> None:
    resp = auth_client.post("/v1/demo/reset", headers=_bearer("demo_operator"))
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert "fixture_checksum" in data


def test_reset_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.post("/v1/demo/reset", headers=_bearer("senior")).status_code == 403


def test_reset_coordinator_forbidden(auth_client: TestClient) -> None:
    assert auth_client.post("/v1/demo/reset", headers=_bearer("coordinator")).status_code == 403


def test_reset_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.post("/v1/demo/reset").status_code == 401


# ── /v1/demo/reset in production ─────────────────────────────────────────────


def test_reset_disabled_in_production(repo_with_link: SqlAlchemyRepository) -> None:
    settings = Settings(
        app_env="production",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=JWT_SECRET,
    )
    app = create_app(repo_with_link, settings=settings, migrate_on_start=False)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/v1/demo/reset", headers=_bearer("demo_operator"))
    assert resp.status_code == 403


# ── auth-disabled offline mode ────────────────────────────────────────────────


def test_auth_disabled_all_routes_work_without_token(
    repo_with_link: SqlAlchemyRepository,
) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
    )
    app = create_app(repo_with_link, settings=settings, migrate_on_start=False)
    c = TestClient(app, raise_server_exceptions=False)

    assert c.get("/v1/people/mdm-lim/state").status_code == 200
    assert c.get("/v1/interventions").status_code == 200
    assert c.post("/v1/simulation/advance", json={"event": "activity_declines"}).status_code == 200
    assert c.post("/v1/demo/reset").status_code == 200
