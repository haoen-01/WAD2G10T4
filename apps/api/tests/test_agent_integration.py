"""The planner as wired into the repository.

`test_agent_planner.py` proves the loop in isolation. These tests prove the seam: that an
intervention created through the real `advance()` path carries planner evidence, that the
offline profile is byte-for-byte the behaviour it had before the planner existed, and that an
enabled planner changes the wording without ever changing the decision.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from silverloop.agent import AgentProposal, validate_proposal
from silverloop.config import Settings
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.learning import PreferenceLearner
from silverloop.logging_config import agent_logger, request_id_var
from silverloop.main import create_app
from silverloop.models import Decision, DeclineReason, PreferenceDimension, PreferenceStance
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_agent_planner import FakeBlock, FakeClient, FakeResponse

AGENT_MESSAGE = (
    "Would a gentle five-minute seated movement break suit you today? No pressure at all."
)

# A provider exception text shaped like the real ones: an error class, a status, and a fragment
# that must never be written down anywhere an operator or coordinator can read it back.
PROVIDER_SENTINEL = "sk-ant-SENTINEL-must-never-be-audited"
PROVIDER_ERROR_TEXT = f"gateway timeout: 401 Unauthorized for key {PROVIDER_SENTINEL}"


def _events_over(repository: SqlAlchemyRepository) -> list[dict[str, Any]]:
    """`GET /v1/simulation/events` for this repository, through the real HTTP contract.

    The app is built without entering the `TestClient` context manager on purpose: the lifespan
    would run `validate_runtime`, which correctly refuses SQLite under the default `shared`
    profile, and the runtime guard is not what is under test here.
    """
    application = create_app(repository, settings=enabled_settings(), migrate_on_start=False)
    response = TestClient(application).get(
        "/v1/simulation/events", params={"person_id": DEMO_PERSON_ID}
    )
    assert response.status_code == 200, response.text
    return list(response.json())


@pytest.fixture
def agent_log_records() -> Iterator[list[logging.LogRecord]]:
    """Records emitted by the agent logger during the test.

    `agent_logger()` deliberately does not propagate -- it owns its own JSON handler, exactly
    like `request_logger()` -- so `caplog` cannot see it; a handler attached here can.
    """
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = agent_logger()
    handler = _Collector()
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def build_repository(settings: Settings | None = None) -> SqlAlchemyRepository:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=settings)
    instance.create_schema_for_tests()
    instance.reset()
    return instance


def enabled_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        auth_enabled=False,
        external_context_enabled=False,
        llm_enabled=True,
        llm_api_key="test-key",
        llm_model="claude-opus-5",
    )


def offline_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        auth_enabled=False,
        external_context_enabled=False,
        llm_enabled=False,
    )


@pytest.fixture
def offline_repository() -> Iterator[SqlAlchemyRepository]:
    instance = build_repository(offline_settings())
    yield instance
    instance.close()


def advance_to_intervention(repository: SqlAlchemyRepository) -> Any:
    """Drive the scripted decline until the policy permits an outreach message."""
    for _ in range(4):
        response = repository.advance("activity_declines")
        if response.created_intervention is not None:
            return response
    raise AssertionError("the scripted decline never produced an intervention")


def test_offline_profile_records_the_deterministic_path(
    offline_repository: SqlAlchemyRepository,
) -> None:
    """With `LLM_ENABLED=false` the ranker still chooses, and the record says so plainly."""
    response = advance_to_intervention(offline_repository)
    intervention = response.created_intervention
    assert intervention is not None

    agent = intervention.evidence["agent"]
    assert agent["mode"] == "fallback_disabled"
    assert agent["model"] is None
    assert agent["iterations"] == 0
    assert agent["tool_calls"] == []
    assert "LLM_ENABLED is false" in agent["fallback_reason"]

    # The message is still the curated fixture copy, unchanged by the planner's existence,
    # and the chosen candidate is exactly the one the deterministic ranker put first.
    assert (
        intervention.evidence["candidate_key"]
        == (intervention.evidence["deterministic_candidate_key"])
    )
    assert "No pressure" in intervention.message or "optional" in intervention.message


def test_planner_evidence_appears_in_the_decision_trace(
    offline_repository: SqlAlchemyRepository,
) -> None:
    """A judge watching the simulator sees how the candidate was chosen."""
    response = advance_to_intervention(offline_repository)
    action_step = next(step for step in response.loop_trace if step.stage == "action")
    assert "Deterministic ranker selected the candidate" in action_step.detail
    # The trace contract the UI and e2e tests rely on: ten stages since the follow-through loop
    # landed, with `follow_through` inserted between `outcome` and `learning`.
    assert len(response.loop_trace) == 10
    assert [step.stage for step in response.loop_trace][-3:] == [
        "follow_through",
        "learning",
        "audit",
    ]


def test_enabled_planner_writes_its_own_wording_and_full_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An approved proposal replaces the wording but never the decision."""
    scripted = [
        FakeResponse([FakeBlock("tu1", "get_candidate_options", {})]),
        FakeResponse(
            [
                FakeBlock(
                    "tu2",
                    "propose_outreach",
                    {
                        "candidate_key": "gentle_nudge:chair_mobility",
                        "message": AGENT_MESSAGE,
                        "reasoning": "She responds well to low-effort, social framing.",
                    },
                )
            ]
        ),
    ]
    monkeypatch.setattr(
        "silverloop.agent.planner._build_client",
        lambda settings, timeout: (FakeClient(scripted), None),
    )

    repository = build_repository(enabled_settings())
    try:
        response = advance_to_intervention(repository)
        intervention = response.created_intervention
        assert intervention is not None

        agent = intervention.evidence["agent"]
        assert agent["mode"] == "agent"
        assert agent["model"] == "claude-opus-5"
        assert agent["iterations"] == 2
        assert agent["tool_call_success_rate"] == 1.0
        assert agent["total_tokens"] > 0
        assert agent["agent_reasoning"].startswith("She responds well")

        # The planner supplied the copy...
        assert intervention.message == AGENT_MESSAGE
        assert intervention.evidence["candidate_key"] == "gentle_nudge:chair_mobility"
        # ...but the decision class is still the deterministic policy's.
        assert intervention.decision == Decision.GENTLE_NUDGE
        assert intervention.evidence["policy_version"] == "silverloop-policy-v1"

        action_step = next(step for step in response.loop_trace if step.stage == "action")
        assert "Planner" in action_step.detail
    finally:
        repository.close()


