"""Stored simulation snapshots written before a contract field existed.

`advance()` persists the whole `AdvanceResponse` in `SimulationEventRow.response_json` and the
idempotent `event_id` replay re-validates it (`latest_advance` and `simulation_history`, the other
two read paths, went with their routes in step 7). A snapshot written before
`PersonState.decided_by_gate` existed (an offline SQLite file that outlived a code update) has no
gate, and re-validating it raised a pydantic `ValidationError`. That is a `ValueError`, so the
app-wide handler reported it as a 422 carrying the raw pydantic text, and the web told a demo
operator to start an API that was already running.

These tests pin the replacement behaviour:

- a read that must return the full snapshot refuses honestly (no invented gate) with a classified
  `stored_state_incompatible` error the web can offer a demo reset for;
- no raw validation text ever reaches a client, for this or any other server-side schema failure.

A separate failure mode: `response_json` text that is not valid JSON at all. SQLAlchemy's JSON
type decodes it while fetching the row, so `json.JSONDecodeError` used to escape as a bare
`ValueError` and reach the same app-wide 422 handler with the raw decode error text. It is
classified the same way as an outdated shape, and never leaks the corrupted text or the decoder's
message to a client.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import text as sql_text

from silverloop.config import Settings
from silverloop.db_models import DailyMetricRow, SimulationEventRow
from silverloop.error_responses import INTERNAL_ERROR_MESSAGE
from silverloop.main import create_app
from silverloop.models import PolicyGate, ServerErrorBody, ServerErrorCode
from silverloop.sql_repository import SqlAlchemyRepository
from silverloop.stored_state import StoredStateIncompatible

EVENT_ID = "legacy-event-1"
UNDECODABLE_EVENT_ID = "undecodable-event-1"
UNDECODABLE_JSON_TEXT = "{not json"


def _strip_decided_by_gate(repository: SqlAlchemyRepository) -> None:
    """Rewrite every stored snapshot as it was before `decided_by_gate` was added to the contract.

    Direct SQL, because no product action can write an older contract's shape.
    """
    with repository.sessions.begin() as session:
        for row in session.scalars(select(SimulationEventRow)):
            payload: dict[str, Any] = dict(row.response_json)
            state = dict(payload["state"])
            state.pop("decided_by_gate")
            payload["state"] = state
            row.response_json = payload


@pytest.fixture
def legacy_repository(repository: SqlAlchemyRepository) -> SqlAlchemyRepository:
    repository.advance("activity_declines", event_id=EVENT_ID)
    _strip_decided_by_gate(repository)
    return repository


def _corrupt_response_json(repository: SqlAlchemyRepository) -> None:
    """Overwrite every stored snapshot's `response_json` with text that is not valid JSON at all.

    Raw SQL, bypassing the ORM's JSON type on write, the same way a hand-corrupted row or a
    storage-layer truncation would arrive: no product action can write text that isn't JSON. The
    test schema (`create_schema_for_tests`) has no append-only trigger on `simulation_events` --
    unlike the Alembic-migrated schema -- so a plain `UPDATE` is enough here.
    """
    with repository.sessions.begin() as session:
        session.execute(
            sql_text("UPDATE simulation_events SET response_json = :raw"),
            {"raw": UNDECODABLE_JSON_TEXT},
        )


@pytest.fixture
def undecodable_repository(repository: SqlAlchemyRepository) -> SqlAlchemyRepository:
    repository.advance("activity_declines", event_id=UNDECODABLE_EVENT_ID)
    _corrupt_response_json(repository)
    return repository


@pytest.fixture
def undecodable_app(
    undecodable_repository: SqlAlchemyRepository, auth_disabled_settings: Settings
) -> FastAPI:
    return create_app(
        undecodable_repository, settings=auth_disabled_settings, migrate_on_start=False
    )


@pytest.fixture
def undecodable_client(undecodable_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(undecodable_app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def app(legacy_repository: SqlAlchemyRepository, auth_disabled_settings: Settings) -> FastAPI:
    return create_app(legacy_repository, settings=auth_disabled_settings, migrate_on_start=False)


@pytest.fixture
def legacy_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _assert_no_framework_text(body: object) -> None:
    text = str(body).lower()
    for leaked in (
        "validation error",
        "pydantic",
        "field required",
        "decided_by_gate",
        "8000",
        "jsondecodeerror",
        "expecting property name",
        "not json",
    ):
        assert leaked not in text, f"{leaked!r} leaked into a client error body: {body!r}"


# ── Repository ───────────────────────────────────────────────────────────────────────────────


def test_idempotent_replay_of_a_legacy_snapshot_is_classified(
    legacy_repository: SqlAlchemyRepository,
) -> None:
    with pytest.raises(StoredStateIncompatible):
        legacy_repository.advance("activity_declines", event_id=EVENT_ID)


def test_stored_state_incompatible_is_not_a_value_error() -> None:
    # Routes catch `ValueError` locally and return it as a 422 with `str(exc)`; this must not be
    # swallowed by those catches.
    assert not issubclass(StoredStateIncompatible, ValueError)


def test_a_current_snapshot_still_round_trips(repository: SqlAlchemyRepository) -> None:
    created = repository.advance("activity_declines", event_id="current-1")

    replayed = repository.advance("activity_declines", event_id="current-1")

    assert replayed == created
    assert replayed.state.decided_by_gate in set(PolicyGate)


# ── Undecodable stored JSON ─────────────────────────────────────────────────────────────────────
#
# `response_json` text that is not valid JSON at all (not merely an outdated shape). SQLAlchemy's
# JSON type decodes it while fetching the row, before any pydantic model runs, so the failure
# is a `json.JSONDecodeError` at the query call site, not inside `load_stored_advance`. It must
# be classified exactly like a schema mismatch.


def test_idempotent_replay_of_undecodable_json_is_classified(
    undecodable_repository: SqlAlchemyRepository,
) -> None:
    with pytest.raises(StoredStateIncompatible):
        undecodable_repository.advance("activity_declines", event_id=UNDECODABLE_EVENT_ID)


# ── API ──────────────────────────────────────────────────────────────────────────────────────


def test_advance_replay_route_returns_a_classified_error(legacy_client: TestClient) -> None:
    response = legacy_client.post(
        "/v1/simulation/advance", json={"event": "activity_declines", "event_id": EVENT_ID}
    )

    assert response.status_code == 500
    assert response.json()["code"] == "stored_state_incompatible"
    _assert_no_framework_text(response.json())


def test_resetting_the_demo_recovers(legacy_client: TestClient) -> None:
    assert legacy_client.post("/v1/demo/reset").status_code == 200

    response = legacy_client.post(
        "/v1/simulation/advance", json={"event": "activity_declines", "event_id": EVENT_ID}
    )

    assert response.status_code == 200, response.text


def test_advance_replay_route_classifies_undecodable_json(undecodable_client: TestClient) -> None:
    response = undecodable_client.post(
        "/v1/simulation/advance",
        json={"event": "activity_declines", "event_id": UNDECODABLE_EVENT_ID},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "stored_state_incompatible"
    _assert_no_framework_text(response.json())


def test_resetting_the_demo_recovers_from_undecodable_json(undecodable_client: TestClient) -> None:
    assert undecodable_client.post("/v1/demo/reset").status_code == 200

    response = undecodable_client.post(
        "/v1/simulation/advance",
        json={"event": "activity_declines", "event_id": UNDECODABLE_EVENT_ID},
    )

    assert response.status_code == 200, response.text


class _Strict(BaseModel):
    required: int


def test_a_server_side_validation_error_is_internal_not_a_422(app: FastAPI) -> None:
    @app.get("/test-only/server-validation-error")
    def _boom() -> None:
        _Strict.model_validate({})

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/test-only/server-validation-error")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    _assert_no_framework_text(response.json())


def test_a_response_model_failure_is_internal_without_raw_text(app: FastAPI) -> None:
    @app.get("/test-only/response-validation-error", response_model=_Strict)
    def _bad_response() -> dict[str, str]:
        return {"required": "not a number"}

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/test-only/response-validation-error")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    _assert_no_framework_text(response.json())


def test_a_validation_error_inside_a_route_s_own_value_error_catch_is_still_internal(
    repository: SqlAlchemyRepository, auth_disabled_settings: Settings
) -> None:
    """`POST /v1/simulation/advance` turns a domain `ValueError` into a 422 locally. A pydantic
    `ValidationError` is a `ValueError` too, so that catch used to swallow a corrupt stored row and
    answer 422 with the raw validation text; it must reach the classified 500 instead."""
    sentinel = "SENTINEL-CORRUPT-CONTEXT"
    repository.advance("activity_declines", event_id="corrupt-context-0")
    with repository.sessions.begin() as session:
        for row in session.scalars(select(DailyMetricRow)):
            row.context_json = {"rainy": sentinel}
    app = create_app(repository, settings=auth_disabled_settings, migrate_on_start=False)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post(
            "/v1/simulation/advance",
            json={"event": "activity_declines", "event_id": "corrupt-context-1"},
        )

    assert response.status_code == 500, response.text
    body = response.json()
    assert body == {
        "code": "internal_error",
        "message": INTERNAL_ERROR_MESSAGE,
        "detail": INTERNAL_ERROR_MESSAGE,
    }
    ServerErrorBody.model_validate(body)
    _assert_no_framework_text(body)
    assert sentinel.lower() not in response.text.lower()
    assert "errors.pydantic.dev" not in response.text


def test_every_route_declares_the_classified_500_body(legacy_client: TestClient) -> None:
    spec = legacy_client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert schemas["ServerErrorCode"]["enum"] == [code.value for code in ServerErrorCode]
    assert set(schemas["ServerErrorBody"]["required"]) == {"code", "message", "detail"}
    for route in (
        ("post", "/v1/simulation/advance"),
        ("post", "/v1/demo/reset"),
        ("get", "/v1/people/{person_id}/state"),
        ("get", "/v1/interventions"),
        ("get", "/v1/groups/{group_id}/calendar"),
    ):
        assert route[1] in spec["paths"], route
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            declared = operation["responses"].get("500")
            assert declared is not None, (method, path)
            assert declared["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ServerErrorBody"
            }, (method, path)


def test_request_validation_is_still_a_422(legacy_client: TestClient) -> None:
    response = legacy_client.post("/v1/simulation/advance", json={"event": 12})

    assert response.status_code == 422
