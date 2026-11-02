"""The quiet-day answer changing what happens next, end to end through the API.

`test_context_explanation.py` pins the rule; this file pins that the rule is actually reached from
the product. It exists because the gap it closes was not a logic error -- every piece was already
built and tested -- but a missing wire: `ContextQuestionAnswerRow` was written, read once as an
existence check so the question is not asked twice, and read again for display, so "I'm away" and
"I don't feel like going out" were indistinguishable to `policy.decide`.

Expressed here rather than as a scenario YAML on purpose: the scenario runner maps a flat list of
input events to `advance()` and has no step for "the senior answers a question". Adding one is a
change to the simulation contract and belongs in its own review, not smuggled in here.

The answer itself is stored as a row (`tests/row_fixtures.py`): `POST
/v1/people/{id}/context-answer` went in step 7, and what `advance` does with a stored answer is
unchanged.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository
from tests.row_fixtures import answer_context_question


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


def _answer(repository: SqlAlchemyRepository, value: str) -> None:
    answer_context_question(repository, value, person_id=DEMO_PERSON_ID)


def test_an_explanation_changes_the_next_decision(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """The loop closes: the answer reaches the ladder rather than only the screen."""
    state = _decline_until_question(client)
    assert state["last_decision"] in {"gentle_nudge", "programme_suggestion"}

    _answer(repository, "away")
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


def test_declining_to_answer_changes_nothing(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """A question described as optional must be answerable with no consequence."""
    _decline_until_question(client)
    _answer(repository, "prefer_not_to_say")
    after = _advance(client)
    assert "This person has said" not in " ".join(after["rationale"])


def test_not_feeling_like_going_out_is_not_an_explanation(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """It may be the signal rather than an account of it, so it must not defer outreach."""
    _decline_until_question(client)
    _answer(repository, "not_feeling_it")
    after = _advance(client)
    assert "This person has said" not in " ".join(after["rationale"])


def test_the_explanation_expires_and_the_ladder_resumes(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """`resting` covers the day it was given and the one after; the third day is normal again."""
    _decline_until_question(client)
    _answer(repository, "resting")

    first = _advance(client)
    assert first["last_decision"] == "no_action"
    assert "resting" in " ".join(first["rationale"])

    second = _advance(client)
    assert "resting" not in " ".join(second["rationale"]), "a two-day answer reached a third day"


def test_a_persistent_severe_decline_still_reaches_a_human(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """The invariant, through the product: an explanation never buys its way past review.

    The person answers as soon as they are asked and keeps declining. The explanation defers the
    outreach rungs for its window and then stops applying, so review is still reached and a case is
    still opened.
    """
    _decline_until_question(client)
    _answer(repository, "away")

    decisions = [_advance(client)["last_decision"] for _ in range(6)]
    assert "coordinator_review" in decisions, decisions

    metrics = repository.metrics()
    assert metrics.open_cases >= 1, metrics