# ── Grounding: the message may only assert facts the chosen candidate actually has ────────────
#
# Regression pins for the real defect this guardrail was added for (2026-09-09 model probe): two
# of two live runs against `gentle_nudge:chair_mobility` -- a SOLO, seated option -- invented
# company ("with us", "joining us"), dropped "seated" for a generic "stretch", and one instructed
# a reply the senior surface cannot receive. Both here are pinned end-to-end through the real
# `advance()` seam, not just at the guardrail unit level, so a regression in the wiring (not just
# the rule) would also be caught.


def test_fabricated_company_language_is_rejected_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact shape of the real defect: a SOLO candidate described as done "with others"."""
    fabricated = (
        "How about joining us for a quick five-minute movement session? It's a great way to "
        "move with others."
    )
    scripted = [
        FakeResponse([FakeBlock("tu1", "get_candidate_options", {})]),
        FakeResponse(
            [
                FakeBlock(
                    "tu2",
                    "propose_outreach",
                    {
                        "candidate_key": "gentle_nudge:chair_mobility",
                        "message": fabricated,
                        "reasoning": "She is socially motivated.",
                    },
                )
            ]
        ),
    ]
    monkeypatch.setattr(
        "silverloop.agent.planner._build_client",
        lambda settings, timeout: (FakeClient(scripted), None),
    )

    repository = build_repository(enabled_settings())
    try:
        response = advance_to_intervention(repository)
        intervention = response.created_intervention
        assert intervention is not None

        agent = intervention.evidence["agent"]
        # The turn budget is exhausted before a compliant proposal arrives (only one attempt was
        # scripted), so the run falls back -- exactly the outcome the spec requires: reject a
        # good-sounding fabrication rather than let it reach a senior.
        assert agent["mode"] != "agent"
        assert any("company" in rejection for rejection in agent["guardrail_rejections"])
        # The fabricated wording never reaches the person.
        assert intervention.message != fabricated
        assert "with us" not in intervention.message.lower()
        assert "with others" not in intervention.message.lower()
    finally:
        repository.close()


def test_dropped_accessibility_word_is_rejected_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second real defect: "seated" silently became "stretch" for a seated-only option."""
    fabricated = "Would you like a quick five-minute stretch today? It is completely optional."
    scripted = [
        FakeResponse([FakeBlock("tu1", "get_candidate_options", {})]),
        FakeResponse(
            [
                FakeBlock(
                    "tu2",
                    "propose_outreach",
                    {
                        "candidate_key": "gentle_nudge:chair_mobility",
                        "message": fabricated,
                        "reasoning": "Keeping it brief.",
                    },
                )
            ]
        ),
    ]
    monkeypatch.setattr(
        "silverloop.agent.planner._build_client",
        lambda settings, timeout: (FakeClient(scripted), None),
    )

    repository = build_repository(enabled_settings())
    try:
        response = advance_to_intervention(repository)
        intervention = response.created_intervention
        assert intervention is not None

        agent = intervention.evidence["agent"]
        assert agent["mode"] != "agent"
        assert any("accessibility" in rejection for rejection in agent["guardrail_rejections"])
        assert intervention.message != fabricated
    finally:
        repository.close()


