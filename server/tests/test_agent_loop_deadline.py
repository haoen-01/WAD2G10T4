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


def _run(settings: Settings, provider: Any) -> agent_loop.LoopOutcome:
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


class _RateLimitedProvider:
    """Answers each call with a 429 carrying `retry_after` seconds, until `failures` calls have
    failed; then asks for the submit tool. Each call takes `seconds` on the fake clock."""

    def __init__(self, clock: _Clock, *, retry_after: str, failures: int, seconds: float) -> None:
        self.clock = clock
        self.retry_after = retry_after
        self.failures = failures
        self.seconds = seconds
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_: Any) -> SimpleNamespace:
        import anthropic
        import httpx

        self.calls += 1
        self.clock.now += self.seconds
        if self.calls <= self.failures:
            response = httpx.Response(
                429,
                headers={"retry-after": self.retry_after},
                request=httpx.Request("POST", "https://provider.invalid/v1/messages"),
            )
            raise anthropic.RateLimitError("rate limited", response=response, body=None)
        block = SimpleNamespace(type="tool_use", id="s1", name="submit", input={"ok": True})
        return SimpleNamespace(stop_reason="tool_use", content=[block])


def _patch_clock(monkeypatch: pytest.MonkeyPatch) -> tuple[_Clock, list[float]]:
    clock = _Clock()
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(agent_loop.time, "monotonic", clock)
    monkeypatch.setattr(agent_loop.time, "sleep", sleep)
    return clock, slept


def test_a_long_retry_after_is_not_waited_out_past_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A 429 with retry-after: 45 after 1 s: waiting it out and trying again (20 s) would end at
    # 66 s, past the browser's 60 s. The loop falls back at once instead of sleeping.
    clock, slept = _patch_clock(monkeypatch)
    provider = _RateLimitedProvider(clock, retry_after="45", failures=1, seconds=1.0)
    start = clock.now
    outcome = _run(_settings(), provider)

    assert outcome.status == "error"
    assert outcome.reason == "RateLimitError"
    assert provider.calls == 1
    assert slept == []
    assert clock.now - start <= REQUEST_BUDGET_SECONDS < BROWSER_TIMEOUT_SECONDS


def test_a_short_retry_after_is_retried_inside_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock, slept = _patch_clock(monkeypatch)
    provider = _RateLimitedProvider(clock, retry_after="3", failures=1, seconds=1.0)
    outcome = _run(_settings(), provider)

    assert outcome.status == "submitted"
    assert provider.calls == 2
    assert slept == [3.0]


def test_retries_stop_at_llm_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, slept = _patch_clock(monkeypatch)
    provider = _RateLimitedProvider(clock, retry_after="1", failures=5, seconds=1.0)
    outcome = _run(_settings(llm_max_retries=1), provider)

    assert outcome.status == "error"
    assert provider.calls == 2
    assert slept == [1.0]


def test_the_agent_client_has_sdk_retries_switched_off() -> None:
    # The SDK would honour a retry-after of up to 60 s on its own; the loop's client must not.
    settings = _settings(llm_provider="anthropic", llm_api_key="synthetic-not-a-key")
    client, unavailable = agent_loop.default_client(settings)
    assert unavailable is None
    assert client.max_retries == 0
    assert settings.llm_max_retries == 1  # the caller's settings are left as they were
