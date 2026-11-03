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

A route whose `person_id` instead comes from `current_user.person_id` (never a path or query
parameter -- `/v1/interventions`) always resolves to `DEMO_PERSON_ID` under disabled auth, so a
*non-existent* person can never reach it through this fixture (its person_id is derived from an
authenticated identity, not attacker- or caller-controlled input). What *is* reachable, and is
exactly as realistic a failure -- a freshly authenticated person whose data has not been seeded
yet -- is covered by deactivating `DEMO_PERSON_ID`'s own active run and hitting it directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from silverloop.db_models import ScenarioRunRow
from silverloop.fixtures import DEMO_PERSON_ID
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
    """`/v1/interventions` never takes a person_id from the caller; under disabled auth it always
    resolves to `DEMO_PERSON_ID`. The equivalent failure here is `DEMO_PERSON_ID` itself never
    having been seeded for a run.
    """
    _deactivate_active_run(repository, DEMO_PERSON_ID)

    interventions = client.get("/v1/interventions")
    assert interventions.status_code == 409, interventions.text