# ── Signal the system already has, reaching the planner ───────────────────────────────────────


def test_decline_reason_reaches_the_planners_outreach_history(
    offline_repository: SqlAlchemyRepository,
) -> None:
    """A specific decline reason is real evidence already collected through `record_outcome`.
    The planner's `get_outreach_history` tool should carry it, not just that the person said no
    -- see `agent.tools.HistoryEntry.decline_reason`.
    """
    first = advance_to_intervention(offline_repository)
    intervention = first.created_intervention
    assert intervention is not None
    offline_repository.record_outcome(
        intervention.intervention_id, "declined", reason=DeclineReason.TOO_TIRING
    )

    with offline_repository.sessions() as session:
        run = offline_repository._active_run(session, DEMO_PERSON_ID)
        state = offline_repository._person_state(session, run)
        resolved = offline_repository._rank_intervention_candidates(session, run, state)
        assert resolved is not None
        ranked, _decision_learner, candidate_learner = resolved
        tool_context = offline_repository._tool_context(
            session, run, state, ranked, candidate_learner
        )

    matching = next(
        entry
        for entry in tool_context.history
        if entry.created_at == intervention.created_at.isoformat()
    )
    assert matching.decline_reason == DeclineReason.TOO_TIRING.value


def test_a_real_acceptance_reaches_the_guardrail_as_the_candidate_key_it_was(
    offline_repository: SqlAlchemyRepository,
) -> None:
    """End to end for the rule that could never pass. `guardrails._accepted_before` asks "did
    this person accept THIS option before", and until `HistoryEntry` carried the key the only
    thing it could compare against was the display title -- so a message referring to an
    acceptance the database really holds was rejected as a false claim about the person's past.
    """
    first = advance_to_intervention(offline_repository)
    intervention = first.created_intervention
    assert intervention is not None
    recorded = offline_repository.record_outcome(intervention.intervention_id, "accepted")

    with offline_repository.sessions() as session:
        run = offline_repository._active_run(session, DEMO_PERSON_ID)
        state = offline_repository._person_state(session, run)
        # An empty candidate list on purpose: accepting the only offer of the week puts the
        # ladder on `suppress` (the contact cap), so there is no live allow-list to rank -- and
        # the allow-list is not what is under test here. The history this assembles is.
        tool_context = offline_repository._tool_context(
            session, run, state, [], PreferenceLearner()
        )

    matching = next(
        entry
        for entry in tool_context.history
        if entry.created_at == intervention.created_at.isoformat()
    )
    assert matching.candidate_key == recorded.candidate_key
    # The key, not the title: those are different strings, and comparing one to the other is
    # exactly the bug.
    assert matching.candidate_key != matching.title

    assert validate_proposal(
        AgentProposal(
            candidate_key=recorded.candidate_key,
            message="Would you like the movement option you enjoyed before? No pressure.",
        ),
        permitted_candidate_keys=[recorded.candidate_key],
        history=tool_context.history,
    ).approved


