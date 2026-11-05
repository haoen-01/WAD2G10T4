"""One command to verify the four agents against a real provider, once the team has approved it.

    uv run python -m silverloop.agent.live_check --confirm-team-approval

Runs each agent once -- the outreach planner, "Since you last visited", "Read my day" and the
typed appointment -- through its real loop, real tools and real check, against the provider the
environment configures (`LLM_ENABLED=true` and `LLM_PROVIDER=openai`, `anthropic` or `bedrock`).
Every context here is **synthetic** and built in this file: no database is opened and no real
person's data is read, so even this check sends nothing about a real family.

It refuses to run without `--confirm-team-approval` (live LLM use is on hold pending the team's
data-sharing review, issue #10), with the flag off, or with the `recorded` replay transport, which
would prove nothing about a live model. It prints what each agent did and never prints a key.
Exit status 0 only when all four reached `agent` mode, i.e. a live model wrote each result and the
deterministic check approved it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from silverloop.agent.appointment_draft import DraftContext, ExistingAppointment, draft_appointment
from silverloop.agent.catchup import CatchUpContext, FeedItem, OpenVisit, TaskToday, write_catch_up
from silverloop.agent.loop import ClientFactory
from silverloop.agent.my_day import DayAppointment, MyDayContext, write_my_day
from silverloop.agent.planner import plan_outreach
from silverloop.agent.tools import CandidateOption, HistoryEntry, ProgrammeOption, ToolContext
from silverloop.config import Settings
from silverloop.models import Decision

SENIOR = "Mdm Tan (synthetic)"


@dataclass
class CheckResult:
    agent: str
    mode: str
    tools: list[str]
    rejections: list[str] = field(default_factory=list)
    reason: str | None = None
    model: str | None = None
    output: str = ""

    @property
    def live(self) -> bool:
        return self.mode == "agent"


def _outreach(settings: Settings, factory: ClientFactory | None) -> CheckResult:
    context = ToolContext(
        decision=Decision.GENTLE_NUDGE,
        display_name=SENIOR,
        preferred_language="English",
        context_note=None,
        delta_percent=-25.0,
        sustained_low_days=2,
        confidence=0.8,
        rainy=False,
        holiday=False,
        candidates=[
            CandidateOption("gentle_nudge:indoor_walk", "Gentle movement check-in", 0.5, 2, 1),
            CandidateOption("gentle_nudge:chair_mobility", "Five-minute movement option", 0.7),
        ],
        programmes=[
            ProgrammeOption(
                key="programme:synthetic-taichi",
                name="Morning Tai Chi (synthetic)",
                venue="Synthetic CC",
                distance_km=0.4,
                next_session=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
                accessibility=["step-free"],
            )
        ],
        history=[HistoryEntry("2026-01-01T12:00:00+00:00", "gentle_nudge", "Check-in", "declined")],
    )
    run = plan_outreach(
        context,
        settings=settings,
        fallback_choice=("gentle_nudge:chair_mobility", "Would a five-minute stretch suit you?"),
        client_factory=factory,
    )
    return CheckResult(
        agent="Outreach planner",
        mode=run.mode,
        tools=[call.tool_name for call in run.tool_calls],
        rejections=run.guardrail_rejections,
        reason=run.fallback_reason,
        model=run.model,
        output=run.proposal.message if run.proposal else "",
    )


def _catch_up(settings: Settings, factory: ClientFactory | None, today: date) -> CheckResult:
    context = CatchUpContext(
        senior_name=SENIOR,
        today=today,
        since=datetime.now(UTC) - timedelta(days=2),
        feed=[
            FeedItem(
                datetime.now(UTC) - timedelta(hours=20),
                "John",
                False,
                "check_in",
                None,
                None,
                "visited",
            ),
            FeedItem(
                datetime.now(UTC) - timedelta(hours=3),
                "Emily",
                False,
                "helper_joined",
                "Physio session",
                today + timedelta(days=2),
            ),
        ],
        open_visits=[OpenVisit("Eye check-up", today + timedelta(days=1), "10:00", "medical")],
        tasks_today=[
            TaskToday("Glass of water", "09:00", True),
            TaskToday("Light stretching", "17:00", False),
        ],
    )
    result = write_catch_up(context, settings=settings, client_factory=factory)
    return CheckResult(
        agent="Since you last visited",
        mode=result.mode,
        tools=[call.tool_name for call in result.tool_calls],
        rejections=result.guardrail_rejections,
        reason=result.fallback_reason,
        model=result.model,
        output=" | ".join([result.summary, *result.highlights]),
    )


def _my_day(settings: Settings, factory: ClientFactory | None, today: date) -> CheckResult:
    context = MyDayContext(
        senior_name=SENIOR,
        today=today,
        part_of_day="morning",
        appointments=[DayAppointment("Eye check-up", "medical", "10:30", "11:30", ("John",))],
        reminders=[
            TaskToday("Glass of water", "09:00", True),
            TaskToday("Light stretching", "17:00", False),
        ],
        tomorrow=[DayAppointment("Grocery shopping", "errand", "10:00", "11:00")],
    )
    result = write_my_day(context, settings=settings, client_factory=factory)
    return CheckResult(
        agent="Read my day",
        mode=result.mode,
        tools=[call.tool_name for call in result.tool_calls],
        rejections=result.guardrail_rejections,
        reason=result.fallback_reason,
        model=result.model,
        output=result.script,
    )


def _draft(settings: Settings, factory: ClientFactory | None, today: date) -> CheckResult:
    context = DraftContext(
        today=today,
        text="Dental check next Thursday 2:30 to 3:30pm at Synthetic Polyclinic",
        upcoming=[
            ExistingAppointment("Physio session", today + timedelta(days=9), "14:00", "15:00")
        ],
    )
    result = draft_appointment(context, settings=settings, client_factory=factory)
    filled = result.draft
    return CheckResult(
        agent="Typed appointment",
        mode=result.mode,
        tools=[call.tool_name for call in result.tool_calls],
        rejections=result.guardrail_rejections,
        reason=result.fallback_reason,
        model=result.model,
        output=(
            f"{filled.title} | {filled.kind} | {filled.date} {filled.start}-{filled.end} | "
            f"{filled.location} | missing={filled.missing} assumed={filled.assumed} "
            f"clashes={result.clashes}"
        ),
    )


def run_live_check(
    settings: Settings, *, client_factory: ClientFactory | None = None
) -> list[CheckResult]:
    today = date.today()
    return [
        _outreach(settings, client_factory),
        _catch_up(settings, client_factory, today),
        _my_day(settings, client_factory, today),
        _draft(settings, client_factory, today),
    ]


def refusal(settings: Settings, confirmed: bool) -> str | None:
    """Why this check may not run, or None."""
    if not confirmed:
        return (
            "Live LLM use is on hold pending the team's data-sharing review (issue #10). Run with "
            "--confirm-team-approval only once the team has approved it."
        )
    if not settings.llm_enabled:
        return "LLM_ENABLED is false. Set LLM_ENABLED=true for this check."
    if settings.llm_provider == "recorded":
        return "LLM_PROVIDER=recorded replays a file; it proves nothing about a live model."
    return None


def describe(results: Sequence[CheckResult]) -> str:
    lines: list[str] = []
    for result in results:
        verdict = "LIVE MODEL, check approved" if result.live else f"FELL BACK ({result.mode})"
        lines.append(f"{result.agent}: {verdict}")
        lines.append(f"  model: {result.model or '-'}")
        lines.append(f"  tools: {', '.join(result.tools) or '-'}")
        if result.rejections:
            lines.append(f"  check rejected first: {len(result.rejections)} reason(s)")
        if result.reason:
            lines.append(f"  fallback reason: {result.reason}")
        lines.append(f"  output: {result.output}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm-team-approval", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings()
    if why := refusal(settings, args.confirm_team_approval):
        print(why, file=sys.stderr)
        return 2
    print(f"Provider: {settings.llm_provider}. Every context below is synthetic.\n")
    results = run_live_check(settings)
    print(describe(results))
    return 0 if all(result.live for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
