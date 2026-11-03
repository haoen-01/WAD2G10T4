"""The live-provider check: it refuses until approved, and drives all four agents' real loops."""

from __future__ import annotations

from typing import Any

import pytest

from silverloop.agent.demo_recording import ScriptedStandIn
from silverloop.agent.live_check import describe, main, refusal, run_live_check
from silverloop.config import Settings


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "database_url": "sqlite+pysqlite:///:memory:",
        "llm_enabled": True,
        "llm_provider": "anthropic",
        "llm_model": "synthetic-scripted-stand-in-v1",
    }
    base.update(overrides)
    return Settings(**base)


def test_it_refuses_without_the_teams_approval_a_flag_or_a_live_provider() -> None:
    assert "issue #10" in (refusal(_settings(), confirmed=False) or "")
    assert "LLM_ENABLED" in (refusal(_settings(llm_enabled=False), confirmed=True) or "")
    assert "recorded" in (refusal(_settings(llm_provider="recorded"), confirmed=True) or "")
    assert refusal(_settings(), confirmed=True) is None


def test_the_command_exits_without_running_anything_when_not_approved(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "silverloop.agent.live_check.run_live_check",
        lambda *_, **__: pytest.fail("nothing may run without approval"),
    )
    assert main([]) == 2
    assert "issue #10" in capsys.readouterr().err


def test_all_four_agents_run_their_real_loops_and_checks() -> None:
    # The stand-in in place of a provider: this proves the wiring, not a live model.
    results = run_live_check(_settings(), client_factory=lambda: (ScriptedStandIn(), None))
    assert [result.agent for result in results] == [
        "Outreach planner",
        "Since you last visited",
        "Read my day",
        "Typed appointment",
    ]
    for result in results:
        assert result.live, (result.agent, result.mode, result.reason, result.rejections)
        assert result.tools, result.agent
    report = describe(results)
    assert report.count("LIVE MODEL, check approved") == 4
    assert "key" not in report.lower()