def test_candidate_options_carry_real_social_shape_and_accessibility_words(
    offline_repository: SqlAlchemyRepository,
) -> None:
    """The structured attributes the grounding guardrail checks against are the same ones handed
    to the model -- a single source of truth, never a second, looser copy for the prompt.
    """
    advance_to_intervention(offline_repository)
    with offline_repository.sessions() as session:
        run = offline_repository._active_run(session, DEMO_PERSON_ID)
        state = offline_repository._person_state(session, run)
        resolved = offline_repository._rank_intervention_candidates(session, run, state)
        assert resolved is not None
        ranked, _decision_learner, candidate_learner = resolved
        tool_context = offline_repository._tool_context(
            session, run, state, ranked, candidate_learner
        )

    by_key = {candidate.key: candidate for candidate in tool_context.candidates}
    assert by_key["gentle_nudge:indoor_walk"].social_shape.value == "solo"
    assert by_key["gentle_nudge:chair_mobility"].social_shape.value == "solo"
    assert by_key["gentle_nudge:chair_mobility"].accessibility_terms == ("seated",)


# ── ADR 0005: the social nudge must never override a single real observation ───────────────────


def _opposing_social_shape(shape: str) -> str:
    return "solo" if shape == "social" else "social"


def test_social_nudge_cannot_override_a_single_real_acceptance(
    offline_repository: SqlAlchemyRepository,
) -> None:
    """The worst realistic case: the accepted candidate's own SOCIAL shape is maximally
    disfavoured (`AVOID`) while a same-decision, never-offered competitor's is maximally
    favoured (`PREFER`) -- two independent preference rows under one dimension, both confirmed
    `senior_statement`s at full strength, giving the nudge its full two-sided range at once.

    A single `accepted` + `completed` report must still keep this candidate ranked first. See
    `sql_repository.SOCIAL_DIMENSION_RANKING_WEIGHT` and ADR 0005 for why this holds by
    construction rather than by a hand-tuned margin.
    """
    first = advance_to_intervention(offline_repository)
    intervention = first.created_intervention
    assert intervention is not None
    accepted_key = intervention.evidence["candidate_key"]
    # Captured before recording anything: accepting today's suggestion is itself grounds for the
    # *next* live evaluation of this same day to prefer `SUPPRESS` ("took up a suggestion
    # recently, give them space") -- correct policy behaviour, and irrelevant to what this test
    # checks. Re-using the original `GENTLE_NUDGE` state (rather than re-deriving it after
    # recording the outcome) keeps the ranking question isolated from that unrelated gate; the
    # candidate learner underneath it is still rebuilt fresh from the database rows either way.
    original_state = first.state

    offline_repository.record_outcome(intervention.intervention_id, "accepted")
    offline_repository.record_follow_through(intervention.intervention_id, "completed")

    with offline_repository.sessions() as session:
        run = offline_repository._active_run(session, DEMO_PERSON_ID)
        resolved = offline_repository._rank_intervention_candidates(session, run, original_state)
    assert resolved is not None
    ranked, _decision_learner, candidate_learner = resolved
    accepted_shape = next(c for c in ranked if c.key == accepted_key).social_shape.value
    opposing_shape = _opposing_social_shape(accepted_shape)

    offline_repository.state_preference(
        PreferenceDimension.SOCIAL,
        accepted_shape,
        PreferenceStance.AVOID,
        actor="senior",
        person_id=DEMO_PERSON_ID,
    )
    offline_repository.state_preference(
        PreferenceDimension.SOCIAL,
        opposing_shape,
        PreferenceStance.PREFER,
        actor="senior",
        person_id=DEMO_PERSON_ID,
    )

    with offline_repository.sessions() as session:
        run = offline_repository._active_run(session, DEMO_PERSON_ID)
        resolved = offline_repository._rank_intervention_candidates(session, run, original_state)
    assert resolved is not None
    ranked, _decision_learner, candidate_learner = resolved

    assert candidate_learner.expected_value(accepted_key) > 0.25, (
        "the setup must actually give the accepted candidate real evidence above the prior"
    )
    assert ranked[0].key == accepted_key, (
        "one real acceptance must survive the nudge's full two-sided range, not just half of it"
    )


