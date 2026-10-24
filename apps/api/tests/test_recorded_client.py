"""Tests for the recorded transport (M25) and the LLM cost counters it makes measurable (M40).

`RecordedClient` is what turns "the agent works" from a claim into something CI can check: the
loop, the guardrail and every degradation path run offline against a recording file. These
tests pin what makes that trustworthy -- the key identifies the request, a miss degrades loudly
rather than quietly producing the deterministic answer as though a model had chosen it, and a
misconfigured recording reads differently from a missing answer. The recordings they read are
tiny synthetic files written into `tmp_path`; no recording is committed.

Record mode is never exercised here; the only record-mode behaviour under test is its refusal to
run.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from silverloop.agent.guardrail_rules import (
    RULE_NAMES,
    RULE_OTHER,
    classify_violation,
    count_violations_by_rule,
)
from silverloop.agent.guardrails import (
    ActivityOrderProposal,
    validate_activity_order,
    validate_proposal,
)
from silverloop.agent.intent_planner import IntentTelemetry, plan_intent
from silverloop.agent.models import AgentProposal
from silverloop.agent.planner import _build_client
from silverloop.agent.recorded_client import (
    RecordedClient,
    RecordedResponse,
    Recording,
    RecordingMiss,
    RecordingRefused,
    load_recordings,
    refuse_record_mode_in_ci,
    request_key,
)
from silverloop.agent.tools import CandidateOption
from silverloop.config import Settings
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.intent import parse_intent
from silverloop.models import SocialPreference
from silverloop.runtime import RuntimeConfigurationError, validate_runtime
from silverloop.sql_repository import SqlAlchemyRepository

_MODEL = "synthetic-scripted-stand-in-v1"
_TODAY = date(2026, 9, 7)


def _write_recording(directory: Path) -> Path:
    """A one-entry synthetic recording whose key no real request produces, so every lookup
    misses -- which is what each test reading it is about."""
    Recording(
        loop="test",
        banner="synthetic test fixture -- NOT A MODEL",
        generator="test",
        entries=[
            RecordedResponse(
                key="0" * 64,
                model=_MODEL,
                content=[],
                stop_reason="end_turn",
                usage={},
                latency_ms=0,
                note="answers nothing",
            )
        ],
    ).write(directory / "fixture.json")
    return directory


def _recorded_settings(recording_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        adapter_mode="fixture",
        external_context_enabled=False,
        llm_enabled=True,
        llm_provider="recorded",
        llm_recording_path=str(recording_path),
        llm_model=_MODEL,
    )


# ── Request keying ─────────────────────────────────────────────────────────────────────────────


def _request(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model": "test-model",
        "max_tokens": 2048,
        "system": [{"type": "text", "text": "system"}],
        "tools": [{"name": "propose_activity_order"}],
        "messages": [{"role": "user", "content": "hello"}],
    }
    base.update(overrides)
    return base


def test_the_key_is_stable_for_the_same_request() -> None:
    assert request_key(_request()) == request_key(_request())


def test_the_key_changes_with_the_model_the_system_the_tools_or_the_messages() -> None:
    baseline = request_key(_request())
    assert request_key(_request(model="other")) != baseline
    assert request_key(_request(system=[{"type": "text", "text": "changed"}])) != baseline
    assert request_key(_request(tools=[{"name": "something_else"}])) != baseline
    assert request_key(_request(messages=[{"role": "user", "content": "bye"}])) != baseline


def test_the_key_ignores_fields_that_do_not_change_what_was_asked() -> None:
    """`max_tokens`, `tool_choice`, thinking and effort shape how an answer is produced, not
    which answer a recording stands for. Including them would invalidate every fixture on an
    unrelated effort change."""
    baseline = request_key(_request())
    assert request_key(_request(max_tokens=64)) == baseline
    assert request_key(_request(tool_choice={"type": "tool", "name": "x"})) == baseline
    assert request_key(_request(output_config={"effort": "max"})) == baseline


def test_the_key_reads_response_objects_as_well_as_data() -> None:
    """From the second turn onward the loop appends provider objects into `messages`; the key
    must see through them, and two equal namespaces must key identically."""
    block = SimpleNamespace(type="tool_use", id="a", name="t", input={"k": [1, 2]})
    twin = SimpleNamespace(type="tool_use", id="a", name="t", input={"k": [1, 2]})
    left = _request(messages=[{"role": "assistant", "content": [block]}])
    right = _request(messages=[{"role": "assistant", "content": [twin]}])
    assert request_key(left) == request_key(right)

    different = SimpleNamespace(type="tool_use", id="b", name="t", input={"k": [1, 2]})
    assert request_key(_request(messages=[{"role": "assistant", "content": [different]}])) != (
        request_key(left)
    )


# ── What a miss does ───────────────────────────────────────────────────────────────────────────


def test_recording_miss_carries_the_key_and_never_the_response(tmp_path: Path) -> None:
    client = RecordedClient(_write_recording(tmp_path), mode="replay")
    with pytest.raises(RecordingMiss) as caught:
        client.messages.create(**_request())
    assert caught.value.key == request_key(_request())
    assert type(caught.value).__name__ == "RecordingMiss"


# ── Record mode is refused ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("marker", ["CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION"])
def test_record_mode_is_refused_under_ci(marker: str) -> None:
    with pytest.raises(RecordingRefused):
        refuse_record_mode_in_ci({marker: "true"})


def test_record_mode_is_permitted_when_no_ci_marker_is_set() -> None:
    """The guard must not be so broad that a human cannot record at all."""
    refuse_record_mode_in_ci({"CI": "", "GITHUB_ACTIONS": "false"})


def test_record_mode_without_an_inner_client_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecordingRefused):
        RecordedClient(tmp_path / "out.json", mode="record", inner=None, environ={})
    assert not (tmp_path / "out.json").exists()


def test_an_unknown_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown recording mode"):
        RecordedClient(tmp_path, mode="replay-ish")  # type: ignore[arg-type]


# ── Recording files ────────────────────────────────────────────────────────────────────────────


def test_a_missing_path_loads_as_empty_rather_than_raising(tmp_path: Path) -> None:
    responses, files = load_recordings(tmp_path / "nowhere")
    assert responses == {}
    assert files == []


def test_conflicting_recordings_are_refused(tmp_path: Path) -> None:
    """Two files that answer the same request differently would make replay order-dependent."""
    for index, note in enumerate(("left", "right")):
        Recording(
            loop="test",
            banner="synthetic test fixture",
            generator="test",
            entries=[
                RecordedResponse(
                    key="a" * 64,
                    model="m",
                    content=[],
                    stop_reason="end_turn",
                    usage={},
                    latency_ms=index,
                    note=note,
                )
            ],
        ).write(tmp_path / f"{note}.json")
    with pytest.raises(ValueError, match="redefines recorded request"):
        load_recordings(tmp_path)


def test_a_future_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema_version": 99, "entries": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        load_recordings(path)


# ── The client factory branch ──────────────────────────────────────────────────────────────────


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "llm_enabled": True,
        "llm_provider": "recorded",
        "llm_recording_path": "recordings",
        "llm_model": _MODEL,
    }
    base.update(overrides)
    return Settings(**base)


def test_build_client_returns_the_recorded_client_without_touching_the_sdk(tmp_path: Path) -> None:
    client, unavailable = _build_client(
        _settings(llm_recording_path=str(_write_recording(tmp_path))), 20.0
    )
    assert unavailable is None
    assert isinstance(client, RecordedClient)
    assert client.recorded_count > 0


def test_build_client_reports_an_unset_path_as_unavailable() -> None:
    client, unavailable = _build_client(_settings(llm_recording_path=""), 20.0)
    assert client is None
    assert "LLM_RECORDING_PATH" in (unavailable or "")


def test_build_client_reports_a_missing_path_as_unavailable(tmp_path: Path) -> None:
    client, unavailable = _build_client(
        _settings(llm_recording_path=str(tmp_path / "absent")), 20.0
    )
    assert client is None
    assert "does not exist" in (unavailable or "")


def test_build_client_reports_an_empty_recording_as_unavailable(tmp_path: Path) -> None:
    client, unavailable = _build_client(_settings(llm_recording_path=str(tmp_path)), 20.0)
    assert client is None
    assert "no recorded responses" in (unavailable or "")


# ── Runtime configuration ──────────────────────────────────────────────────────────────────────


def _offline(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "silverloop_runtime_profile": "offline",
        "adapter_mode": "fixture",
        "llm_enabled": True,
        "llm_provider": "recorded",
        # The runtime check reads the setting, not the file; `_build_client` checks the file.
        "llm_recording_path": "recordings",
    }
    base.update(overrides)
    return Settings(**base)


def test_the_offline_profile_accepts_the_recorded_provider() -> None:
    validate_runtime(_offline())


@pytest.mark.parametrize("provider", ["anthropic", "bedrock"])
def test_the_offline_profile_still_refuses_a_real_provider(provider: str) -> None:
    """The offline promise is "no provider, no egress". Recorded is the only exception."""
    with pytest.raises(RuntimeConfigurationError, match="offline fallback requires"):
        validate_runtime(
            _offline(
                llm_provider=provider,
                llm_api_key="key",
                llm_aws_region="ap-southeast-1",
            )
        )


def test_the_recorded_provider_requires_a_recording_path() -> None:
    with pytest.raises(RuntimeConfigurationError, match="LLM_RECORDING_PATH"):
        validate_runtime(_offline(llm_recording_path="  "))


def test_the_recorded_provider_needs_no_key_and_no_region() -> None:
    """The check that would demand them for a real provider must not fire for a file reader."""
    validate_runtime(_offline(llm_api_key="", llm_aws_region=""))


def test_the_iteration_ceiling_still_binds_for_the_recorded_provider() -> None:
    with pytest.raises(RuntimeConfigurationError, match="hard ceiling"):
        validate_runtime(_offline(llm_max_iterations=99))


# ── Intent telemetry ───────────────────────────────────────────────────────────────────────────


def test_intent_telemetry_records_a_failed_call_too(tmp_path: Path) -> None:
    """A failure that leaves no trace in the cost record is the one nobody fixes."""

    class Exploding:
        @property
        def messages(self) -> Exploding:
            return self

        def create(self, **_: Any) -> Any:
            raise RuntimeError("boom")

    telemetry = IntentTelemetry()
    _, mode = plan_intent(
        "something gentle",
        today=_TODAY,
        settings=_recorded_settings(tmp_path),
        fallback=parse_intent("something gentle", today=_TODAY),
        client_factory=lambda: (Exploding(), None),
        telemetry=telemetry,
    )
    assert mode == "fallback_error"
    assert telemetry.attempted
    assert telemetry.usage == {}


def test_intent_telemetry_is_absent_when_no_call_was_made() -> None:
    telemetry = IntentTelemetry()
    fallback = parse_intent("anything", today=_TODAY)
    _, mode = plan_intent(
        "anything",
        today=_TODAY,
        settings=Settings(database_url="sqlite+pysqlite:///:memory:", llm_enabled=False),
        fallback=fallback,
        telemetry=telemetry,
    )
    assert mode == "fallback_disabled"
    assert telemetry.attempted is False
    assert telemetry.latency_ms == 0


# ── Guardrail rule names ───────────────────────────────────────────────────────────────────────


def _emitted_violations() -> list[str]:
    """Every violation the guardrail can currently emit, from real verdicts -- not hand-copied
    strings, so a reworded rule reaches this test rather than passing it."""
    permitted = ["candidate-a"]
    candidate = CandidateOption(
        key="candidate-a",
        title="Seated stretching",
        preference_score=0.25,
        social_shape=SocialPreference.SOLO,
        accessibility_terms=("seated",),
    )

    def proposal(message: str, key: str = "candidate-a") -> AgentProposal:
        return AgentProposal(candidate_key=key, message=message, reasoning="because")

    verdicts = [
        validate_proposal(
            proposal("Would you like to come along?", key="not-permitted"),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(proposal("Short?"), permitted_candidate_keys=permitted),
        validate_proposal(proposal("x" * 400 + "?"), permitted_candidate_keys=permitted),
        validate_proposal(
            proposal("Your doctor suggested this, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("You must come along today, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("Your daughter thought you might like this, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("A place has been booked for you, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("You walked 4500 steps last week, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("There is a seated stretching session on Tuesday."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("Please reply to let us know, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("A gentle seated session awaits \U0001f60a, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("You enjoyed this seated session before, no pressure."),
            permitted_candidate_keys=permitted,
        ),
        validate_proposal(
            proposal("Come and join us for a seated stretch, no pressure."),
            permitted_candidate_keys=permitted,
            candidates=[candidate],
        ),
        validate_proposal(
            proposal("A gentle stretching session on Tuesday, no pressure."),
            permitted_candidate_keys=permitted,
            candidates=[candidate],
        ),
        validate_activity_order(ActivityOrderProposal(ordered_keys=[]), permitted_keys=["a"]),
        validate_activity_order(
            ActivityOrderProposal(ordered_keys=["invented"]), permitted_keys=["a"]
        ),
        validate_activity_order(
            ActivityOrderProposal(ordered_keys=["a", "a"]), permitted_keys=["a"]
        ),
        # "e" is offered first from deterministic position 5: a gain past `MAX_PROMOTION`.
        validate_activity_order(
            ActivityOrderProposal(ordered_keys=["e", "a", "b", "c", "d"]),
            permitted_keys=_FIVE_PERMITTED,
        ),
        # One of five kept: below `MIN_SHOWN_AFTER_NARROWING`.
        validate_activity_order(
            ActivityOrderProposal(ordered_keys=["a"]), permitted_keys=_FIVE_PERMITTED
        ),
    ]
    return [violation for verdict in verdicts for violation in verdict.violations]


_FIVE_PERMITTED = ["a", "b", "c", "d", "e"]


def test_every_violation_the_guardrail_can_emit_has_a_rule_name() -> None:
    """`guardrail_rejections_by_rule` classifies prose. Reword a violation in `guardrails.py`
    and this fails -- which is the point: the counter must never quietly become `other`."""
    violations = _emitted_violations()
    assert violations
    unclassified = [v for v in violations if classify_violation(v) == RULE_OTHER]
    assert unclassified == []


def test_the_rule_table_covers_every_named_rule() -> None:
    """Both directions: no rule in the table is unreachable from a real verdict."""
    seen = {classify_violation(violation) for violation in _emitted_violations()}
    assert seen == set(RULE_NAMES) - {RULE_OTHER}


def test_promotion_and_narrowing_violations_classify_to_their_own_rules() -> None:
    """Both used to fall into `other`, so the two rules that bound a poisoned listing's reach
    were invisible in `guardrail_rejections_by_rule`. Each real sentence must name its own rule,
    and neither may be captured by an earlier marker (the narrowing sentence says "at least")."""
    promoted = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["e", "a", "b", "c", "d"]),
        permitted_keys=_FIVE_PERMITTED,
    ).violations
    narrowed = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["a"]), permitted_keys=_FIVE_PERMITTED
    ).violations
    assert [classify_violation(v) for v in promoted] == ["over_promotion"]
    assert [classify_violation(v) for v in narrowed] == ["over_narrowing"]
    assert count_violations_by_rule(promoted + narrowed) == {
        "over_promotion": 1,
        "over_narrowing": 1,
    }


def test_an_unrecognised_violation_is_counted_under_other_not_dropped() -> None:
    counts = count_violations_by_rule(["something nobody anticipated", 17, None])
    assert counts == {RULE_OTHER: 1}


def test_counting_violations_tolerates_a_non_list() -> None:
    assert count_violations_by_rule(None) == {}
    assert count_violations_by_rule("a string") == {}


# ── M40: the LLM cost counters ─────────────────────────────────────────────────────────────────


def _repository(settings: Settings | None = None) -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=settings)
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_the_cost_counters_are_zero_and_honest_with_the_planner_off() -> None:
    """Under `LLM_ENABLED=false` no call is made, so every cost number is zero -- and is
    reported, rather than absent."""
    repository = _repository(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            llm_enabled=False,
        )
    )
    try:
        repository.search_activities(
            text="something gentle", intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
        )
        metrics = repository.metrics()
        assert metrics.llm_calls == 0
        assert metrics.llm_latency_ms_total == 0
        assert metrics.llm_tokens_total == 0
        assert metrics.guardrail_rejections_by_rule == {}
        assert metrics.llm_fallbacks_by_mode == {
            "intent:fallback_disabled": 1,
            "fallback_disabled": 1,
        }
    finally:
        repository.close()


def test_a_recorded_search_moves_the_cost_counters_off_zero(tmp_path: Path) -> None:
    """The counters M25 exists for: with a recorded transport the search path reaches a
    "model" twice (intent, then ranking), and both calls are counted with their latency even
    though neither request is in the recording and both degrade."""
    repository = _repository(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            adapter_mode="fixture",
            llm_enabled=True,
            llm_provider="recorded",
            llm_recording_path=str(_write_recording(tmp_path)),
            llm_model=_MODEL,
        )
    )
    try:
        repository.search_activities(
            text="something gentle", intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
        )
        metrics = repository.metrics()
        assert metrics.llm_calls == 2
        assert metrics.llm_fallbacks_by_mode == {
            "intent:fallback_error": 1,
            "fallback_error": 1,
        }
        assert sum(metrics.llm_fallbacks_by_mode.values()) == metrics.llm_calls
    finally:
        repository.close()


def test_the_search_audit_records_what_the_intent_parse_cost(tmp_path: Path) -> None:
    """The one LLM entry point that recorded nothing measurable now records latency and usage --
    on the evaluator's copy of the event only, never the senior's."""
    repository = _repository(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            adapter_mode="fixture",
            llm_enabled=True,
            llm_provider="recorded",
            llm_recording_path=str(_write_recording(tmp_path)),
            llm_model=_MODEL,
        )
    )
    try:
        response = repository.search_activities(
            text="something gentle", intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
        )
        assert "intent" not in response.audit_event.detail

        events = repository.list_events()
        search = next(event for event in events if event.event_type == "activity_search")
        intent = search.detail["intent"]
        assert intent["attempted"] is True
        assert intent["mode"] == "fallback_error"
        assert intent["model"] == "synthetic-scripted-stand-in-v1"
        assert "latency_ms" in intent
        assert "total_tokens" in intent
    finally:
        repository.close()
