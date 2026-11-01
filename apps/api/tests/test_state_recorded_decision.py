"""`/state` after the contact cap: the decision recorded for the day, not a read-time artefact.

Display only. `advance` reads the live ladder, so each test also pins what it decides next.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from silverloop.context_question import QUESTION_ID
from silverloop.fixtures import DEMO_PERSON_ID

CAP_RATIONALE = ["Weekly contact cap reached; notification fatigue guard applied."]


def _advance(client: TestClient, event: str = "activity_declines") -> dict:
    response = client.post("/v1/simulation/advance", json={"event": event})
    assert response.status_code == 200, response.text
    return response.json()


def _state(client: TestClient) -> dict:
    response = client.get(f"/v1/people/{DEMO_PERSON_ID}/state")
    assert response.status_code == 200, response.text
    return response.json()


def _two_offers(client: TestClient) -> dict:
    _advance(client)
    second = _advance(client)
    assert second["state"]["last_decision"] == "programme_suggestion"
    return second


def _answer(client: TestClient, intervention_id: str, outcome: str) -> None:
    response = client.post(
        f"/v1/interventions/{intervention_id}/outcome", json={"outcome": outcome}
    )
    assert response.status_code == 200, response.text


def test_the_second_offer_reads_as_recorded_with_its_own_fields(client: TestClient) -> None:
    advanced = _two_offers(client)["state"]
    state = _state(client)
    for field in ("last_decision", "rationale", "decided_by_gate"):
        assert state[field] == advanced[field], field
    assert state["last_decision"] == "programme_suggestion"
    # `advance` decides before its own offer counts against the cap; `/state` matches the answer.
    assert (
        advanced["pending_question"] is not None,
        state["pending_question"],
        _try_to_answer(client),
    ) == (True, None, 404)


def _try_to_answer(client: TestClient) -> int:
    return client.post(
        f"/v1/people/{DEMO_PERSON_ID}/context-answer",
        json={"question_id": QUESTION_ID, "value": "resting"},
    ).status_code


def test_an_uncapped_day_offers_the_question_and_accepts_the_answer(client: TestClient) -> None:
    assert _advance(client)["state"]["last_decision"] == "gentle_nudge"
    state = _state(client)
    assert state["decided_by_gate"] != "contact_cap"
    assert state["pending_question"]["question_id"] == QUESTION_ID
    assert _try_to_answer(client) == 200
    assert _state(client)["pending_question"] is None


def test_a_capped_day_offers_no_question_the_answer_path_would_refuse(client: TestClient) -> None:
    """The offer still reads as recorded, but the live ladder is at the cap and refuses an answer,
    so nothing may invite one. An answer feeds the ladder, so it must not get past the cap."""
    _two_offers(client)
    state = _state(client)
    assert state["last_decision"] == "programme_suggestion"
    assert state["pending_question"] is None
    assert _try_to_answer(client) == 404
    # The refusal stays a refusal: the cap goes on holding the next low day.
    _advance(client, "recovery")
    assert _advance(client)["state"]["decided_by_gate"] == "contact_cap"


@pytest.mark.parametrize("days", [1, 2, 3, 4])
def test_state_offers_a_question_exactly_when_the_answer_path_accepts_it(
    client: TestClient, days: int
) -> None:
    """The scenario 07 sequence, stopped on each day in turn."""
    for event in ["activity_declines", "activity_declines", "recovery", "activity_declines"][:days]:
        _advance(client, event)
    offered = _state(client)["pending_question"] is not None
    assert _try_to_answer(client) == (200 if offered else 404)


def test_a_decline_that_day_still_reads_as_recorded(client: TestClient) -> None:
    second = _two_offers(client)
    _answer(client, second["created_intervention"]["intervention_id"], "declined")
    assert _state(client)["last_decision"] == "programme_suggestion"


def test_revoking_consent_wins_live(client: TestClient) -> None:
    _two_offers(client)
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/consent", json={"active": False, "reason": "Opting out."}
    )
    assert response.status_code == 200, response.text
    state = _state(client)
    assert (state["last_decision"], state["decided_by_gate"]) == ("suppress", "consent")


def test_accepting_that_day_is_not_overwritten_by_the_recorded_offer(client: TestClient) -> None:
    """The cap is checked before the cooldown, so the live gate says `contact_cap` while the person
    is in their cooldown. It must read exactly as it did: nothing new is going to them."""
    second = _two_offers(client)
    _answer(client, second["created_intervention"]["intervention_id"], "accepted")
    state = _state(client)
    assert (state["last_decision"], state["decided_by_gate"]) == ("suppress", "contact_cap")
    assert state["rationale"] == CAP_RATIONALE


def test_a_day_the_cap_really_suppressed_still_reads_suppress(client: TestClient) -> None:
    _two_offers(client)
    _advance(client, "recovery")
    capped = _advance(client)["state"]
    assert (capped["last_decision"], capped["decided_by_gate"]) == ("suppress", "contact_cap")
    state = _state(client)
    assert (state["last_decision"], state["decided_by_gate"]) == ("suppress", "contact_cap")
    assert state["rationale"] == CAP_RATIONALE


def test_a_rain_day_reads_live(client: TestClient) -> None:
    _two_offers(client)
    _advance(client, "recovery")
    advanced = _advance(client, "rain_explains_decline")["state"]
    state = _state(client)
    assert state["decided_by_gate"] == advanced["decided_by_gate"] == "rain_context"
    assert state["last_decision"] == "no_action"


def test_reading_state_changes_nothing_advance_decides(client: TestClient) -> None:
    """The same days with and without a read between them, on the scenario 07 sequence."""
    events = ["activity_declines", "activity_declines", "recovery", "activity_declines"]
    decided = []
    for event in events:
        decided.append(_advance(client, event)["state"]["last_decision"])
        _state(client)
    assert decided == ["gentle_nudge", "programme_suggestion", "no_action", "suppress"]
