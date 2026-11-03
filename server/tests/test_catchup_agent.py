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
    assert "1 of 2 of today's tasks are done" in result.summary
    # The reader's own call is not news to them.
    assert all("You " not in line for line in result.highlights)


def test_the_fallback_always_passes_its_own_check() -> None:
    for context in (_context(), _context(feed=[], open_visits=[], tasks_today=[])):
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
