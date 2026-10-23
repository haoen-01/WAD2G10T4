"""The `/v1/people/{person_id}/baseline-confirmation` route, exercised over real HTTP.

`test_baseline_confirmation_repository.py` pins the repository behaviour directly; this pins the
route wiring in `main.py` -- status codes, and that the state returned over HTTP reflects the same
re-anchoring the repository test already proved.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _decline_until_pending(client: TestClient, *, limit: int = 60) -> dict:
    payload: dict | None = None
    for index in range(limit):
        response = client.post(
            "/v1/simulation/advance",
            json={"event": "activity_declines", "event_id": f"api-decline-{index}"},
        )
        assert response.status_code == 200
        payload = response.json()
        if payload["state"]["pending_baseline_confirmation"] is not None:
            return payload
    raise AssertionError(f"pending_baseline_confirmation never appeared within {limit} days")


def test_deciding_with_nothing_pending_returns_404(client: TestClient) -> None:
    response = client.post("/v1/people/mdm-lim/baseline-confirmation", json={"decision": "confirm"})
    assert response.status_code == 404
    assert "detail" in response.json()


def test_confirming_over_http_re_anchors_the_reference(client: TestClient) -> None:
    payload = _decline_until_pending(client)
    rolling_median = payload["state"]["baseline"]["median_steps"]

    response = client.post("/v1/people/mdm-lim/baseline-confirmation", json={"decision": "confirm"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "confirm"
    assert body["reference_steps"] == rolling_median
    assert "audit_event" in body

    state = client.get("/v1/people/mdm-lim/state").json()
    assert state["baseline"]["reference_steps"] == rolling_median
    assert state["baseline"]["effective_median_steps"] == state["baseline"]["median_steps"]
    assert state["pending_baseline_confirmation"] is None

    # Answering a second time now finds nothing pending.
    replay = client.post("/v1/people/mdm-lim/baseline-confirmation", json={"decision": "confirm"})
    assert replay.status_code == 404


def test_declining_over_http_leaves_the_clamp_bound(client: TestClient) -> None:
    payload = _decline_until_pending(client)
    reference_before = payload["state"]["baseline"]["reference_steps"]
    effective_before = payload["state"]["baseline"]["effective_median_steps"]

    response = client.post("/v1/people/mdm-lim/baseline-confirmation", json={"decision": "decline"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "decline"
    assert body["reference_steps"] == reference_before

    state = client.get("/v1/people/mdm-lim/state").json()
    assert state["baseline"]["reference_steps"] == reference_before
    assert state["baseline"]["effective_median_steps"] == effective_before
    assert state["pending_baseline_confirmation"] is None


def test_an_invalid_decision_value_is_rejected(client: TestClient) -> None:
    _decline_until_pending(client)
    response = client.post("/v1/people/mdm-lim/baseline-confirmation", json={"decision": "maybe"})
    assert response.status_code == 422
