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


# ── /v1/simulation/events ─────────────────────────────────────────────────────


def test_events_demo_operator_ok(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/simulation/events", headers=_bearer("demo_operator"))
    assert response.status_code == 200


def test_events_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/simulation/events", headers=_bearer("senior")).status_code == 403


def test_events_senior_forbidden_even_with_person_id_query_param(auth_client: TestClient) -> None:
    """A senior cannot use `?person_id=` to read someone else's simulation trail either -- the
    role gate applies before the query parameter is ever consulted.
    """
    response = auth_client.get(
        "/v1/simulation/events",
        params={"person_id": "mdm-lim"},
        headers=_bearer("senior"),
    )
    assert response.status_code == 403


# ── /v1/simulation/latest ─────────────────────────────────────────────────────


def test_latest_demo_operator_ok(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/simulation/latest", headers=_bearer("demo_operator"))
    assert response.status_code == 200


def test_latest_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/simulation/latest", headers=_bearer("senior")).status_code == 403


# ── /v1/simulation/history ────────────────────────────────────────────────────


def test_history_demo_operator_ok(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/simulation/history", headers=_bearer("demo_operator"))
    assert response.status_code == 200


def test_history_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/simulation/history", headers=_bearer("senior")).status_code == 403


def test_history_senior_forbidden_even_with_person_id_query_param(auth_client: TestClient) -> None:
    """A senior cannot use `?person_id=` to read another person's decision-trace history --
    the role gate applies before the query parameter is ever consulted.
    """
    response = auth_client.get(
        "/v1/simulation/history",
        params={"person_id": "mdm-lim"},
        headers=_bearer("senior"),
    )
    assert response.status_code == 403


# ── /v1/interventions ─────────────────────────────────────────────────────────


def test_interventions_senior_ok(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/interventions", headers=_bearer("senior")).status_code == 200


def test_interventions_coordinator_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/interventions", headers=_bearer("coordinator")).status_code == 403


def test_interventions_demo_operator_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/interventions", headers=_bearer("demo_operator")).status_code == 403


# ── /v1/programmes ────────────────────────────────────────────────────────────


def test_programmes_all_roles_ok(auth_client: TestClient) -> None:
    for role in ("senior", "coordinator", "demo_operator"):
        resp = auth_client.get("/v1/programmes", headers=_bearer(role))
        assert resp.status_code == 200, f"Failed for role={role}"


def test_programmes_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/programmes").status_code == 401


# ── /v1/coordinator/queue ─────────────────────────────────────────────────────


def test_coordinator_queue_coordinator_ok(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/queue", headers=_bearer("coordinator"))
    assert response.status_code == 200


def test_coordinator_queue_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/coordinator/queue", headers=_bearer("senior")).status_code == 403


def test_coordinator_queue_demo_operator_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/queue", headers=_bearer("demo_operator"))
    assert response.status_code == 403


# ── /v1/coordinator/people ────────────────────────────────────────────────────
#
# The roster names people and says a band word about each of them. It is role-gated exactly like
# the queue is -- a senior must never read a list of other seniors, and a demo operator's job is
# the simulation, not the caseload.


def test_coordinator_people_coordinator_ok(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/people", headers=_bearer("coordinator"))
    assert response.status_code == 200


def test_coordinator_people_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/coordinator/people", headers=_bearer("senior")).status_code == 403


def test_coordinator_people_demo_operator_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/people", headers=_bearer("demo_operator"))
    assert response.status_code == 403


# ── /v1/coordinator/priorities ────────────────────────────────────────────────
#
# The care-priority board orders people and says why. Gated exactly like the roster.


def test_coordinator_priorities_coordinator_ok(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/priorities", headers=_bearer("coordinator"))
    assert response.status_code == 200


def test_coordinator_priorities_senior_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/priorities", headers=_bearer("senior"))
    assert response.status_code == 403


def test_coordinator_priorities_demo_operator_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/priorities", headers=_bearer("demo_operator"))
    assert response.status_code == 403


def test_coordinator_priorities_for_one_person_gated_like_the_board(
    auth_client: TestClient,
) -> None:
    path = "/v1/coordinator/priorities?person_id=mdm-lim"
    assert auth_client.get(path, headers=_bearer("coordinator")).status_code == 200
    assert auth_client.get(path, headers=_bearer("senior")).status_code == 403
    assert auth_client.get(path, headers=_bearer("demo_operator")).status_code == 403


# ── /v1/coordinator/metrics ───────────────────────────────────────────────────
#
# The caseload's totals. Gated exactly like the roster it sums over.


def test_coordinator_metrics_coordinator_ok(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/metrics", headers=_bearer("coordinator"))
    assert response.status_code == 200


def test_coordinator_metrics_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/coordinator/metrics", headers=_bearer("senior")).status_code == 403


def test_coordinator_metrics_demo_operator_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/coordinator/metrics", headers=_bearer("demo_operator"))
    assert response.status_code == 403


def test_coordinator_metrics_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/coordinator/metrics").status_code == 401


# ── /v1/coordinator/people/{id}/activity-relative ────────────────────────────
#
# The case page's recent-activity strip. Coordinator only: the senior's own metrics and state
# routes stay senior-only, and this is not a door into them for anyone else either.

_ACTIVITY_RELATIVE = "/v1/coordinator/people/mdm-lim/activity-relative"


def test_activity_relative_coordinator_ok(auth_client: TestClient) -> None:
    response = auth_client.get(_ACTIVITY_RELATIVE, headers=_bearer("coordinator"))
    assert response.status_code == 200, response.text
    assert response.json()["person_id"] == "mdm-lim"


@pytest.mark.parametrize("role", ["senior", "demo_operator"])
def test_activity_relative_other_roles_forbidden(auth_client: TestClient, role: str) -> None:
    # `user-001` is linked to mdm-lim: even the senior whose record it is uses their own routes.
    assert auth_client.get(_ACTIVITY_RELATIVE, headers=_bearer(role)).status_code == 403


def test_activity_relative_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.get(_ACTIVITY_RELATIVE).status_code == 401


# ── /v1/coordinator/people/{id}/review-threshold ─────────────────────────────
#
# The review setting and its decisions are a coordinator's, like the rest of the care-team surface.


_THRESHOLD = "/v1/coordinator/people/mdm-lim/review-threshold"
_STALE_DAY = "2020-01-01"
# (method, path, body, what a coordinator gets on the freshly reset demo person)
_THRESHOLD_ROUTES: list[tuple[str, str, dict[str, object] | None, int]] = [
    ("GET", _THRESHOLD, None, 200),
    ("GET", f"{_THRESHOLD}/replay?severity_pct=40&persistence_days=4", None, 200),
    (
        "POST",
        f"{_THRESHOLD}/proposals/nope/approve",
        {"cause_confirmed": True, "shown_on_day": _STALE_DAY},
        404,
    ),
    ("POST", f"{_THRESHOLD}/proposals/nope/reject", {"reason": "other"}, 404),
    (
        "POST",
        f"{_THRESHOLD}/manual",
        {
            "threshold": {"severity_pct": 40, "persistence_days": 4},
            "note": "By hand.",
            "shown_on_day": _STALE_DAY,
        },
        409,
    ),
    ("POST", f"{_THRESHOLD}/confirm-starting", {"shown_on_day": _STALE_DAY}, 409),
    ("POST", f"{_THRESHOLD}/decisions/nope/reconfirm", {"shown_on_day": _STALE_DAY}, 404),
]


@pytest.mark.parametrize(("method", "path", "body", "expected"), _THRESHOLD_ROUTES)
def test_review_threshold_routes_coordinator_reaches_the_route(
    auth_client: TestClient,
    method: str,
    path: str,
    body: dict[str, object] | None,
    expected: int,
) -> None:
    response = auth_client.request(method, path, json=body, headers=_bearer("coordinator"))
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("role", ["senior", "demo_operator"])
@pytest.mark.parametrize(("method", "path", "body", "expected"), _THRESHOLD_ROUTES)
def test_review_threshold_routes_other_roles_forbidden(
    auth_client: TestClient,
    role: str,
    method: str,
    path: str,
    body: dict[str, object] | None,
    expected: int,
) -> None:
    response = auth_client.request(method, path, json=body, headers=_bearer(role))
    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path", "body", "expected"), _THRESHOLD_ROUTES)
def test_review_threshold_routes_unauthenticated(
    auth_client: TestClient,
    method: str,
    path: str,
    body: dict[str, object] | None,
    expected: int,
) -> None:
    assert auth_client.request(method, path, json=body).status_code == 401


# ── /v1/evaluator/people/{id}/senior-home ────────────────────────────────────
#
# The Demo Tools senior-screen preview: a demo operator reads any persona's senior home. It is not
# an identity path into the senior's own screen, so a senior cannot use it, and neither can a
# coordinator.


def test_senior_home_preview_demo_operator_ok(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/v1/evaluator/people/mdm-lim/senior-home", headers=_bearer("demo_operator")
    )
    assert response.status_code == 200
    assert response.json()["person_id"] == "mdm-lim"


def test_senior_home_preview_coordinator_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/v1/evaluator/people/mdm-lim/senior-home", headers=_bearer("coordinator")
    )
    assert response.status_code == 403


def test_senior_home_preview_senior_forbidden(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/v1/evaluator/people/mdm-lim/senior-home", headers=_bearer("senior")
    )
    assert response.status_code == 403


def test_senior_home_preview_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/evaluator/people/mdm-lim/senior-home").status_code == 401


def test_senior_home_preview_persona_not_in_this_database_is_not_found(
    auth_client: TestClient,
) -> None:
    response = auth_client.get(
        "/v1/evaluator/people/mdm-wong/senior-home", headers=_bearer("demo_operator")
    )
    assert response.status_code == 404


# ── /v1/metrics ───────────────────────────────────────────────────────────────


def test_metrics_coordinator_ok(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/metrics", headers=_bearer("coordinator")).status_code == 200


def test_metrics_demo_operator_ok(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/metrics", headers=_bearer("demo_operator")).status_code == 200


def test_metrics_senior_forbidden(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/metrics", headers=_bearer("senior")).status_code == 403


def test_metrics_senior_forbidden_even_with_person_id_query_param(auth_client: TestClient) -> None:
    """A senior must not be able to read another (or even their own) person's metrics by
    supplying `?person_id=` -- the role gate blocks seniors from `/v1/metrics` outright,
    independent of the query parameter.
    """
    response = auth_client.get(
        "/v1/metrics",
        params={"person_id": "mdm-lim"},
        headers=_bearer("senior"),
    )
    assert response.status_code == 403


def test_metrics_coordinator_can_read_a_different_persons_metrics(auth_client: TestClient) -> None:
    """Coordinators and demo operators are staff roles with no `person_id` of their own -- unlike
    seniors, they are meant to see any person's metrics; that is the whole point of the role.
    """
    response = auth_client.get(
        "/v1/metrics",
        params={"person_id": "mdm-lim"},
        headers=_bearer("coordinator"),
    )
    assert response.status_code == 200


def test_metrics_unauthenticated(auth_client: TestClient) -> None:
    assert auth_client.get("/v1/metrics").status_code == 401


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
    assert c.get("/v1/programmes").status_code == 200
    assert c.get("/v1/coordinator/queue").status_code == 200
    assert c.get("/v1/metrics").status_code == 200
    assert c.post("/v1/simulation/advance", json={"event": "activity_declines"}).status_code == 200
    assert c.post("/v1/demo/reset").status_code == 200
