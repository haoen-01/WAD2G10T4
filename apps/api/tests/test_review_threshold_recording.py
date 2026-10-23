"""The review-threshold calibrator's committed recording replays through the guided sequence.

`tests/recordings/review_threshold/scripted.json` was produced by
`python -m silverloop.evaluation.ranking_llm.synthesise --threshold-only` against
`ScriptedThresholdModel` -- NOT A MODEL -- and says so in its banner. Replaying it through the same
`mdm-wong` sequence under `LLM_PROVIDER=recorded` exercises the calibration and write-up loops,
their guardrails and the stored run records offline, labelled `transport == "recorded"`.

No test records. A `live_demo.json` recorded by a human from a live provider, when committed,
must declare itself live.
"""

from __future__ import annotations

from typing import Any

import pytest

from silverloop.agent import planner as planner_module
from silverloop.agent.recorded_client import RecordedClient, Recording
from silverloop.evaluation.ranking_llm.harness import THRESHOLD_RECORDINGS, recorded_settings
from silverloop.evaluation.ranking_llm.scripted_model import SCRIPTED_MODEL_ID
from silverloop.evaluation.ranking_llm.synthesise import LIVE_BANNER
from silverloop.evaluation.ranking_llm.threshold_sequence import run_guided_threshold_sequence

SCRIPTED = THRESHOLD_RECORDINGS / "scripted.json"
LIVE_DEMO = THRESHOLD_RECORDINGS / "live_demo.json"


def _replay(client: RecordedClient | None) -> Any:
    settings = recorded_settings(SCRIPTED, model=SCRIPTED_MODEL_ID)
    return run_guided_threshold_sequence(
        settings=settings,
        client_factory=(lambda: (client, None)) if client is not None else None,
    )


def test_the_scripted_recording_is_synthetic_and_labelled() -> None:
    recording = Recording.load(SCRIPTED)
    assert recording.synthetic is True
    assert "NOT A MODEL" in recording.banner
    assert recording.loop == "review_threshold"
    assert recording.entries
    assert {entry.model for entry in recording.entries} == {SCRIPTED_MODEL_ID}


def test_the_guided_sequence_replays_as_recorded_agent_runs() -> None:
    client = RecordedClient(SCRIPTED, mode="replay")
    state = _replay(client)
    assert client.misses == []
    assert len(client.replayed) == client.recorded_count

    runs = {item.output_kind.value: item for item in state.proposals}
    assert set(runs) >= {"proposal", "write_up"}
    for item in state.proposals:
        run = item.agent_run
        assert run is not None
        assert run["mode"] == "agent", (item.output_kind, run["fallback_reason"])
        assert (run["provider"], run["transport"]) == ("recorded", "recorded")
        assert item.proposer.value == "agent"
    assert runs["proposal"].agent_run is not None
    assert runs["proposal"].agent_run["task"] == "calibrate"
    assert runs["write_up"].agent_run is not None
    assert runs["write_up"].agent_run["task"] == "write_up"
    [revert] = [item for item in state.decisions if item.kind.value == "reverted"]
    assert runs["write_up"].write_up_for_decision_id == revert.decision_id
    assert revert.revert_trigger is not None and revert.revert_trigger.value == "reached_too_late"


def test_two_replays_send_identical_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    first = RecordedClient(SCRIPTED, mode="replay")
    _replay(first)

    # The second run builds its client the product's way, through `_build_client`.
    built: list[Any] = []
    real = planner_module._build_client

    def capturing(settings: Any, timeout: float) -> tuple[Any, str | None]:
        client, unavailable = real(settings, timeout)
        if isinstance(client, RecordedClient) and settings.llm_recording_path == str(SCRIPTED):
            built.append(client)
        return client, unavailable

    monkeypatch.setattr(planner_module, "_build_client", capturing)
    second_state = _replay(None)
    threshold_clients = [client for client in built if client.replayed]
    second_keys = [call.key for client in threshold_clients for call in client.replayed]
    assert [call.key for call in first.replayed] == second_keys
    assert all(client.misses == [] for client in threshold_clients)
    assert all(
        (item.agent_run or {}).get("transport") == "recorded" for item in second_state.proposals
    )


def test_a_committed_live_demo_recording_declares_itself_live() -> None:
    if not LIVE_DEMO.exists():
        pytest.skip("live_demo.json is recorded by a human from a live provider; none committed")
    recording = Recording.load(LIVE_DEMO)
    assert recording.synthetic is False
    assert recording.banner == LIVE_BANNER
    assert recording.loop == "review_threshold"
