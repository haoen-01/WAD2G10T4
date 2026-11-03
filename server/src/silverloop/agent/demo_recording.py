"""Make, and replay, the offline agent demo: the outreach planner's real loop, without a model.

Why this exists
---------------
Live LLM work is on hold (team plan, issue #10) until the data sent to a provider is reviewed, so
no real model may be called. The planner's loop, tools and guardrail are still real code worth
showing, and `recorded_client` can drive them from a recording -- but this repository ships none.

This module produces one, honestly: a *scripted stand-in* plays the model's part. It calls the
same read-only tools a model would, chooses among the candidates the deterministic policy already
permitted, and submits a proposal the real guardrail then rules on. Nothing leaves the machine,
and the recording's banner says it is synthetic.

    uv run python -m silverloop.agent.demo_recording record   # writes the recording
    uv run python -m silverloop.agent.demo_recording replay   # replays it and prints the trace

Replay runs the app exactly as the offline demo would with `LLM_PROVIDER=recorded`: the planner
builds its own recorded client from settings, so a replay proves the recording is what the
running demo will read. A miss degrades to the deterministic ranker (`fallback_error`), never an
error, and is reported.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

STAND_IN_MODEL = "synthetic-scripted-stand-in-v1"
BANNER = (
    "SYNTHETIC -- produced by a scripted stand-in, not by any language model. "
    "It exercises the planner's real tools and guardrail offline."
)
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "recordings" / "demo-planner.json"
# The demo story's two days: day one's nudge, day two's programme suggestion.
DEMO_EVENTS: tuple[tuple[str, str], ...] = (
    ("activity_declines", "agent-demo-day-1"),
    ("activity_declines", "agent-demo-day-2"),
)

# The outreach loop's first turn: read the allow-list and the history before choosing.
_OUTREACH_READS: tuple[tuple[str, str], ...] = (
    ("a", "get_candidate_options"),
    ("b", "get_outreach_history"),
)

# The catch-up loop's first turn: everything it may say comes from these three reads.
_CATCH_UP_READS: tuple[tuple[str, str], ...] = (
    ("a", "get_recent_family_activity"),
    ("b", "get_visits_needing_someone"),
    ("c", "get_todays_tasks"),
)

# The "Read my day" loop's first turn: today, today's reminders, and tomorrow.
_MY_DAY_READS: tuple[tuple[str, str], ...] = (
    ("a", "get_my_appointments_today"),
    ("b", "get_my_reminders_today"),
    ("c", "get_tomorrow"),
)

# Outcomes that mean "do not lead with this again yet".
_AVOID_OUTCOMES = frozenset({"declined", "deferred", "no_response"})
_AVOID_FOLLOW_THROUGH = frozenset({"not_this_time", "unable"})


def _block(kind: str, **fields: Any) -> SimpleNamespace:
    return SimpleNamespace(type=kind, **fields)


def _response(blocks: list[SimpleNamespace], stop_reason: str = "tool_use") -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    # A declared stand-in latency, so a replay never reports a dict lookup as a model's speed.
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage, latency_ms=0)


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, Mapping) else getattr(item, name, None)


def _tool_results(messages: Sequence[Mapping[str, Any]]) -> dict[str, tuple[Any, bool]]:
    """`{tool_name: (decoded payload, is_error)}` for the tool results in the latest user turn."""
    if len(messages) < 2 or not isinstance(messages[-1].get("content"), list):
        return {}
    names = {
        _field(block, "id"): _field(block, "name")
        for block in messages[-2].get("content") or []
        if _field(block, "type") == "tool_use"
    }
    results: dict[str, tuple[Any, bool]] = {}
    for item in messages[-1]["content"]:
        if _field(item, "type") != "tool_result":
            continue
        name = names.get(_field(item, "tool_use_id"), "")
        content = _field(item, "content")
        try:
            payload = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            payload = content
        results[name] = (payload, bool(_field(item, "is_error")))
    return results


def _pick_candidate(candidates: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict:
    """The stand-in's judgement: skip what was recently turned down, then prefer what has worked."""
    turned_down = {
        _unfenced(entry.get("title")).lower()
        for entry in history
        if entry.get("outcome") in _AVOID_OUTCOMES
        or entry.get("follow_through") in _AVOID_FOLLOW_THROUGH
    }
    fresh = [c for c in candidates if _unfenced(c.get("title")).lower() not in turned_down]
    pool = fresh or candidates
    return max(pool, key=lambda c: float(c.get("preference_score") or 0.0))


