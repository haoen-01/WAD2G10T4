"""`GET /v1/people/{id}/my-day`: who may read it, and what it is built from."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from silverloop.local_time import local_date
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _onboard,
    client,  # noqa: F401 - pytest fixture
    repo,  # noqa: F401 - pytest fixture
)

OWNER = "family-a"


def _my_day(client: TestClient, person_id: str, sub: str):  # noqa: F811
    return client.get(f"/v1/people/{person_id}/my-day", headers=_headers(sub))


def test_the_senior_hears_today_without_a_model(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    today = local_date(datetime.now(UTC)).isoformat()
    created = client.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Eye check-up",
            "kind": "medical",
            "date": today,
            "start": "23:00",
            "end": "23:30",
            "location": "Block 5 clinic",
            "notes": "Bring the old glasses",
        },
        headers=_headers(OWNER),
    )
    assert created.status_code == 201, created.text
    task = client.post(
        f"/v1/groups/{group_id}/tasks",
        json={"title": "Water the plants", "start_date": today, "time": "23:15"},
        headers=_headers(OWNER),
    )
    assert task.status_code == 201, task.text

    response = _my_day(client, person_id, "senior-1")
    assert response.status_code == 200, response.text
    body = response.json()
    # The test settings leave the flag off: Care+ reads the day itself, and says so.
    assert body["mode"] == "fallback_disabled"
    assert body["source"] is None and body["model"] is None
    assert body["steps"] == []
    assert body["appointments_today"] == 1
    assert body["reminders_total"] == 1 and body["reminders_done"] == 0
    assert "Mdm Tan" in body["script"]
    assert "Eye check-up at 11 pm" in body["script"]
    assert "Water the plants at 11:15 pm" in body["script"]
    # Notes and the place stay out of the script, as they stay out of the model's tools.
    assert "glasses" not in body["script"] and "clinic" not in body["script"]


def test_the_family_may_read_it_and_outsiders_may_not(client: TestClient) -> None:  # noqa: F811
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    assert _my_day(client, person_id, OWNER).status_code == 200
    _onboard(client, "family-z", "family", "Stranger")
    assert _my_day(client, person_id, "family-z").status_code == 404
