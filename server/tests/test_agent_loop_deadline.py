"""The family agents' loop always answers before the browser gives up (60 s), even when the
provider is slow: no turn starts whose worst case would run past the request budget."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from silverloop.agent import loop as agent_loop
from silverloop.agent.loop import (
    REQUEST_BUDGET_SECONDS,
    attempt_timeout,
    run_tool_loop,
    turn_worst_case,
)
from silverloop.config import Settings

# The browser's own wait for an agent route (`AGENT_TIMEOUT_MS` in client/src/services/careApi.ts).
BROWSER_TIMEOUT_SECONDS = 60.0


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "database_url": "sqlite+pysqlite:///:memory:",
        "llm_enabled": True,
        "llm_provider": "recorded",
        "llm_recording_path": "unused",
        "llm_model": "synthetic-scripted-stand-in-v1",
        "llm_max_iterations": 8,
        "llm_timeout_seconds": 20.0,
        "llm_max_retries": 1,
    }
    base.update(overrides)
    return Settings(**base)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _SlowProvider:
    """Takes `seconds` (on the fake clock) per turn and only ever asks for a read tool."""

    def __init__(self, clock: _Clock, seconds: float) -> None:
        self.clock = clock
        self.seconds = seconds
        self.turns = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_: Any) -> SimpleNamespace:
        self.turns += 1
        self.clock.now += self.seconds
        block = SimpleNamespace(type="tool_use", id=f"t{self.turns}", name="read", input={})
        return SimpleNamespace(stop_reason="tool_use", content=[block])


def _run(settings: Settings, provider: _SlowProvider) -> agent_loop.LoopOutcome:
    return run_tool_loop(
        settings=settings,
        system="s",
        tools=[{"name": "read"}, {"name": "submit"}],
        brief="b",
        submit_tool="submit",
        read_tool=lambda name, arguments: ("{}", "read", True),
        validate=lambda arguments: [],
        client_factory=lambda: (provider, None),
    )


def test_a_slow_provider_is_cut_off_before_the_browser_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(agent_loop.time, "monotonic", clock)
    provider = _SlowProvider(clock, seconds=12.0)
    start = clock.now
    outcome = _run(_settings(), provider)

    assert outcome.status == "error"
    assert outcome.reason == "DeadlineExceeded"
    # 12 s, then 24 s: a third turn could take another 40 s (two 20 s attempts), past 55 s.
    assert provider.turns == 2
    # Even had the last turn hit its worst case, the request would have ended in time.
    worst_end = (clock.now - start) - provider.seconds + turn_worst_case(_settings())
    assert worst_end <= REQUEST_BUDGET_SECONDS < BROWSER_TIMEOUT_SECONDS


def test_each_attempt_is_clamped_so_one_turn_always_fits() -> None:
    assert attempt_timeout(_settings()) == 20.0
    many = _settings(llm_timeout_seconds=30.0, llm_max_retries=4)
    assert attempt_timeout(many) == pytest.approx(REQUEST_BUDGET_SECONDS / 5)
    assert turn_worst_case(many) <= REQUEST_BUDGET_SECONDS


def test_a_quick_provider_is_not_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(agent_loop.time, "monotonic", clock)
    provider = _SlowProvider(clock, seconds=2.0)
    outcome = _run(_settings(llm_max_iterations=4), provider)
    # Four quick turns all run; the budget only ran out of iterations.
    assert provider.turns == 4
    assert outcome.status == "no_proposal"