def _unfenced(text: Any) -> str:
    """The data inside a `fence_untrusted` wrapper. A model reads the fence as a marker, never as
    words to repeat to the person."""
    value = str(text or "").strip()
    if value.startswith("<<<untrusted_text") and value.endswith(">>>"):
        value = value[len("<<<untrusted_text") : -len(">>>")].strip()
    return value


def _invitation(candidate: Mapping[str, Any], *, plain: bool) -> str:
    title = _unfenced(candidate.get("title")) or "something gentle"
    message = f"Would you like to try {title} today?"
    if not plain:
        message += " It is completely optional, and no pressure at all."
    missing = [
        word
        for word in candidate.get("must_preserve_words") or []
        if word.lower() not in message.lower()
    ]
    if missing:
        message += f" It can be done {' and '.join(missing)}."
    return message


class ScriptedStandIn:
    """Answers `messages.create` like a model would, deterministically, for both planner loops.

    Tool-use ids are derived from the turn number, so the same conversation always produces the
    same requests -- which is what lets the recording replay.
    """

    def __init__(self) -> None:
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        tools = {tool.get("name") for tool in kwargs.get("tools") or []}
        messages: list[Mapping[str, Any]] = list(kwargs.get("messages") or [])
        turn = len(messages)
        if "get_activity_options" in tools:
            return self._activity_turn(messages, turn)
        if "get_recent_family_activity" in tools:
            return self._catch_up_turn(messages, turn)
        if "get_my_appointments_today" in tools:
            return self._my_day_turn(messages, turn)
        if "get_calendar_context" in tools:
            return self._draft_turn(messages, turn)
        return self._outreach_turn(messages, turn)

    def _catch_up_turn(self, messages: list[Mapping[str, Any]], turn: int) -> SimpleNamespace:
        results = _tool_results(messages)
        if not results:
            return _response(
                [
                    _block("tool_use", id=f"toolu_{turn}_{suffix}", name=name, input={})
                    for suffix, name in _CATCH_UP_READS
                ]
            )
        feed = (_find_earlier(messages, "get_recent_family_activity") or {}).get("updates") or []
        visits = (_find_earlier(messages, "get_visits_needing_someone") or {}).get("visits") or []
        tasks = (_find_earlier(messages, "get_todays_tasks") or {}).get("tasks") or []
        others = [item for item in feed if not item.get("is_me")]
        highlights: list[str] = []
        people = sorted({_unfenced(item.get("actor_name")) for item in others})
        if people:
            highlights.append(f"New from {' and '.join(people[:2])} in the family group")
        for visit in visits[:2]:
            highlights.append(f"{_unfenced(visit.get('title'))} on {visit.get('weekday')} is open")
        opening = (
            f"While you were away, {' and '.join(people[:2])} kept things moving."
            if people
            else "It has been quiet in the family group since you last looked."
        )
        waiting = (
            f" {len(visits)} upcoming visit{'s' if len(visits) != 1 else ''} still "
            f"need{'s' if len(visits) == 1 else ''} someone to go along."
            if visits
            else " Every upcoming visit has someone going."
        )
        done = sum(1 for task in tasks if task.get("done"))
        today = f" {done} of {len(tasks)} of today's tasks are ticked off." if tasks else ""
        return _response(
            [
                _block(
                    "tool_use",
                    id=f"toolu_{turn}_s",
                    name="submit_catch_up",
                    input={"summary": opening + waiting + today, "highlights": highlights},
                )
            ]
        )

    def _my_day_turn(self, messages: list[Mapping[str, Any]], turn: int) -> SimpleNamespace:
        from silverloop.agent.my_day import spoken_clock

        if not _tool_results(messages):
            return _response(
                [
                    _block("tool_use", id=f"toolu_{turn}_{suffix}", name=name, input={})
                    for suffix, name in _MY_DAY_READS
                ]
            )
        today = _find_earlier(messages, "get_my_appointments_today") or {}
        reminders = (_find_earlier(messages, "get_my_reminders_today") or {}).get("reminders") or []
        tomorrow = (_find_earlier(messages, "get_tomorrow") or {}).get("appointments") or []
        sentences = [f"Good {today.get('part_of_day', 'day')}, {_unfenced(today.get('name'))}."]
        for item in (today.get("appointments") or [])[:2]:
            going = [_unfenced(name) for name in item.get("going_with") or []]
            company = f", and {' and '.join(going)} will come along" if going else ""
            sentences.append(
                f"At {spoken_clock(item['start'])} you have {_unfenced(item['title'])}{company}."
            )
        if not today.get("appointments"):
            sentences.append("Your calendar is clear today.")
        still = [item for item in reminders if not item.get("done")]
        if still:
            first = still[0]
            sentences.append(
                f"You have {len(still)} reminder{'s' if len(still) != 1 else ''} left, starting "
                f"with {_unfenced(first['title'])} at {spoken_clock(first['time'])}."
            )
        if tomorrow:
            sentences.append(
                f"Tomorrow, {_unfenced(tomorrow[0]['title'])} is at "
                f"{spoken_clock(tomorrow[0]['start'])}."
            )
        return _response(
            [
                _block(
                    "tool_use",
                    id=f"toolu_{turn}_s",
                    name="submit_my_day",
                    input={"script": " ".join(sentences)},
                )
            ]
        )

    def _draft_turn(self, messages: list[Mapping[str, Any]], turn: int) -> SimpleNamespace:
        from datetime import date as Date

        from silverloop.agent.appointment_draft import DATE_PHRASE, DraftContext, fallback_draft

        def call(suffix: str, name: str, **arguments: Any) -> SimpleNamespace:
            return _response(
                [_block("tool_use", id=f"toolu_{turn}_{suffix}", name=name, input=arguments)]
            )

        context = _find_earlier(messages, "get_calendar_context")
        if context is None:
            return call("a", "get_calendar_context")
        typed = _unfenced(context["typed"])
        resolved = _find_earlier(messages, "resolve_date")
        phrase = DATE_PHRASE.search(typed)
        if resolved is None and phrase:
            return call("b", "resolve_date", phrase=phrase.group(0))
        # The form's other fields as a careful reader of the sentence would fill them in.
        draft = fallback_draft(
            DraftContext(today=Date.fromisoformat(context["today"]), text=typed, upcoming=[])
        )
        day = (resolved or {}).get("date")
        if day and draft.start and draft.end and _find_earlier(messages, "check_clashes") is None:
            return call("c", "check_clashes", date=day, start=draft.start, end=draft.end)
        return call(
            "s",
            "submit_appointment_draft",
            title=draft.title,
            kind=draft.kind,
            date=day,
            start=draft.start,
            end=draft.end,
            location=draft.location,
            repeat=draft.repeat,
            missing=[name for name in draft.missing if name != "date"] + ([] if day else ["date"]),
            assumed=draft.assumed,
        )

    def _outreach_turn(self, messages: list[Mapping[str, Any]], turn: int) -> SimpleNamespace:
        results = _tool_results(messages)
        if "get_candidate_options" not in results and "propose_outreach" not in results:
            return _response(
                [
                    _block("tool_use", id=f"toolu_{turn}_{suffix}", name=name, input={})
                    for suffix, name in _OUTREACH_READS
                ]
            )
        candidates_payload = _find_earlier(messages, "get_candidate_options") or {}
        history_payload = _find_earlier(messages, "get_outreach_history") or {}
        candidates = list(candidates_payload.get("candidates") or [])
        if not candidates:
            return _response([_block("text", text="No candidates to choose from.")], "end_turn")
        history = list(history_payload.get("recent_outreach") or [])
        rejected_before = "propose_outreach" in results and results["propose_outreach"][1]
        chosen = _pick_candidate(candidates, history)
        reasoning = (
            f"Chose '{_unfenced(chosen.get('title'))}' from {len(candidates)} permitted option(s): "
            "it was not "
            "recently turned down and has the strongest record of being taken up."
        )
        return _response(
            [
                _block(
                    "tool_use",
                    id=f"toolu_{turn}_p",
                    name="propose_outreach",
                    input={
                        "candidate_key": chosen.get("candidate_key"),
                        "message": _invitation(chosen, plain=rejected_before),
                        "reasoning": reasoning,
                    },
                )
            ]
        )

    def _activity_turn(self, messages: list[Mapping[str, Any]], turn: int) -> SimpleNamespace:
        results = _tool_results(messages)
        if "get_activity_options" not in results and "propose_activity_order" not in results:
            return _response(
                [_block("tool_use", id=f"toolu_{turn}_a", name="get_activity_options", input={})]
            )
        payload = _find_earlier(messages, "get_activity_options") or {}
        options = list(payload.get("options") or [])
        keys = [str(option.get("activity_key")) for option in options]
        # Keep the deterministic order, but let a gentler option step up one place: the only
        # reordering the guardrail allows, and the kind of judgement the model is there for.
        if len(options) >= 2 and _gentler(options[1], options[0]):
            keys[0], keys[1] = keys[1], keys[0]
        return _response(
            [
                _block(
                    "tool_use",
                    id=f"toolu_{turn}_p",
                    name="propose_activity_order",
                    input={
                        "ordered_keys": keys,
                        "reasoning": "Kept the permitted order, with the gentler option first.",
                    },
                )
            ]
        )