def test_social_nudge_cannot_lift_a_single_real_decline_to_the_top(
    offline_repository: SqlAlchemyRepository,
) -> None:
    """The mirror case: a declined candidate's own SOCIAL shape maximally favoured while a
    same-decision, never-offered competitor's is maximally disfavoured. A single `declined`
    report must still keep this candidate out of first place.
    """
    first = advance_to_intervention(offline_repository)
    intervention = first.created_intervention
    assert intervention is not None
    declined_key = intervention.evidence["candidate_key"]
    # See the acceptance test's comment: re-using the original `GENTLE_NUDGE` state keeps this
    # isolated from whatever the *next* live policy evaluation of this same day would otherwise
    # decide once an outcome is on record.
    original_state = first.state

    offline_repository.record_outcome(intervention.intervention_id, "declined")

    with offline_repository.sessions() as session:
        run = offline_repository._active_run(session, DEMO_PERSON_ID)
        resolved = offline_repository._rank_intervention_candidates(session, run, original_state)
    assert resolved is not None
    ranked, _decision_learner, _candidate_learner = resolved
    declined_shape = next(c for c in ranked if c.key == declined_key).social_shape.value
    opposing_shape = _opposing_social_shape(declined_shape)

    offline_repository.state_preference(
        PreferenceDimension.SOCIAL,
        declined_shape,
        PreferenceStance.PREFER,
        actor="senior",
        person_id=DEMO_PERSON_ID,
    )
    offline_repository.state_preference(
        PreferenceDimension.SOCIAL,
        opposing_shape,
        PreferenceStance.AVOID,
        actor="senior",
        person_id=DEMO_PERSON_ID,
    )

    with offline_repository.sessions() as session:
        run = offline_repository._active_run(session, DEMO_PERSON_ID)
        resolved = offline_repository._rank_intervention_candidates(session, run, original_state)
    assert resolved is not None
    ranked, _decision_learner, candidate_learner = resolved

    assert candidate_learner.expected_value(declined_key) < 0.25, (
        "the setup must actually give the declined candidate real evidence below the prior"
    )
    assert ranked[0].key != declined_key, (
        "one real decline must not be overturned by the nudge's full two-sided range"
    )


