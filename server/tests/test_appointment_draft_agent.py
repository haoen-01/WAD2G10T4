"""The typed-appointment agent: date resolution, its loop, its check and its fallback."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from silverloop.agent.appointment_draft import (
    Draft,
    DraftContext,
    ExistingAppointment,
    draft_appointment,
    execute_read_tool,
    fallback_draft,
    resolve_date,
    typed_times,
    validate_draft,
)
from silverloop.agent.demo_recording import ScriptedStandIn
from silverloop.config import Settings

TODAY = date(2026, 11, 3)  # a Tuesday
TYPED = "Eye check-up next Tuesday 10:30 to 11:30 at Bedok Polyclinic"


def _context(text: str = TYPED, **overrides: Any) -> DraftContext:
    base: dict[str, Any] = {"today": TODAY, "text": text, "upcoming": []}
    base.update(overrides)
    return DraftContext(**base)


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
    """Resolves the date, then submits each draft in turn, as a model correcting itself would."""

    def __init__(self, *drafts: dict[str, Any]) -> None:
        self.drafts = list(drafts)
        self.turn = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_: Any) -> SimpleNamespace:
        self.turn += 1
        if self.turn == 1:
            name, arguments = "resolve_date", {"phrase": "next Tuesday"}
        else:
            name, arguments = "submit_appointment_draft", self.drafts.pop(0)
        block = SimpleNamespace(type="tool_use", id=f"t{self.turn}", name=name, input=arguments)
        return SimpleNamespace(content=[block], stop_reason="tool_use")


GOOD = {
    "title": "Eye check-up",
    "kind": "medical",
    "date": "2026-11-10",
    "start": "10:30",
    "end": "11:30",
    "location": "Bedok Polyclinic",
    "repeat": "none",
    "missing": [],
}


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("today", date(2026, 11, 3)),
        ("tmr", date(2026, 11, 4)),
        ("next Tuesday", date(2026, 11, 10)),
        ("this Tuesday", date(2026, 11, 3)),
        ("friday", date(2026, 11, 6)),
        ("thurs", date(2026, 11, 5)),
        ("in 2 weeks", date(2026, 11, 17)),
        ("12 Nov", date(2026, 11, 12)),
        ("Nov 12th", date(2026, 11, 12)),
        ("3/12", date(2026, 12, 3)),  # day first
        ("1 Jan", date(2027, 1, 1)),  # a date already past this year is next year's
        ("2026-12-25", date(2026, 12, 25)),
    ],
)
def test_resolve_date_reads_the_ways_people_write_a_day(phrase: str, expected: date) -> None:
    assert resolve_date(phrase, TODAY)[0] == expected


def test_resolve_date_refuses_what_is_not_a_date() -> None:
    assert resolve_date("31/2", TODAY)[0] is None
    assert resolve_date("whenever", TODAY)[0] is None


def test_typed_times_guess_like_a_person_would() -> None:
    assert typed_times("lunch at 12.30")[0] == [750]
    assert typed_times("physio 2-3pm")[0] == [840, 900]
    assert typed_times("dentist 3:30")[0] == [930]
    assert typed_times("walk 9:15")[0] == [555]


def test_the_agent_resolves_the_date_and_fills_in_an_approved_form() -> None:
    upcoming = [ExistingAppointment("Grocery shopping", date(2026, 11, 10), "11:00", "12:00")]
    result = draft_appointment(
        _context(upcoming=upcoming),
        settings=_settings(),
        client_factory=lambda: (ScriptedStandIn(), None),
    )
    assert result.mode == "agent", result.guardrail_rejections
    assert [call.tool_name for call in result.tool_calls] == [
        "get_calendar_context",
        "resolve_date",
        "check_clashes",
        "submit_appointment_draft",
    ]
    draft = result.draft
    assert (draft.title, draft.kind, draft.date) == ("Eye check-up", "medical", date(2026, 11, 10))
    assert (draft.start, draft.end, draft.location) == ("10:30", "11:30", "Bedok Polyclinic")
    assert result.clashes == ["Grocery shopping"]


def test_a_date_worked_out_without_resolve_date_is_rejected_and_retried() -> None:
    guessed = GOOD | {"date": "2026-11-11"}
    result = draft_appointment(
        _context(), settings=_settings(), client_factory=lambda: (_Submits(guessed, GOOD), None)
    )
    assert result.mode == "agent"
    assert result.draft.date == date(2026, 11, 10)
    assert any("not returned by resolve_date" in r for r in result.guardrail_rejections)


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"start": "09:00"}, "not a time that was typed"),
        ({"end": "12:45"}, "not a time that was typed"),
        ({"location": "Tan Tock Seng Hospital"}, "place was not typed"),
        ({"title": "Ophthalmology review"}, "none of the words"),
        ({"title": None}, "title is empty but not listed"),
        ({"kind": "surgery"}, "not one the form allows"),
        ({"start": "11:30", "end": "10:30"}, "end time needs to be after"),
    ],
)
def test_the_check_rejects_anything_not_typed_or_not_allowed(
    change: dict[str, Any], rule: str
) -> None:
    context = _context()
    context.resolved.add(date(2026, 11, 10))
    fields = GOOD | change
    draft = Draft(
        title=fields["title"],
        kind=fields["kind"],
        date=date.fromisoformat(fields["date"]),
        start=fields["start"],
        end=fields["end"],
        location=fields["location"],
        repeat=fields["repeat"],
        missing=[],
    )
    assert any(rule in violation for violation in validate_draft(draft, context)), change


def test_an_assumed_end_is_one_hour_after_the_start() -> None:
    context = _context("Dentist tomorrow 3pm")
    context.resolved.add(date(2026, 11, 4))
    draft = Draft("Dentist", "medical", date(2026, 11, 4), "15:00", "16:00", assumed=["end"])
    assert validate_draft(draft, context) == []
    # The agent forgetting to list it as assumed is not a reason to throw away the time.
    draft.assumed = []
    assert validate_draft(draft, context) == []
    draft.end = "17:00"
    assert validate_draft(draft, context)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("Eye check-up tomorrow at 2pm", "14:00", "15:00"),
        ("Eye check-up tomorrow at 2:30 PM", "14:30", "15:30"),
        ("Eye check-up tomorrow 14:30", "14:30", "15:30"),
        ("Eye check-up tomorrow at 9am", "09:00", "10:00"),
        ("tomorrow at 9am eye check-up", "09:00", "10:00"),
        ("Eye check-up tomorrow at 2", "14:00", "15:00"),
        ("Eye check-up tomorrow at 9", "09:00", "10:00"),
        ("Eye check-up tomorrow at noon", "12:00", "13:00"),
        ("Eye check-up tomorrow at 1430", "14:30", "15:30"),
        ("Eye check-up tomorrow 1430hrs", "14:30", "15:30"),
        ("Eye check-up tomorrow 2 o'clock", "14:00", "15:00"),
        ("Eye check-up tomorrow afternoon 3", "15:00", "16:00"),
        ("Eye check-up tomorrow at 3 in the afternoon", "15:00", "16:00"),
        ("Eye check-up tomorrow morning at 9.30", "09:30", "10:30"),
        ("Eye check-up tomorrow 2-3pm", "14:00", "15:00"),
    ],
)
def test_the_time_is_filled_in_however_it_was_typed(text: str, start: str, end: str) -> None:
    context = _context(text)
    draft = fallback_draft(context)
    # The time fills in, the day is still tomorrow, and the time words are not left in the title.
    assert (draft.start, draft.end) == (start, end)
    assert draft.date == date(2026, 11, 4)
    assert draft.title == "Eye check-up"
    assert validate_draft(draft, context) == []


def test_a_bare_hour_the_agent_fills_in_passes_the_check() -> None:
    # "at 2" used to have no typed time, so the agent's 14:00 was rejected and the time left empty.
    context = _context("Eye check-up tomorrow at 2")
    context.resolved.add(date(2026, 11, 4))
    draft = Draft(
        title="Eye check-up",
        kind="medical",
        date=date(2026, 11, 4),
        start="14:00",
        end="15:00",
        assumed=["end"],
        missing=["location"],
    )
    assert validate_draft(draft, context) == []
    assert any(
        "not a time that was typed" in v
        for v in validate_draft(
            Draft(**{**draft.__dict__, "start": "16:00", "end": "17:00"}), context
        )
    )


def test_numbers_that_are_not_times_stay_out_of_the_form() -> None:
    assert typed_times("You have 2 reminders")[1] == set()
    assert typed_times("Party on 5 Nov 2026")[1] == set()
    # "at 2 Simei Street" is a place, not 2 o'clock.
    assert typed_times("Physio at 2 Simei Street")[1] == set()


def test_with_the_flag_off_a_plain_parser_fills_in_what_it_recognises() -> None:
    result = draft_appointment(_context(), settings=_settings(llm_enabled=False))
    assert result.mode == "fallback_disabled"
    assert result.tool_calls == []
    assert result.draft.title == "Eye check-up"
    assert result.draft.date == date(2026, 11, 10)
    assert result.draft.location == "Bedok Polyclinic"


@pytest.mark.parametrize(
    "text",
    [
        TYPED,
        "Taiji with Mdm Wong every Saturday 8am at the CC",
        "lunch tmr at 12.30",
        "kopi with John",
        "physio 3/12 2-3pm",
        "1 Jan 2020 dentist 10am",
        "remind me",
    ],
)
def test_the_fallback_always_passes_its_own_check(text: str) -> None:
    context = _context(text)
    assert validate_draft(fallback_draft(context), context) == []


def test_what_was_typed_is_fenced_and_clashes_name_titles_only() -> None:
    context = _context(
        upcoming=[ExistingAppointment("Grocery shopping", date(2026, 11, 10), "11:00", "12:00")]
    )
    payload, _, ok = execute_read_tool("get_calendar_context", {}, context)
    assert ok and "<<<untrusted_text" in payload
    payload, _, ok = execute_read_tool(
        "check_clashes", {"date": "2026-11-10", "start": "10:30", "end": "11:30"}, context
    )
    assert ok and "Grocery shopping" in payload


def test_a_provider_error_falls_back_to_the_parser() -> None:
    class Failing:
        messages = SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(TimeoutError("x")))

    result = draft_appointment(
        _context(), settings=_settings(), client_factory=lambda: (Failing(), None)
    )
    assert result.mode == "fallback_error"
    assert result.fallback_reason == "TimeoutError"
    assert result.draft.title == "Eye check-up"
