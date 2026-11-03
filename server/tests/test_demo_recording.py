"""The committed offline agent demo replays through the real planner loop.

Replay only: no test uses record mode (see `silverloop.agent.recorded_client`). The recording is
made by hand with `python -m silverloop.agent.demo_recording record` and reviewed in the diff.
"""

from __future__ import annotations

import json

from silverloop.agent.demo_recording import BANNER, DEFAULT_PATH, ScriptedStandIn, run_demo


def test_the_committed_recording_is_labelled_synthetic() -> None:
    document = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    assert document["synthetic"] is True
    assert document["banner"] == BANNER


def test_day_one_replays_through_the_real_tools_and_guardrail() -> None:
    runs = run_demo(DEFAULT_PATH, record=False)
    assert len(runs) == 2
    first = runs[0]
    assert first.mode == "agent"
    assert [call.tool_name for call in first.tool_calls] == [
        "get_candidate_options",
        "get_outreach_history",
        "propose_outreach",
    ]
    assert first.tool_calls[-1].ok  # the real guardrail approved the stand-in's proposal
    assert "<<<" not in first.selected_message
    # Day two's history carries a wall-clock timestamp, so its request differs on every run: the
    # recording misses and the planner falls back to the deterministic choice, as designed.
    second = runs[1]
    assert second.mode in {"agent", "fallback_error"}
    assert second.selected_candidate_key


def test_the_stand_in_asks_for_the_allow_list_before_proposing() -> None:
    brief = [{"role": "user", "content": "Plan outreach."}]
    response = ScriptedStandIn().messages.create(
        model="m", tools=[{"name": "get_candidate_options"}], messages=brief
    )
    assert [block.name for block in response.content] == [
        "get_candidate_options",
        "get_outreach_history",
    ]
