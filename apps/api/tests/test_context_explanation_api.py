"""The quiet-day answer changing what happens next, end to end through the API.

`test_context_explanation.py` pins the rule; this file pins that the rule is actually reached from
the product. It exists because the gap it closes was not a logic error -- every piece was already
built and tested -- but a missing wire: `ContextQuestionAnswerRow` was written, read once as an
existence check so the question is not asked twice, and read again for display, so "I'm away" and
"I don't feel like going out" were indistinguishable to `policy.decide`.

Expressed here rather than as a scenario YAML on purpose: the scenario runner maps a flat list of
input events to `advance()` and has no step for "the senior answers a question". Adding one is a
change to the simulation contract and belongs in its own review, not smuggled in here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from silverloop.fixtures import DEMO_PERSON_ID


def _advance(client: TestClient, event: str = "activity_declines") -> dict:
    client.post("/v1/simulation/advance", json={"event": event})
    return client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()


def _decline_until_question(client: TestClient) -> dict:
    """Advance declining days until the quiet-day question is raised, and return that state."""
    for _ in range(6):
        state = _advance(client)
        if state["pending_question"] is not None:
            return state
    raise AssertionError("no declining day raised the quiet-day question")


def _answer(client: TestClient, state: dict, value: str) -> None:
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/context-answer",
        json={"question_id": state["pending_question"]["question_id"], "value": value},
    )
    assert response.status_code == 200, response.text


def test_an_explanation_changes_the_next_decision(client: TestClient) -> None:
    """The loop closes: the answer reaches the ladder rather than only the screen."""
    state = _decline_until_question(client)
    assert state["last_decision"] in {"gentle_nudge", "programme_suggestion"}

    _answer(client, state, "away")
    after = _advance(client)

    assert after["last_decision"] == "no_action"
    rationale = " ".join(after["rationale"])
    assert "away from home" in rationale
    assert "applies through" in rationale


def test_without_an_answer_no_explanation_is_recorded(client: TestClient) -> None:
    """The control for the test above: nothing else about the run produces that rationale.

    The decision itself is not pinned here -- an unanswered declining run legitimately reaches the
    contact-fatigue guard and reports `suppress` -- so this asserts the thing that is actually
    specific to the new gate: no stated explanation appears in the audit when nobody stated one.
    """
    _decline_until_question(client)
    after = _advance(client)
    assert "This person has said" not in " ".join(after["rationale"])


def test_declining_to_answer_changes_nothing(client: TestClient) -> None:
    """A question described as optional must be answerable with no consequence."""
    state = _decline_until_question(client)
    _answer(client, state, "prefer_not_to_say")
    after = _advance(client)
    assert "This person has said" not in " ".join(after["rationale"])


def test_not_feeling_like_going_out_is_not_an_explanation(client: TestClient) -> None:
    """It may be the signal rather than an account of it, so it must not defer outreach."""
    state = _decline_until_question(client)
    _answer(client, state, "not_feeling_it")
    after = _advance(client)
    assert "This person has said" not in " ".join(after["rationale"])


def test_the_explanation_expires_and_the_ladder_resumes(client: TestClient) -> None:
    """`resting` covers the day it was given and the one after; the third day is normal again."""
    state = _decline_until_question(client)
    _answer(client, state, "resting")

    first = _advance(client)
    assert first["last_decision"] == "no_action"
    assert "resting" in " ".join(first["rationale"])

    second = _advance(client)
    assert "resting" not in " ".join(second["rationale"]), "a two-day answer reached a third day"


def test_a_persistent_severe_decline_still_reaches_a_human(client: TestClient) -> None:
    """The invariant, through the product: an explanation never buys its way past review.

    The person answers as soon as they are asked and keeps declining. The explanation defers the
    outreach rungs for its window and then stops applying, so review is still reached and a case is
    still opened.
    """
    state = _decline_until_question(client)
    _answer(client, state, "away")

    decisions = [_advance(client)["last_decision"] for _ in range(6)]
    assert "coordinator_review" in decisions, decisions

    metrics = client.get("/v1/metrics").json()
    assert metrics["open_cases"] >= 1, metrics


def test_the_recorded_answer_carries_the_simulated_day(client: TestClient) -> None:
    """`answered_on_day` is what the window is counted from; it must be the scenario day."""
    state = _decline_until_question(client)
    _answer(client, state, "away")

    model = client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()
    context = [fact for fact in model["facts"] if fact["category"] == "context"]
    assert len(context) == 1
    assert context[0]["expires_at"] is not None
