"""`GET /v1/coordinator/queue` hygiene (audit-H finding 8).

Before this change, `list_cases()` had no status filter and ordered purely by `opened_at.desc()`
(with a `priority` column hard-coded to `4` for every case, so it contributed nothing) -- a
resolved case interleaved with open/acknowledged ones forever. These tests pin the fix: the
default view excludes resolved cases, `?status=` opens that up on request, and the ordering is
open before acknowledged before resolved, newest first within each status. The filtering and
ordering live in `main.py` (`_parse_queue_statuses`/`_ordered_queue`), a route-local post-process
over `repository.list_cases()` -- that method's own signature and "return everything" default are
unchanged (see `test_case_dedup.py`, `test_consent_boundary.py`, `test_multi_person.py`, which all
rely on it).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

PERSON_B = "person-b"
PERSON_C = "person-c"

_SETTINGS = dict(
    app_env="test",
    database_url="sqlite+pysqlite:///:memory:",
    silverloop_runtime_profile="offline",
    auth_enabled=False,
    llm_enabled=False,
)


def _three_person_client() -> TestClient:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_SETTINGS))
    repository.create_schema_for_tests()
    repository.reset()
    repository.reset(person_id=PERSON_B, allow_new_person=True)
    repository.reset(person_id=PERSON_C, allow_new_person=True)
    application = create_app(repository, settings=Settings(**_SETTINGS), migrate_on_start=False)
    return TestClient(application)


def _open_a_case(client: TestClient, person_id: str | None = None) -> str:
    event = {"event": "activity_declines"}
    if person_id is not None:
        event["person_id"] = person_id
    payload = None
    for _ in range(3):
        payload = client.post("/v1/simulation/advance", json=event).json()
    assert payload is not None and payload["created_case"] is not None
    return str(payload["created_case"]["case_id"])


def test_default_queue_excludes_resolved_cases() -> None:
    client = _three_person_client()
    try:
        open_id = _open_a_case(client)
        _open_a_case(client, PERSON_B)

        client.post(
            f"/v1/cases/{open_id}/review",
            json={"status": "resolved", "reviewer_note": "Closed for this test."},
        )

        default_queue = client.get("/v1/coordinator/queue").json()
        assert {case["person_id"] for case in default_queue} == {PERSON_B}
        assert all(case["status"] != "resolved" for case in default_queue)
    finally:
        client.close()


def test_status_query_param_opens_up_resolved_cases_on_request() -> None:
    client = _three_person_client()
    try:
        open_id = _open_a_case(client)
        client.post(
            f"/v1/cases/{open_id}/review",
            json={"status": "resolved", "reviewer_note": "Closed for this test."},
        )

        resolved_only = client.get("/v1/coordinator/queue", params={"status": "resolved"}).json()
        assert [case["case_id"] for case in resolved_only] == [open_id]

        everything = client.get(
            "/v1/coordinator/queue", params={"status": "open,acknowledged,resolved"}
        ).json()
        assert open_id in [case["case_id"] for case in everything]
    finally:
        client.close()


def test_queue_orders_open_before_acknowledged_before_resolved_newest_first() -> None:
    client = _three_person_client()
    try:
        resolved_id = _open_a_case(client, DEMO_PERSON_ID)
        client.post(
            f"/v1/cases/{resolved_id}/review",
            json={"status": "resolved", "reviewer_note": "Closed for this test."},
        )
        acknowledged_id = _open_a_case(client, PERSON_B)
        client.post(
            f"/v1/cases/{acknowledged_id}/review",
            json={"status": "acknowledged", "reviewer_note": "Acknowledged for this test."},
        )
        open_id = _open_a_case(client, PERSON_C)

        everything = client.get(
            "/v1/coordinator/queue", params={"status": "open,acknowledged,resolved"}
        ).json()
        assert [case["case_id"] for case in everything] == [
            open_id,
            acknowledged_id,
            resolved_id,
        ]
    finally:
        client.close()


def test_queue_rejects_an_unknown_status_value() -> None:
    client = _three_person_client()
    try:
        response = client.get("/v1/coordinator/queue", params={"status": "urgent"})
        assert response.status_code == 422
    finally:
        client.close()


def test_queue_no_longer_reports_a_case_priority_score() -> None:
    """`priority` stays on the contract (`ReviewCase.priority`), but every case is opened with the
    same hard-coded value (`sql_repository.py::_create_case`) -- it carries no signal, so the
    queue does not sort by it and the card no longer displays it (see `review-card.tsx`)."""
    client = _three_person_client()
    try:
        case_id = _open_a_case(client)
        case = client.get("/v1/coordinator/queue").json()
        assert next(c["priority"] for c in case if c["case_id"] == case_id) == 4
    finally:
        client.close()
