"""The "Read my day" agent: its loop, its check and its fallback."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from silverloop.agent.catchup import TaskToday
from silverloop.agent.demo_recording import ScriptedStandIn
from silverloop.agent.my_day import (
    DayAppointment,
    MyDayContext,
    execute_read_tool,
    fallback_my_day,
    spoken_clock,
    spoken_times,
    validate_my_day,
    write_my_day,
)
from silverloop.config import Settings

TODAY = date(2026, 11, 3)


def _context(**overrides: Any) -> MyDayContext:
    base: dict[str, Any] = {
        "senior_name": "Mdm Lim",
        "today": TODAY,
        "part_of_day": "morning",
        "appointments": [
            DayAppointment(
                title="Eye check-up",
                kind="medical",
                start="10:30",
                end="11:30",
                going_with=("John",),
            ),
            DayAppointment(
                title="Tea at 3pm with Mrs Ong", kind="social", start="15:00", end="16:00"
            ),
        ],
        "reminders": [
            TaskToday(title="Glass of water", time="09:00", done=True),
            TaskToday(title="Light stretching", time="17:00", done=False),
        ],
        "tomorrow": [
            DayAppointment(title="Grocery shopping", kind="errand", start="10:00", end="11:00")
        ],
    }
    base.update(overrides)
    return MyDayContext(**base)


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


class _Submits:
    """Submits each script in turn, as a model correcting itself after a rejection would."""

    def __init__(self, *scripts: str) -> None:
        self.scripts = list(scripts)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_: Any) -> SimpleNamespace:
        script = self.scripts.pop(0)
        block = SimpleNamespace(
            type="tool_use",
            id=f"toolu_{len(self.scripts)}",
            name="submit_my_day",
            input={"script": script},
        )
        return SimpleNamespace(content=[block], stop_reason="tool_use")


def test_the_agent_reads_the_day_then_writes_an_approved_script() -> None:
    result = write_my_day(
        _context(), settings=_settings(), client_factory=lambda: (ScriptedStandIn(), None)
    )
    assert result.mode == "agent", result.guardrail_rejections
    assert [call.tool_name for call in result.tool_calls] == [
        "get_my_appointments_today",
        "get_my_reminders_today",
        "get_tomorrow",
        "submit_my_day",
    ]
    assert "Eye check-up" in result.script
    assert "10:30 am" in result.script
    assert "<<<" not in result.script
    assert validate_my_day(result.script, _context()) == []


def test_with_the_flag_off_care_plus_reads_the_day_itself() -> None:
    result = write_my_day(_context(), settings=_settings(llm_enabled=False))
    assert result.mode == "fallback_disabled"
    assert result.tool_calls == []
    assert result.script.startswith("Good morning, Mdm Lim.")
    assert "Eye check-up at 10:30 am, and John is going with you" in result.script
    assert "Light stretching at 5 pm" in result.script
    assert "Glass of water" not in result.script  # already ticked off
    assert "Tomorrow starts with Grocery shopping at 10 am." in result.script


def test_the_fallback_always_passes_its_own_check() -> None:
    for context in (
        _context(),
        _context(appointments=[], reminders=[], tomorrow=[]),
        _context(reminders=[TaskToday(title="Glass of water", time="09:00", done=True)]),
    ):
        assert validate_my_day(fallback_my_day(context), context) == []


def test_a_time_the_tools_never_returned_is_rejected_and_retried() -> None:
    wrong = "Good morning, Mdm Lim. Your Eye check-up is at 9:45 am today, with John."
    right = "Good morning, Mdm Lim. Your Eye check-up is at 10:30 am today, with John."
    result = write_my_day(
        _context(), settings=_settings(), client_factory=lambda: (_Submits(wrong, right), None)
    )
    assert result.mode == "agent"
    assert result.script == right
    assert any("'9:45 am'" in rejection for rejection in result.guardrail_rejections)


def test_wellbeing_medicine_and_urgency_are_rejected() -> None:
    for script, rule in (
        ("Good morning, Mdm Lim. You are doing well and nothing is on today.", "judges"),
        ("Good morning, Mdm Lim. Remember your medication before the Eye check-up.", "clinical"),
        ("Good morning, Mdm Lim. You must do Light stretching at 5 pm.", "urgency"),
    ):
        assert any(rule in violation for violation in validate_my_day(script, _context())), script


def test_a_family_title_with_a_time_in_it_is_not_an_invented_time() -> None:
    script = "Good afternoon, Mdm Lim. Tea at 3pm with Mrs Ong starts at 3 pm."
    assert validate_my_day(script, _context()) == []


def test_spoken_times_reads_the_ways_people_write_a_time() -> None:
    assert spoken_clock("14:30") == "2:30 pm"
    assert spoken_clock("09:00") == "9 am"
    assert spoken_clock("00:15") == "12:15 am"
    found = dict(spoken_times("at 9:30, 2 pm, 10.15 a.m. and 2 reminders"))
    assert found == {"9:30": {570, 1290}, "2 pm": {840}, "10.15 a.m.": {615}}


def test_a_provider_error_falls_back_and_names_only_the_error_class() -> None:
    class Failing:
        messages = SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(TimeoutError("x")))

    result = write_my_day(
        _context(), settings=_settings(), client_factory=lambda: (Failing(), None)
    )
    assert result.mode == "fallback_error"
    assert result.fallback_reason == "TimeoutError"
    assert result.script.startswith("Good morning")


def test_names_and_titles_are_fenced_as_data() -> None:
    payload, _, ok = execute_read_tool("get_my_appointments_today", _context())
    assert ok
    assert "<<<untrusted_text" in payload
    assert "location" not in payload and "notes" not in payload
