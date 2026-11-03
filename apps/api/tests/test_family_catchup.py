"""`GET /v1/groups/{id}/catch-up`: who may read it, and what it is built from."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _onboard,
    client,  # noqa: F401 - pytest fixture
    repo,  # noqa: F401 - pytest fixture
)

OWNER = "family-a"


def _catch_up(client: TestClient, group_id: str, sub: str = OWNER, **params: object):  # noqa: F811
    return client.get(f"/v1/groups/{group_id}/catch-up", params=params, headers=_headers(sub))


def test_a_member_gets_a_catch_up_without_a_model(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    response = _catch_up(client, group_id)
    assert response.status_code == 200, response.text
    body = response.json()
    # The test settings leave the flag off: Care+ assembles the catch-up itself, and says so.
    assert body["mode"] == "fallback_disabled"
    assert body["model"] is None
    assert body["summary"]
    assert body["steps"] == []
    # Your own actions (creating the group) are not news to you.
    assert body["new_updates"] == 0


def test_since_counts_only_what_happened_after_it(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    client.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Eye check-up",
            "kind": "medical",
            "date": (datetime.now(UTC) + timedelta(days=3)).date().isoformat(),
            "start": "09:30",
            "end": "10:30",
        },
        headers=_headers(OWNER),
    )
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    body = _catch_up(client, group_id, since=future).json()
    assert body["new_updates"] == 0
    assert body["visits_needing_someone"] == 1
    assert any("Eye check-up" in line for line in body["highlights"])


def test_the_senior_and_outsiders_cannot_read_it(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    assert _catch_up(client, group_id, "senior-1").status_code == 403
    _onboard(client, "family-z", "family", "Stranger")
    assert _catch_up(client, group_id, "family-z").status_code == 404
