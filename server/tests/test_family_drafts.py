"""`POST /v1/groups/{id}/appointments/draft`: who may use it, and that it saves nothing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


def _draft(client: TestClient, group_id: str, text: str, sub: str = OWNER):  # noqa: F811
    return client.post(
        f"/v1/groups/{group_id}/appointments/draft", json={"text": text}, headers=_headers(sub)
    )


def test_a_member_gets_a_filled_in_form_and_nothing_is_saved(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    response = _draft(client, group_id, "Eye check-up tomorrow 10:30 to 11:30 at Bedok Polyclinic")
    assert response.status_code == 200, response.text
    body = response.json()
    # The test settings leave the flag off: a plain parser fills it in, and says so.
    assert body["mode"] == "fallback_disabled"
    assert body["source"] is None and body["model"] is None
    assert body["title"] == "Eye check-up"
    assert body["kind"] == "medical"
    assert (body["start"], body["end"]) == ("10:30", "11:30")
    assert body["location"] == "Bedok Polyclinic"
    assert body["date"] == (local_date(datetime.now(UTC)) + timedelta(days=1)).isoformat()
    assert body["missing"] == []

    calendar = client.get(f"/v1/groups/{group_id}/calendar", headers=_headers(OWNER)).json()
    assert calendar["appointments"] == []


def test_an_unrecognised_sentence_lists_what_is_missing(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    body = _draft(client, group_id, "kopi with John").json()
    assert body["title"] == "Kopi with John"
    assert set(body["missing"]) == {"date", "start", "end"}


def test_the_senior_and_outsiders_cannot_use_it(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    assert _draft(client, group_id, "lunch tmr 12pm", "senior-1").status_code == 403
    _onboard(client, "family-z", "family", "Stranger")
    assert _draft(client, group_id, "lunch tmr 12pm", "family-z").status_code == 404


def test_overlong_text_is_refused(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    assert _draft(client, group_id, "x" * 301).status_code == 422
