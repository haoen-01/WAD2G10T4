"""`GET /v1/groups/{id}/catch-up`: who may read it, and what it is built from."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from silverloop import family_routes as routes
from silverloop.config import Settings
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _join_pin,
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


def test_a_pending_member_cannot_read_it(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    _onboard(client, "family-b", "family", "Jun")
    joined = client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Son"},
        headers=_headers("family-b"),
    )
    assert joined.json()["my_status"] == "pending"
    assert _catch_up(client, group_id, "family-b").status_code == 404


def test_past_the_agent_limit_the_answer_is_still_given_without_a_model(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The flag is on, but the stand-ins below never call a provider: they record whether the
    # route let the agent run, then answer as Care+ does without a model.
    app = client.app
    app.state.settings = app.state.settings.model_copy(  # type: ignore[attr-defined]
        update={"llm_enabled": True, "agent_rate_per_10_min": 2}
    )
    allowed: list[tuple[str, bool]] = []

    def spy(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def run(context: Any, settings: Settings) -> Any:
            allowed.append((name, settings.llm_enabled))
            return real(context, settings.model_copy(update={"llm_enabled": False}))

        return run

    monkeypatch.setattr(routes, "catch_up", spy("catch_up", routes.catch_up))
    monkeypatch.setattr(routes, "my_day", spy("my_day", routes.my_day))
    monkeypatch.setattr(routes, "draft_appointment", spy("draft", routes.draft_appointment))
    group_id = _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]

    assert _catch_up(client, group_id).status_code == 200
    assert client.get(f"/v1/people/{person_id}/my-day", headers=_headers(OWNER)).status_code == 200
    over = client.post(
        f"/v1/groups/{group_id}/appointments/draft",
        json={"text": "lunch tmr 12pm"},
        headers=_headers(OWNER),
    )
    assert over.status_code == 200
    assert over.json()["mode"] == "fallback_disabled"
    # One limit across the three agent routes, per person: the senior's own is untouched.
    assert (
        client.get(f"/v1/people/{person_id}/my-day", headers=_headers("senior-1")).status_code
        == 200
    )
    assert allowed == [("catch_up", True), ("my_day", True), ("draft", False), ("my_day", True)]