_INTENSITY = {"low": 0, "light": 0, "gentle": 0, "moderate": 1, "medium": 1, "high": 2}


def _gentler(candidate: Mapping[str, Any], incumbent: Mapping[str, Any]) -> bool:
    def level(option: Mapping[str, Any]) -> int:
        return _INTENSITY.get(str(option.get("intensity") or "").lower(), 1)

    return level(candidate) < level(incumbent)


def _find_earlier(messages: Sequence[Mapping[str, Any]], tool_name: str) -> Any:
    """The decoded result of `tool_name`, from whichever earlier turn called it."""
    for index in range(len(messages) - 1, 0, -1):
        found = _tool_results(messages[: index + 1]).get(tool_name)
        if found is not None:
            return found[0]
    return None


# ── Running the demo ──────────────────────────────────────────────────────────────────────────


def _settings(database_url: str, recording: Path) -> Any:
    from silverloop.config import Settings

    return Settings(
        _env_file=None,
        database_url=database_url,
        silverloop_runtime_profile="offline",
        adapter_mode="fixture",
        external_context_enabled=False,
        auth_enabled=False,
        llm_enabled=True,
        llm_provider="recorded",
        llm_recording_path=str(recording),
        llm_model=STAND_IN_MODEL,
    )


@contextmanager
def _capture_runs() -> Iterator[list[Any]]:
    """Collect every `AgentRun` the outreach planner returns during the demo."""
    from silverloop import sql_repository

    runs: list[Any] = []
    real = sql_repository.plan_outreach

    def recording_plan(*args: Any, **kwargs: Any) -> Any:
        run = real(*args, **kwargs)
        runs.append(run)
        return run

    with mock.patch.object(sql_repository, "plan_outreach", recording_plan):
        yield runs


