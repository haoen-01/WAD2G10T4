"""The "Since you last visited" agent: its loop, its check and its fallback."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from silverloop.agent.catchup import (
    CatchUpContext,
    FeedItem,
    OpenVisit,
    TaskToday,
    execute_read_tool,
    fallback_catch_up,
    short_date,
    validate_catch_up,
    write_catch_up,
)
from silverloop.agent.demo_recording import ScriptedStandIn
from silverloop.config import Settings

TODAY = date(2026, 11, 3)


def _context(**overrides: Any) -> CatchUpContext:
    base: dict[str, Any] = {
        "senior_name": "Mdm Lim",
        "today": TODAY,
        "since": datetime(2026, 11, 1, tzinfo=UTC),
        "feed": [
            FeedItem(
                at=datetime(2026, 11, 2, 9, tzinfo=UTC),
                actor_name="John",
                is_me=False,
                kind="check_in",
                check_in_kind="visited",
            ),
            FeedItem(
                at=datetime(2026, 11, 3, 8, tzinfo=UTC),
                actor_name="Emily",
                is_me=False,
                kind="helper_joined",
                appointment_title="Physiotherapy session",
                on_date=date(2026, 11, 5),
            ),
            FeedItem(
                at=datetime(2026, 11, 3, 8, tzinfo=UTC),
                actor_name="Sarah",
                is_me=True,
                kind="check_in",
                check_in_kind="called",
            ),
        ],
        "open_visits": [
            OpenVisit(
                title="Doctor's appointment", day=date(2026, 11, 4), start="10:00", kind="medical"
            ),
            OpenVisit(
                title="Grocery shopping", day=date(2026, 11, 7), start="10:00", kind="errand"
            ),
        ],
        "tasks_today": [
            TaskToday(title="Blood pressure tablet", time="08:00", done=True),
            TaskToday(title="Light stretching", time="17:00", done=False),
        ],
    }
    base.update(overrides)
    return CatchUpContext(**base)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "database_url": "sqlite+pysqlite:///:memory:",
        "silverloop_runtime_profile": "offline",
        "adapter_mode": "fixture",
        "llm_enabled": True,
        "llm_provider": "recorded",
        "llm_recording_path": "unused",
        "llm_model": "synthetic-scripted-stand-in-v1",
    }
    base.update(overrides)
    return Settings(**base)


def test_the_agent_reads_every_tool_then_submits_an_approved_catch_up() -> None:
    result = write_catch_up(
        _context(), settings=_settings(), client_factory=lambda: (ScriptedStandIn(), None)
    )
    assert result.mode == "agent"
    assert [call.tool_name for call in result.tool_calls] == [
        "get_recent_family_activity",
        "get_visits_needing_someone",
        "get_todays_tasks",
        "submit_catch_up",
    ]
    assert result.tool_calls[-1].ok
    assert "Emily" in result.summary and "John" in result.summary
    assert "2 upcoming visits still need someone" in result.summary
    assert any("Doctor's appointment" in line for line in result.highlights)
    assert "<<<" not in result.summary + " ".join(result.highlights)


def test_with_the_flag_off_the_fallback_says_the_same_things() -> None:
    result = write_catch_up(_context(), settings=_settings(llm_enabled=False))
    assert result.mode == "fallback_disabled"
    assert "2 updates from the family" in result.summary
    assert "2 visits still need someone" in result.summary
    assert "1 of 2 tasks done today." in result.summary
    # The reader's own call is not news to them.
    assert all("You " not in line for line in result.highlights)


def test_a_return_visit_says_what_changed_since_they_last_looked() -> None:
    summary, _ = fallback_catch_up(_context())
    assert summary.startswith("2 updates from the family since you last looked.")
    summary, _ = fallback_catch_up(_context(feed=[]))
    assert summary.startswith("No new updates from the family since you last looked.")


def test_a_first_visit_says_where_things_stand_not_since_you_last_looked() -> None:
    summary, _ = fallback_catch_up(_context(since=None))
    assert summary.startswith("2 recent updates from the family.")
    assert "since you last looked" not in summary
    one = _context(since=None, feed=_context().feed[:1])
    assert fallback_catch_up(one)[0].startswith("1 recent update from the family.")
    summary, _ = fallback_catch_up(_context(since=None, feed=[]))
    assert summary.startswith("No recent updates from the family.")
    assert "since you last looked" not in summary


def test_the_task_sentence_counts_tasks_done_today() -> None:
    none_done = [TaskToday(title=f"Task {n}", time="09:00", done=False) for n in range(5)]
    assert "0 of 5 tasks done today." in fallback_catch_up(_context(tasks_today=none_done))[0]
    one = [TaskToday(title="Light stretching", time="17:00", done=True)]
    assert "1 of 1 task done today." in fallback_catch_up(_context(tasks_today=one))[0]
    assert "tasks done" not in fallback_catch_up(_context(tasks_today=[]))[0]


def test_open_visits_are_dated_like_the_rest_of_the_app() -> None:
    assert short_date(date(2026, 8, 18)) == "Tue, 18 Aug"
    assert short_date(date(2026, 11, 5)) == "Thu, 5 Nov"
    _, highlights = fallback_catch_up(_context())
    assert "Doctor's appointment on Wed, 4 Nov needs someone" in highlights
    assert "Grocery shopping on Sat, 7 Nov needs someone" in highlights


def test_the_agent_is_told_whether_this_is_a_first_visit() -> None:
    briefs: list[str] = []

    def recording() -> tuple[Any, None]:
        stand_in = ScriptedStandIn()
        create = stand_in.messages.create

        def spy(**kwargs: Any) -> Any:
            briefs.append(str(kwargs["messages"][0]["content"]))
            return create(**kwargs)

        stand_in.messages = SimpleNamespace(create=spy)
        return stand_in, None

    for context in (_context(since=None), _context()):
        write_catch_up(context, settings=_settings(), client_factory=recording)
    assert "first look" in briefs[0]
    assert "since they last looked" in briefs[-1]


def test_the_fallback_always_passes_its_own_check() -> None:
    for context in (
        _context(),
        _context(since=None),
        _context(feed=[], open_visits=[], tasks_today=[]),
    ):
        summary, highlights = fallback_catch_up(context)
        assert validate_catch_up(summary, highlights, context) == []


def test_a_provider_error_degrades_to_the_fallback() -> None:
    def broken(**_: Any) -> Any:
        raise TimeoutError("slow")

    client = SimpleNamespace(messages=SimpleNamespace(create=broken))
    result = write_catch_up(_context(), settings=_settings(), client_factory=lambda: (client, None))
    assert result.mode == "fallback_error"
    assert result.fallback_reason == "TimeoutError"
    assert result.summary


def test_the_check_refuses_wellbeing_claims_urgency_and_invented_names() -> None:
    context = _context()
    violations = validate_catch_up(
        "Mdm Lim is fine and doing well, nothing to worry about today.",
        ["Uncle Tan dropped by"],
        context,
    )
    joined = " ".join(violations)
    assert "judges how the older person is" in joined
    assert "names nothing the tools returned" in joined


def test_the_check_refuses_copied_fence_markers() -> None:
    violations = validate_catch_up(
        "<<<untrusted_text John >>> visited while you were away.", [], _context()
    )
    assert any("data marker" in violation for violation in violations)


def test_notes_never_reach_the_model() -> None:
    payload, _, ok = execute_read_tool("get_recent_family_activity", _context())
    assert ok
    assert '"note"' not in payload
