"""The audit trail (`GET /v1/simulation/events`) is readable by any `demo_operator`, for any
person, so a senior's own free text must never land in it verbatim -- only whether the field was
present, or how long it was. The note or reason itself still has to survive somewhere: on its own
domain row, which is either read back to the person who wrote it or queried directly here.

Five routes let a senior type something in their own words: a follow-through note, a day dispute,
a context-question note, a candidate-preference reason and a consent reason. The review-threshold
routes add a coordinator's notes and a calibrator's reasoning, held to the same rule. Each is driven
through the real HTTP contract with a distinctive sentinel string, and every assertion below
checks the *whole* serialised audit trail for the person, not just the one event just written --
an older event that still carried raw text would pass a narrower check.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.db_models import (
    CandidatePreferenceRow,
    ConsentEvidenceRow,
    ContextQuestionAnswerRow,
    DayDisputeRow,
    InterventionFollowThroughRow,
    ReviewThresholdDecisionRow,
)
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository

SENTINEL = "Sentinel-Zx91-never-leave-the-domain-row"


def _events(client: TestClient) -> list[dict]:
    response = client.get("/v1/simulation/events", params={"person_id": DEMO_PERSON_ID})
    assert response.status_code == 200, response.text
    return response.json()


def _assert_sentinel_absent_from_audit_trail(client: TestClient) -> None:
    """Not just the one event just written -- the entire trail for this person."""
    assert SENTINEL not in str(_events(client))


def _advance(client: TestClient, event: str = "activity_declines") -> dict:
    response = client.post("/v1/simulation/advance", json={"event": event})
    assert response.status_code == 200, response.text
    return response.json()


def test_follow_through_note_never_reaches_the_audit_trail(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    intervention = _advance(client)["created_intervention"]
    assert intervention is not None, "expected this advance to create an intervention"
    intervention_id = intervention["intervention_id"]
    assert (
        client.post(
            f"/v1/interventions/{intervention_id}/outcome", json={"outcome": "accepted"}
        ).status_code
        == 200
    )

    response = client.post(
        f"/v1/interventions/{intervention_id}/follow-through",
        json={"follow_through": "completed", "note": SENTINEL},
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["note_present"] is True
    assert "note" not in detail

    _assert_sentinel_absent_from_audit_trail(client)

    with repository.sessions() as session:
        row = session.scalar(
            select(InterventionFollowThroughRow).where(
                InterventionFollowThroughRow.intervention_id == intervention_id
            )
        )
    assert row is not None and row.note == SENTINEL


def test_day_dispute_note_never_reaches_the_audit_trail(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    metrics = client.get(f"/v1/people/{DEMO_PERSON_ID}/metrics?days=3").json()
    day = metrics[-1]["day"]

    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/day-dispute",
        json={"day": day, "accurate": False, "note": SENTINEL},
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["note_present"] is True
    assert "note" not in detail

    _assert_sentinel_absent_from_audit_trail(client)

    with repository.sessions() as session:
        row = session.scalar(
            select(DayDisputeRow)
            .where(DayDisputeRow.person_id == DEMO_PERSON_ID, DayDisputeRow.day.isnot(None))
            .order_by(DayDisputeRow.recorded_at.desc())
        )
    assert row is not None and row.note == SENTINEL


def test_context_question_note_never_reaches_the_audit_trail(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    pending = None
    for _ in range(6):
        client.post("/v1/simulation/advance", json={"event": "activity_declines"})
        state = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()
        if state["pending_question"] is not None:
            pending = state["pending_question"]
            break
    assert pending is not None, "a gentle nudge day never raised the question"

    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/context-answer",
        json={
            "question_id": pending["question_id"],
            "value": pending["options"][0]["value"],
            "note": SENTINEL,
        },
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["note_present"] is True
    assert "note" not in detail
    # `value` is a closed-vocabulary token, not typed text, so it is not redacted.
    assert detail["value"] == pending["options"][0]["value"]

    _assert_sentinel_absent_from_audit_trail(client)

    with repository.sessions() as session:
        row = session.scalar(
            select(ContextQuestionAnswerRow).where(
                ContextQuestionAnswerRow.person_id == DEMO_PERSON_ID
            )
        )
    assert row is not None and row.note == SENTINEL


def test_context_question_value_is_a_closed_vocabulary(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """The comment above says `value` is "a closed-vocabulary token, not typed text", which is
    exactly why it is the one field here that is NOT redacted out of the audit trail. Nothing
    enforced it: `ContextAnswerRequest.value` was a bare `str`, so any free text -- a whole
    paragraph, an injected instruction -- was echoed verbatim into the response body, the audit
    detail and the world model, and anything over 160 characters hit `String(160)` and became a
    500 on PostgreSQL.
    """
    pending = None
    for _ in range(6):
        client.post("/v1/simulation/advance", json={"event": "activity_declines"})
        state = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()
        if state["pending_question"] is not None:
            pending = state["pending_question"]
            break
    assert pending is not None, "a gentle nudge day never raised the question"
    offered = {option["value"] for option in pending["options"]}
    assert len(offered) == 5, offered

    free_text = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/context-answer",
        json={
            "question_id": pending["question_id"],
            "value": "I would rather not say, but " + SENTINEL * 20,
        },
    )
    assert free_text.status_code == 422, free_text.text

    # A plausible-looking token that is simply not on the list is rejected the same way.
    assert (
        client.post(
            f"/v1/people/{DEMO_PERSON_ID}/context-answer",
            json={"question_id": pending["question_id"], "value": "resting_today"},
        ).status_code
        == 422
    )

    accepted = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/context-answer",
        json={"question_id": pending["question_id"], "value": "away"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["value"] in offered
    assert accepted.json()["audit_event"]["detail"]["value"] in offered

    with repository.sessions() as session:
        rows = list(
            session.scalars(
                select(ContextQuestionAnswerRow).where(
                    ContextQuestionAnswerRow.person_id == DEMO_PERSON_ID
                )
            )
        )
    assert [row.value for row in rows] == ["away"], "a rejected answer must not have been stored"


def test_the_repository_rejects_an_off_vocabulary_answer_without_the_pydantic_layer(
    repository: SqlAlchemyRepository,
) -> None:
    """Defence in depth: `answer_context_question` is on the repository Protocol and is called
    directly by the CLI entrypoints, not only through a validated request body."""
    pending = None
    for index in range(6):
        repository.advance("activity_declines", f"closed-vocab-{index}")
        state = repository.person_state(person_id=DEMO_PERSON_ID)
        if state.pending_question is not None:
            pending = state.pending_question
            break
    assert pending is not None, "a gentle nudge day never raised the question"

    with pytest.raises(ValueError, match="one of"):
        repository.answer_context_question(
            pending.question_id, "whatever I like", None, "test", person_id=DEMO_PERSON_ID
        )


def test_candidate_preference_reason_never_reaches_the_audit_trail(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    candidate_key = "gentle_nudge:indoor_walk"

    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/preferences/{candidate_key}",
        json={"suppressed": True, "reason": SENTINEL},
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["reason_present"] is True
    assert "reason" not in detail

    _assert_sentinel_absent_from_audit_trail(client)

    # The person can still read their own reason back, through their own route.
    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/preferences").json()
    muted = next(item for item in preferences if item["candidate_key"] == candidate_key)
    assert muted["suppressed_reason"] == SENTINEL

    with repository.sessions() as session:
        row = session.scalar(
            select(CandidatePreferenceRow).where(
                CandidatePreferenceRow.person_id == DEMO_PERSON_ID,
                CandidatePreferenceRow.candidate_key == candidate_key,
            )
        )
    assert row is not None and row.reason == SENTINEL


def test_consent_reason_never_reaches_the_audit_trail(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/consent",
        json={"active": False, "reason": SENTINEL},
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["reason_length"] == len(SENTINEL)
    assert "reason" not in detail

    _assert_sentinel_absent_from_audit_trail(client)

    with repository.sessions() as session:
        row = session.scalar(
            select(ConsentEvidenceRow)
            .where(ConsentEvidenceRow.person_id == DEMO_PERSON_ID)
            .order_by(ConsentEvidenceRow.recorded_at.desc())
        )
    assert row is not None and row.reason == SENTINEL


# ── The review-threshold calibrator (ADR 0008) ────────────────────────────────────────────────
#
# A coordinator's review note, an approval note, a rejection note and a manual-set note are the
# coordinator's words about a senior; a calibrator's reasoning is coordinator-facing prose. None
# of it may reach the operator-readable trail -- only ids, kinds, values and `note_present`.


def _threshold_url(suffix: str = "") -> str:
    return f"/v1/coordinator/people/{DEMO_PERSON_ID}/review-threshold{suffix}"


def _false_alarm_with_note(client: TestClient, note: str) -> None:
    for _ in range(6):
        _advance(client)
        queue = client.get("/v1/coordinator/queue").json()
        if queue:
            break
    response = client.post(
        f"/v1/cases/{queue[0]['case_id']}/review",
        json={
            "status": "resolved",
            "reviewer_note": note,
            "human_action": "override",
            "override_reason": "not_a_concern",
        },
    )
    assert response.status_code == 200, response.text


def test_review_threshold_notes_and_reasoning_never_reach_the_audit_trail(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _false_alarm_with_note(client, SENTINEL)
    _advance(client, "recovery")
    _false_alarm_with_note(client, SENTINEL)
    state = client.get(_threshold_url()).json()
    first = state["open_proposal"]
    assert first is not None
    reasonings = [item["reasoning"] for item in state["proposals"]]

    rejected = client.post(
        _threshold_url(f"/proposals/{first['proposal_id']}/reject"),
        json={"reason": "prefer_other_change", "note": SENTINEL},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["audit_event"]["detail"]["note_present"] is True
    assert "note" not in rejected.json()["audit_event"]["detail"]
    retry = rejected.json()["state"]["open_proposal"]
    assert retry is not None
    reasonings.append(retry["reasoning"])

    approved = client.post(
        _threshold_url(f"/proposals/{retry['proposal_id']}/approve"),
        json={"cause_confirmed": True, "shown_on_day": state["current_day"], "note": SENTINEL},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["audit_event"]["detail"]["note_present"] is True

    _assert_sentinel_absent_from_audit_trail(client)
    trail = str(_events(client))
    for reasoning in reasonings:
        assert reasoning not in trail

    with repository.sessions() as session:
        notes = list(session.scalars(select(ReviewThresholdDecisionRow.note)))
    assert notes.count(SENTINEL) == 2


def test_a_calibration_agents_reasoning_and_notes_never_reach_the_audit_trail(
    repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 2: the agent's run record is on the proposal row; the audit event carries only its
    evidence id, mode, cause and values. Driven through the repository with a fake transport --
    the offline app profile refuses to start with the LLM on."""
    from types import SimpleNamespace

    import silverloop.agent.planner as planner
    from silverloop.agent.threshold_tools import THRESHOLD_READ_TOOL_NAMES
    from silverloop.config import Settings
    from silverloop.models import CaseStatus, HumanAction, OverrideReason

    monkeypatch.setattr(planner, "_build_client", lambda *_: (None, "no client in tests"))
    reasoning = f"Ordinary swings recover on their own. {SENTINEL}-reasoning"

    def create(**kwargs: object) -> SimpleNamespace:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        if len(messages) == 1:
            blocks = [
                SimpleNamespace(type="tool_use", id=f"read_{i}", name=name, input={})
                for i, name in enumerate(THRESHOLD_READ_TOOL_NAMES)
            ]
            return SimpleNamespace(content=blocks, stop_reason="tool_use", usage=usage)
        propose = SimpleNamespace(
            type="tool_use",
            id="propose",
            name="propose_threshold_change",
            input={
                "cause": "too_tight_for_person",
                "proposed_severity_pct": None,
                "proposed_persistence_days": 4,
                "reasoning": reasoning,
                "cited_evidence_ids": ["variability"],
            },
        )
        return SimpleNamespace(content=[propose], stop_reason="tool_use", usage=usage)

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    repository._threshold_client_factory = lambda: (fake, None)
    for index in range(6):
        repository.advance("activity_declines", event_id=f"agent-redaction-{index}")
        cases = repository.list_cases()
        if cases:
            break
    repository._settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
        llm_enabled=True,
    )
    repository.review_case(
        cases[0].case_id,
        CaseStatus.RESOLVED,
        SENTINEL,
        "coordinator",
        human_action=HumanAction.OVERRIDE,
        override_reason=OverrideReason.NOT_A_CONCERN,
    )
    state = repository.review_threshold_state(DEMO_PERSON_ID, viewer_sub="coordinator")
    assert state.open_proposal is not None
    assert state.open_proposal.reasoning == reasoning
    agent_run = state.open_proposal.agent_run
    assert agent_run is not None and agent_run["mode"] == "agent"

    trail = repository.list_events()
    assert SENTINEL not in str([event.model_dump() for event in trail])
    [proposed] = [event for event in trail if event.event_type == "review_threshold_proposed"]
    assert proposed.detail["agent_evidence_id"] == agent_run["agent_evidence_id"]
    assert proposed.detail["mode"] == "agent"
    assert proposed.detail["cause"] == "too_tight_for_person"
    assert proposed.detail["proposed"] == {"severity_pct": 40, "persistence_days": 4}
    assert "reasoning" not in proposed.detail and "agent_run" not in proposed.detail