def test_planner_failure_does_not_break_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider outage during a live demo degrades to the deterministic choice, and the record
    of it names the exception's class and nothing else.

    A provider message routinely carries request ids, ARNs, account ids and -- with a
    misconfigured header -- part of a credential. `evidence_json` is append-only and is rendered
    to coordinators, so the text of a provider error must never reach it. The activity-ranking
    loop has recorded the class name only since it was written, with the reasoning spelled out in
    `planner.py`; this pins the same discipline on the outreach path, end to end.
    """
    monkeypatch.setattr(
        "silverloop.agent.planner._build_client",
        lambda settings, timeout: (FakeClient([RuntimeError(PROVIDER_ERROR_TEXT)]), None),
    )

    repository = build_repository(enabled_settings())
    try:
        response = advance_to_intervention(repository)
        intervention = response.created_intervention
        assert intervention is not None
        agent = intervention.evidence["agent"]
        assert agent["mode"] == "fallback_error"
        assert agent["fallback_reason"] == "RuntimeError"
        assert PROVIDER_SENTINEL not in str(intervention.evidence)
        # A real, sendable message was still produced.
        assert intervention.message
        assert (
            intervention.evidence["candidate_key"]
            == (intervention.evidence["deterministic_candidate_key"])
        )

        # ...and the whole operator-readable audit trail for this person, not only the one
        # evidence block, is free of it.
        events = _events_over(repository)
        assert PROVIDER_SENTINEL not in str(events)
        assert any(event["event_type"] == "decision_recorded" for event in events)
    finally:
        repository.close()


def test_a_planner_crash_outside_the_loop_records_the_class_name_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_plan_outreach_safely` is the belt-and-braces wrapper for a failure `plan_outreach` did
    not degrade itself. It formats its own `fallback_reason`, so it needs the same rule --
    otherwise the leak simply moves one frame outwards."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(PROVIDER_ERROR_TEXT)

    monkeypatch.setattr("silverloop.sql_repository.plan_outreach", _explode)

    repository = build_repository(enabled_settings())
    try:
        response = advance_to_intervention(repository)
        intervention = response.created_intervention
        assert intervention is not None
        agent = intervention.evidence["agent"]
        assert agent["mode"] == "fallback_error"
        assert agent["fallback_reason"] == "RuntimeError"
        assert PROVIDER_SENTINEL not in str(intervention.evidence)
        assert PROVIDER_SENTINEL not in str(_events_over(repository))
    finally:
        repository.close()


def test_the_full_provider_error_text_is_logged_at_warning(
    monkeypatch: pytest.MonkeyPatch, agent_log_records: list[logging.LogRecord]
) -> None:
    """Keeping the text out of the audit trail must not lose it: an operator debugging a provider
    outage still needs the message, on the log stream, correlated by request id."""
    monkeypatch.setattr(
        "silverloop.agent.planner._build_client",
        lambda settings, timeout: (FakeClient([RuntimeError(PROVIDER_ERROR_TEXT)]), None),
    )
    records = agent_log_records
    token = request_id_var.set("req_test_r2")
    repository = build_repository(enabled_settings())
    try:
        advance_to_intervention(repository)
    finally:
        request_id_var.reset(token)
        repository.close()

    warnings = [
        getattr(record, "structured_fields", {})
        for record in records
        if record.levelno == logging.WARNING
    ]
    assert warnings, "the provider error must still be visible to an operator"
    assert any(PROVIDER_SENTINEL in str(fields.get("error")) for fields in warnings)
    assert any(fields.get("request_id") == "req_test_r2" for fields in warnings)
    assert any(fields.get("error_class") == "RuntimeError" for fields in warnings)


def test_planner_cannot_change_the_policy_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consent is revoked, so no outreach exists for the planner to influence at all."""
    calls: list[str] = []

    def spy(settings: Any, timeout: float) -> Any:
        calls.append("built")
        return FakeClient([]), None

    monkeypatch.setattr("silverloop.agent.planner._build_client", spy)

    repository = build_repository(enabled_settings())
    try:
        repository.set_consent(active=False, reason="Test withdrawal", actor="test")
        response = repository.advance("activity_declines")
        assert response.state.last_decision == Decision.SUPPRESS
        assert response.created_intervention is None
        assert calls == [], "the planner must never be consulted when the policy blocks outreach"
    finally:
        repository.close()
