"""Every route that reaches `SqlAlchemyRepository._active_run` must fail cleanly.

`_active_run` raises `KeyError(person_id)` for a person that does not exist, and
`RuntimeError("No active scenario run. ...")` for a person who exists but has never been reset /
seeded. Before this fix, several routes had no try/except at all and several more caught
`KeyError` but let `RuntimeError` fall straight through -- both produced a bare, undocumented
HTTP 500. These tests pin the app-level exception handlers in `main.py`
(`register_exception_handlers`) that now turn both into a clean, documented status: 404 for a
person that does not exist, 409 for one that exists but is not seeded for a run.

The `client` fixture runs with `auth_enabled=False`, under which `check_person_scope` is a no-op
(see its docstring in `main.py`) and every senior route accepts whatever `person_id` is in the
path or query string. That is exactly what is needed here: it lets these tests target arbitrary,
non-existent or not-yet-seeded person ids without having to fabricate a JWT per case.

Routes whose `person_id` instead comes from `current_user.person_id` (never a path or query
parameter -- `/v1/interventions`, `/v1/interventions/history`, `/v1/activities/search`) always
resolve to `DEMO_PERSON_ID` under disabled auth, so a *non-existent* person can never reach them
through this fixture (their person_id is derived from an authenticated identity, not attacker- or
caller-controlled input). What *is* reachable, and is exactly as realistic a failure -- a freshly
authenticated person whose data has not been seeded yet -- is covered by deactivating
`DEMO_PERSON_ID`'s own active run and hitting those three routes directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from silverloop.db_models import DecisionEvidenceRow, ReviewCaseRow, ScenarioRunRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import CaseStatus
from silverloop.sql_repository import SqlAlchemyRepository

NONEXISTENT_PERSON = "person-does-not-exist"
UNSEEDED_PERSON = "person-exists-no-active-run"


def _deactivate_active_run(repository: SqlAlchemyRepository, person_id: str) -> None:
    """Leave the `PersonRow` in place but retire their active run.

    This is the "exists but was never seeded for this database" state `_active_run` reports via
    `RuntimeError`, reproduced the same way `test_failure_paths.py` reproduces other row-level
    edge cases: direct SQL, not a repository method, because there is no product action that
    un-seeds a person -- it only happens to accounts nobody has run `pnpm seed` / demo reset for.
    """
    with repository.sessions.begin() as session:
        session.execute(
            update(ScenarioRunRow)
            .where(ScenarioRunRow.person_id == person_id, ScenarioRunRow.active.is_(True))
            .values(active=False)
        )


def _seed_unseeded_person(repository: SqlAlchemyRepository, person_id: str) -> None:
    repository.reset(person_id=person_id, allow_new_person=True)
    _deactivate_active_run(repository, person_id)


def _open_review_case_directly(repository: SqlAlchemyRepository, person_id: str) -> str:
    """Insert an open review case straight into the database, bypassing `advance()`.

    `advance()` -> sustained decline -> `coordinator_review` is the real way a case opens, but
    getting there also exercises `_create_intervention`'s candidate-preference-learner query,
    which is unrelated to this test and, at the time of writing, is being actively changed by
    other in-flight work elsewhere in the repository. This mirrors the direct-SQL setup pattern
    `test_failure_paths.py` already uses for other edge cases: what this test needs is a case row
    that exists and is open, not a faithful replay of how the decision ladder got there.
    """
    now = datetime.now(UTC)
    with repository.sessions.begin() as session:
        run = session.scalar(
            select(ScenarioRunRow).where(
                ScenarioRunRow.person_id == person_id, ScenarioRunRow.active.is_(True)
            )
        )
        assert run is not None, f"expected an active run for {person_id!r}"
        decision_id = f"decision_test_{uuid4().hex[:12]}"
        session.add(
            DecisionEvidenceRow(
                evidence_id=decision_id,
                run_id=run.run_id,
                person_id=person_id,
                observed_at=now,
                recorded_at=now,
                source="synthetic",
                fixture_classification="synthetic_fixture",
                confidence=0.9,
                policy_version="test",
                decision="coordinator_review",
                reasons_json=["testing"],
                input_event="activity_declines",
                quality_evidence_id="dq_test",
            )
        )
        case_id = f"case_test_{uuid4().hex[:12]}"
        session.add(
            ReviewCaseRow(
                case_id=case_id,
                run_id=run.run_id,
                person_id=person_id,
                decision_evidence_id=decision_id,
                title="Test review case",
                status=CaseStatus.OPEN.value,
                priority=3,
                opened_at=now,
                summary="Synthetic case for testing review-after-consent-revocation.",
                evidence_json=["testing"],
                recommendation="Review with the person.",
            )
        )
    return case_id


def _call(client: TestClient, method: str, path: str, body: dict | None):
    if method == "GET":
        return client.get(path)
    assert method == "POST"
    return client.post(path, json=body or {})


# ── Route tables ─────────────────────────────────────────────────────────────────────────────

# Routes scoped by a `{person_id}` path segment: (method, path template, request body or None).
PERSON_PATH_ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/v1/people/{person_id}/state", None),
    ("GET", "/v1/people/{person_id}/metrics", None),
    ("POST", "/v1/people/{person_id}/consent", {"active": False, "reason": "testing revocation"}),
    ("GET", "/v1/people/{person_id}/preferences", None),
    (
        "POST",
        "/v1/people/{person_id}/preferences/some-candidate-key",
        {"suppressed": True, "reason": "testing"},
    ),
    ("POST", "/v1/people/{person_id}/day-dispute", {"day": "2026-01-01", "accurate": True}),
    ("GET", "/v1/people/{person_id}/proposed-memories", None),
    (
        "POST",
        "/v1/people/{person_id}/context-answer",
        # A real `ContextAnswerValue`: the body has to get past request validation for this test
        # to reach the person-scope check it is actually about.
        {"question_id": "some-question", "value": "resting"},
    ),
    (
        "POST",
        "/v1/people/{person_id}/baseline-confirmation",
        {"decision": "decline"},
    ),
    ("GET", "/v1/people/{person_id}/goals", None),
    (
        "POST",
        "/v1/people/{person_id}/goals",
        {"kind": "get_out_more", "target_per_week": 3, "active": True},
    ),
    ("GET", "/v1/people/{person_id}/week", None),
    (
        "POST",
        "/v1/people/{person_id}/week",
        {"activity_id": "some-activity", "day": "2026-01-01"},
    ),
    ("GET", "/v1/people/{person_id}/replan-notices", None),
    ("GET", "/v1/coordinator/people/{person_id}/outreach-history", None),
    ("GET", "/v1/coordinator/people/{person_id}/activity-relative", None),
]

# Routes that take `person_id` as an optional query parameter instead of a path segment.
PERSON_QUERY_ROUTES: list[str] = [
    "/v1/metrics",
    "/v1/simulation/events",
    "/v1/simulation/latest",
    "/v1/simulation/history",
]


PERSON_PATH_ROUTE_IDS = [f"{method} {path}" for method, path, _ in PERSON_PATH_ROUTES]


# ── Non-existent person -> 404, never 500 ───────────────────────────────────────────────────


@pytest.mark.parametrize("method,path_template,body", PERSON_PATH_ROUTES, ids=PERSON_PATH_ROUTE_IDS)
def test_nonexistent_person_path_param_returns_404(
    client: TestClient, method: str, path_template: str, body: dict | None
) -> None:
    path = path_template.format(person_id=NONEXISTENT_PERSON)
    response = _call(client, method, path, body)
    assert response.status_code == 404, (
        f"{method} {path} -> {response.status_code} (expected 404): {response.text}"
    )
    assert response.headers["content-type"].startswith("application/json")
    assert "detail" in response.json()


@pytest.mark.parametrize("path", PERSON_QUERY_ROUTES)
def test_nonexistent_person_query_param_returns_404(client: TestClient, path: str) -> None:
    response = client.get(path, params={"person_id": NONEXISTENT_PERSON})
    assert response.status_code == 404, (
        f"GET {path}?person_id=... -> {response.status_code} (expected 404): {response.text}"
    )
    assert "detail" in response.json()


def test_nonexistent_person_via_simulation_advance_returns_404(client: TestClient) -> None:
    response = client.post(
        "/v1/simulation/advance",
        json={"event": "activity_declines", "person_id": NONEXISTENT_PERSON},
    )
    assert response.status_code == 404, response.text
    assert "detail" in response.json()


# ── Person exists, never seeded (no active run) -> 409, never 500 ──────────────────────────


@pytest.mark.parametrize("method,path_template,body", PERSON_PATH_ROUTES, ids=PERSON_PATH_ROUTE_IDS)
def test_unseeded_person_path_param_returns_409(
    client: TestClient,
    repository: SqlAlchemyRepository,
    method: str,
    path_template: str,
    body: dict | None,
) -> None:
    _seed_unseeded_person(repository, UNSEEDED_PERSON)
    path = path_template.format(person_id=UNSEEDED_PERSON)
    response = _call(client, method, path, body)
    assert response.status_code == 409, (
        f"{method} {path} -> {response.status_code} (expected 409): {response.text}"
    )
    assert "detail" in response.json()


@pytest.mark.parametrize("path", PERSON_QUERY_ROUTES)
def test_unseeded_person_query_param_returns_409(
    client: TestClient, repository: SqlAlchemyRepository, path: str
) -> None:
    _seed_unseeded_person(repository, UNSEEDED_PERSON)
    response = client.get(path, params={"person_id": UNSEEDED_PERSON})
    assert response.status_code == 409, (
        f"GET {path}?person_id=... -> {response.status_code} (expected 409): {response.text}"
    )
    assert "detail" in response.json()


def test_unseeded_person_via_simulation_advance_returns_409(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _seed_unseeded_person(repository, UNSEEDED_PERSON)
    response = client.post(
        "/v1/simulation/advance",
        json={"event": "activity_declines", "person_id": UNSEEDED_PERSON},
    )
    assert response.status_code == 409, response.text
    assert "detail" in response.json()


# ── Same failure mode, reached through the current-user-scoped routes ──────────────────────


def test_unseeded_current_user_scoped_routes_return_409(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """`/v1/interventions`, `/v1/interventions/history` and `/v1/activities/search` never take a
    person_id from the caller; under disabled auth they always resolve to `DEMO_PERSON_ID`. The
    equivalent failure here is `DEMO_PERSON_ID` itself never having been seeded for a run.
    """
    _deactivate_active_run(repository, DEMO_PERSON_ID)

    interventions = client.get("/v1/interventions")
    assert interventions.status_code == 409, interventions.text

    history = client.get("/v1/interventions/history")
    assert history.status_code == 409, history.text

    search = client.post("/v1/activities/search", json={"text": "something to do"})
    assert search.status_code == 409, search.text


# ── The two specific ValueError paths named in the audit ───────────────────────────────────


def test_plan_activity_outside_current_week_returns_422_not_500(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    # `plan_activity` validates the activity exists before it validates the day, so this needs a
    # real activity id -- a made-up one would surface "Activity not found" (404) first and never
    # exercise the day-range `ValueError` this test targets.
    activities = client.get("/v1/activities").json()
    assert activities, "expected the seeded catalogue to contain at least one activity"
    activity_id = activities[0]["activity_id"]

    current_day = repository.person_state().current_day
    week_starting = current_day - timedelta(days=current_day.weekday())
    outside_day = week_starting + timedelta(days=60)

    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week",
        json={"activity_id": activity_id, "day": outside_day.isoformat()},
    )

    assert response.status_code == 422, response.text
    assert "outside the week" in response.json()["detail"]


def test_review_case_after_consent_revocation_returns_422_not_500(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    case_id = _open_review_case_directly(repository, DEMO_PERSON_ID)

    # Revoking consent auto-closes every open case for this person (see
    # `_close_open_cases_for_consent`), but the case row itself survives -- reviewing it further
    # is what `review_case` rejects with `ValueError`.
    revoke = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/consent",
        json={"active": False, "reason": "withdrawing consent"},
    )
    assert revoke.status_code == 200, revoke.text

    review = client.post(
        f"/v1/cases/{case_id}/review",
        json={"status": "acknowledged", "reviewer_note": "reviewing after revocation"},
    )

    assert review.status_code == 422, review.text
    assert "consent is inactive" in review.json()["detail"].lower()
