"""The response clock: unanswered outreach resolves itself, in the person's own days.

Before this existed an offer nobody answered stayed `proposed` forever. The loop trace read
"Waiting for the senior to accept, decline or give no response" indefinitely, the `no_response`
outcome and its half-weight learning rule were unreachable from any product path, and silence
spent the weekly contact budget while teaching the learner nothing. Everything here runs through
the FastAPI contract where a browser could reach it, and through the repository where the
behaviour is a property of `advance()` itself.

The companion change -- the weekly contact cap counted in simulated days rather than wall-clock
seconds -- is asserted at the end, because it is the same clock.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.learning import PreferenceLearner
from silverloop.sql_repository import RESPONSE_WINDOW_DAYS, SqlAlchemyRepository

DECLINE = "activity_declines"


def _advance(client: TestClient, event: str = DECLINE, event_id: str | None = None) -> dict:
    body: dict[str, object] = {"event": event}
    if event_id is not None:
        body["event_id"] = event_id
    response = client.post("/v1/simulation/advance", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _interventions_oldest_first(client: TestClient) -> list[dict]:
    response = client.get("/v1/interventions")
    assert response.status_code == 200, response.text
    return sorted(response.json(), key=lambda item: (item["created_at"], item["intervention_id"]))


def _current_day(client: TestClient) -> date:
    state = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()
    return date.fromisoformat(state["current_day"])


# ── The window ────────────────────────────────────────────────────────────────────────────────


def test_an_offer_stays_open_inside_its_window_and_says_when_it_closes(client: TestClient) -> None:
    first = _advance(client)["created_intervention"]
    assert first is not None
    day_one = _current_day(client)
    _advance(client)

    interventions = _interventions_oldest_first(client)
    assert [item["outcome"] for item in interventions] == [None, None]
    assert all(item["status"] == "proposed" for item in interventions)
    # The contract says on which simulated day the clock stops waiting -- outreach day plus the
    # window -- so a coordinator surface never has to know the constant.
    assert (
        interventions[0]["awaiting_reply_until"]
        == (day_one + timedelta(days=RESPONSE_WINDOW_DAYS)).isoformat()
    )
    assert (
        interventions[1]["awaiting_reply_until"]
        == (day_one + timedelta(days=1 + RESPONSE_WINDOW_DAYS)).isoformat()
    )


def test_an_unanswered_offer_is_closed_as_silence_once_the_window_passes(
    client: TestClient,
) -> None:
    for _ in range(3):
        _advance(client)

    first, second = _interventions_oldest_first(client)
    # Day 1's nudge was still open two simulated days later, so day 3's advance closed it.
    assert first["outcome"] == "no_response"
    assert first["status"] == "closed"
    assert first["awaiting_reply_until"] is None
    # Day 2's suggestion is still inside its window and still open.
    assert second["outcome"] is None
    assert second["status"] == "proposed"
    assert second["awaiting_reply_until"] is not None


def test_a_recorded_answer_is_never_overwritten_by_the_clock(client: TestClient) -> None:
    first = _advance(client)["created_intervention"]
    accepted = client.post(
        f"/v1/interventions/{first['intervention_id']}/outcome", json={"outcome": "accepted"}
    )
    assert accepted.status_code == 200, accepted.text

    for _ in range(3):
        _advance(client)

    resolved = next(
        item
        for item in _interventions_oldest_first(client)
        if item["intervention_id"] == first["intervention_id"]
    )
    assert resolved["outcome"] == "accepted"
    assert resolved["awaiting_reply_until"] is None
    # Exactly one outcome row: the person's own. Taking a suggestion up also starts the
    # acceptance cooldown (`ACCEPTED_OUTREACH_COOLDOWN_DAYS`), so the following days send nothing
    # new, and the clock never writes a second row against something already answered.
    metrics = client.get("/v1/metrics").json()
    assert metrics["outcomes"] == 1
    assert metrics["no_reply_recorded"] == 0


def test_withdrawn_offers_are_not_silence(client: TestClient) -> None:
    _advance(client)
    _advance(client, "consent_revoked")
    for _ in range(RESPONSE_WINDOW_DAYS):
        _advance(client, "consent_revoked")

    (withdrawn,) = _interventions_oldest_first(client)
    assert withdrawn["status"] == "withdrawn_consent_revoked"
    # An offer withdrawn when consent went was never received; nobody was silent about it.
    assert withdrawn["outcome"] is None
    assert withdrawn["awaiting_reply_until"] is None
    assert client.get("/v1/metrics").json()["no_reply_recorded"] == 0


def test_a_replayed_event_does_not_resolve_anything_twice(client: TestClient) -> None:
    for index in range(3):
        _advance(client, event_id=f"clock-replay-{index}")
    before = client.get("/v1/metrics").json()["outcomes"]

    _advance(client, event_id="clock-replay-2")

    assert client.get("/v1/metrics").json()["outcomes"] == before == 1


# ── What the resolution records ───────────────────────────────────────────────────────────────


def test_silence_is_audited_by_the_system_with_the_reason_it_fired(client: TestClient) -> None:
    first = _advance(client)["created_intervention"]
    _advance(client)
    third = _advance(client)

    events = client.get("/v1/simulation/events").json()
    resolution = next(
        event
        for event in events
        if event["event_type"] == "intervention_outcome_recorded"
        and event["detail"]["intervention_id"] == first["intervention_id"]
    )
    assert resolution["actor"] == "system"
    assert resolution["detail"]["outcome"] == "no_response"
    assert resolution["detail"]["resolved_by"] == "response_window"
    assert resolution["detail"]["response_window_days"] == RESPONSE_WINDOW_DAYS
    assert resolution["detail"]["reason"] is None
    # The day's own decision record names what the clock closed before it decided anything.
    assert third["audit_event"]["detail"]["unanswered_outreach_resolved"] == [
        first["intervention_id"]
    ]


def test_silence_moves_the_candidate_posterior_by_exactly_one_no_response(
    client: TestClient,
) -> None:
    first = _advance(client)["created_intervention"]
    candidate_key = first["candidate_key"]
    before = client.get("/v1/metrics").json()["candidate_preference_scores"][candidate_key]
    _advance(client)
    _advance(client)

    expected = PreferenceLearner()
    expected.record(candidate_key, "no_response")
    after = client.get("/v1/metrics").json()["candidate_preference_scores"][candidate_key]
    assert before == PreferenceLearner().expected_value(candidate_key)
    assert after == expected.expected_value(candidate_key)
    # Half a unit against the option, never a full refusal.
    assert before > after > PreferenceLearner().expected_value("x") - 0.15

    # Advancing again does not apply it a second time: the row is written once and the learner
    # is rebuilt from rows.
    _advance(client)
    assert client.get("/v1/metrics").json()["candidate_preference_scores"][candidate_key] == after

    events = client.get("/v1/simulation/events").json()
    resolution = next(
        event
        for event in events
        if event["event_type"] == "intervention_outcome_recorded"
        and event["detail"]["intervention_id"] == first["intervention_id"]
    )
    assert resolution["detail"]["preference_before"] == before
    assert resolution["detail"]["preference_after"] == after


def test_silence_never_counts_as_a_decline(client: TestClient) -> None:
    """Three declines mute a candidate deterministically; three silences must not."""
    for _ in range(3 * (RESPONSE_WINDOW_DAYS + 1)):
        _advance(client, "activity_declines")
        _advance(client, "recovery")
        _advance(client, "recovery")

    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/preferences").json()
    assert all(not item["suppressed"] for item in preferences)
    assert client.get("/v1/metrics").json()["no_reply_recorded"] >= 3


def test_a_late_reply_is_told_the_offer_closed_as_unanswered(client: TestClient) -> None:
    first = _advance(client)["created_intervention"]
    for _ in range(RESPONSE_WINDOW_DAYS):
        _advance(client)

    late = client.post(
        f"/v1/interventions/{first['intervention_id']}/outcome", json={"outcome": "accepted"}
    )
    assert late.status_code == 422
    assert "closed as unanswered" in late.json()["detail"]
    # Not the generic duplicate wording -- the person did not answer twice.
    assert "already been recorded" not in late.json()["detail"]


# ── Where the clock is visible ────────────────────────────────────────────────────────────────


def test_metrics_count_awaiting_and_no_reply_separately(client: TestClient) -> None:
    assert client.get("/v1/metrics").json()["awaiting_reply"] == 0
    _advance(client)
    metrics = client.get("/v1/metrics").json()
    assert (metrics["awaiting_reply"], metrics["no_reply_recorded"]) == (1, 0)

    _advance(client)
    _advance(client)
    metrics = client.get("/v1/metrics").json()
    assert (metrics["awaiting_reply"], metrics["no_reply_recorded"]) == (1, 1)


def test_the_trace_names_the_day_the_clock_stops_waiting(client: TestClient) -> None:
    payload = _advance(client)
    intervention = payload["created_intervention"]
    assert intervention is not None
    due = date.fromisoformat(intervention["awaiting_reply_until"])

    response_stage = next(step for step in payload["loop_trace"] if step["stage"] == "response")
    assert "If nothing is recorded by" in response_stage["detail"]
    assert due.strftime("%a %d %b") in response_stage["detail"]
    assert "silence, not a refusal" in response_stage["detail"]


def test_outreach_history_carries_the_clock(client: TestClient) -> None:
    for _ in range(3):
        _advance(client)

    history = client.get(f"/v1/coordinator/people/{DEMO_PERSON_ID}/outreach-history").json()
    by_outcome = {entry["outcome"]: entry for entry in history}
    assert by_outcome["no_response"]["awaiting_reply_until"] is None
    assert by_outcome[None]["awaiting_reply_until"] is not None


# ── The same clock, on the contact cap ────────────────────────────────────────────────────────


def test_the_contact_cap_counts_the_persons_simulated_week(
    repository: SqlAlchemyRepository,
) -> None:
    """Two contacts, six quiet days, then a mild dip: the budget has been released.

    Every one of these nine advances happens within a second of wall clock. Under the old
    `created_at >= utcnow() - 7 days` rule both early contacts were still "this week" and the
    day-9 dip was `suppress`ed; in the person's own days a week has passed.
    """
    first = repository.advance("activity_declines").state.last_decision.value
    second = repository.advance("activity_declines").state.last_decision.value
    assert (first, second) == ("gentle_nudge", "programme_suggestion")
    for _ in range(6):
        assert repository.advance("recovery").state.last_decision.value == "no_action"

    ninth = repository.advance("activity_declines")
    assert ninth.state.last_decision.value == "gentle_nudge"
    assert not any("contact cap" in line.lower() for line in ninth.state.rationale)


def test_the_contact_cap_still_binds_inside_the_simulated_week(
    repository: SqlAlchemyRepository,
) -> None:
    """Scenario 07's shape: the third contact a few days later is still suppressed."""
    repository.advance("activity_declines")
    repository.advance("activity_declines")
    repository.advance("recovery")
    fourth = repository.advance("activity_declines")
    assert fourth.state.last_decision.value == "suppress"
    assert any("contact cap" in line.lower() for line in fourth.state.rationale)