def run_demo(recording: Path, *, record: bool) -> list[Any]:
    """Play the demo days through the real `advance` route and return the planner's runs."""
    from fastapi.testclient import TestClient

    from silverloop.agent import planner
    from silverloop.agent.recorded_client import RecordedClient
    from silverloop.main import create_app

    # Windows keeps the SQLite file open until the engine is collected; a leftover temp file is
    # harmless, a crash after the recording was made is not.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        settings = _settings(f"sqlite+pysqlite:///{Path(scratch) / 'demo.db'}", recording)
        recorder: RecordedClient | None = None
        patches = []
        if record:
            recorder = RecordedClient(
                recording,
                mode="record",
                inner=ScriptedStandIn(),
                loop="outreach+activity",
                banner=BANNER,
                generator="silverloop.agent.demo_recording",
            )
            patches.append(mock.patch.object(planner, "_build_client", lambda *_: (recorder, None)))
        with _capture_runs() as runs:
            for patch in patches:
                patch.start()
            try:
                with TestClient(create_app(settings=settings)) as client:
                    for event, event_id in DEMO_EVENTS:
                        response = client.post(
                            "/v1/simulation/advance", json={"event": event, "event_id": event_id}
                        )
                        response.raise_for_status()
            finally:
                for patch in patches:
                    patch.stop()
        if recorder is not None:
            recording.parent.mkdir(parents=True, exist_ok=True)
            recorder.save(recording)
        return runs


def _describe(runs: Sequence[Any]) -> str:
    lines: list[str] = []
    for day, run in enumerate(runs, start=1):
        lines.append(f"Day {day}: planner mode = {run.mode} ({run.decision})")
        for call in run.tool_calls:
            lines.append(f"  [{call.iteration}] {call.tool_name}: {call.summary}")
        if run.proposal is not None:
            lines.append(f"  reasoning: {run.proposal.reasoning}")
        lines.append(f"  chose: {run.selected_candidate_key}")
        lines.append(f"  message: {run.selected_message}")
        if run.fallback_reason:
            lines.append(f"  fallback reason: {run.fallback_reason}")
    return "\n".join(lines) if lines else "The planner did not run (no outreach was permitted)."


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("record", "replay"))
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    arguments = parser.parse_args(argv)
    runs = run_demo(arguments.path, record=arguments.command == "record")
    print(_describe(runs))
    if arguments.command == "record":
        print(f"\nWrote {arguments.path}")
        return 0
    agent_runs = [run for run in runs if run.mode == "agent"]
    return 0 if runs and len(agent_runs) == len(runs) else 1


if __name__ == "__main__":
    sys.exit(main())
