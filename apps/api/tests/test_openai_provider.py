"""OpenAI as an agent provider: the translation both ways, the builder, the runtime checks, and
all four agents through the real adapter against a fake OpenAI endpoint (no network, ever)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from silverloop.agent.constants import resolve_model
from silverloop.agent.demo_recording import ScriptedStandIn
from silverloop.agent.live_check import run_live_check
from silverloop.agent.openai_client import (
    MIN_COMPLETION_TOKENS,
    OpenAIChatClient,
    OpenAIRequestError,
    from_openai_response,
    to_openai_messages,
)
from silverloop.agent.planner import _build_client
from silverloop.config import Settings
from silverloop.runtime import RuntimeConfigurationError, validate_runtime

FAKE_KEY = "sk-test-not-a-real-key"


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "database_url": "sqlite+pysqlite:///:memory:",
        "llm_enabled": True,
        "llm_provider": "openai",
        "openai_api_key": FAKE_KEY,
        "openai_model": "gpt-5-mini",
        "llm_model": "",
    }
    base.update(overrides)
    return Settings(**base)


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _completion(*calls: dict[str, Any], content: str | None = None, finish: str = "tool_calls"):
    return {
        "model": "gpt-5-mini",
        "choices": [
            {
                "message": {"role": "assistant", "content": content, "tool_calls": list(calls)},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


# ── A fake OpenAI endpoint that "reasons" with the synthetic stand-in ───────────────────────────


def _back_to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The inverse of the adapter's translation, so the stand-in can answer an OpenAI request."""
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            continue
        if role == "assistant":
            out.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call["id"],
                            "name": call["function"]["name"],
                            "input": json.loads(call["function"]["arguments"]),
                        }
                        for call in message.get("tool_calls") or []
                    ],
                }
            )
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message["tool_call_id"],
                "content": message["content"],
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": "user", "content": message["content"]})
    return out


class FakeOpenAI:
    """Checks every request is a well-formed Chat Completions call, then answers it."""

    def __init__(self) -> None:
        self.stand_in = ScriptedStandIn()
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
        body = json.loads(request.content)
        self.requests.append(body)
        assert body["model"] == "gpt-5-mini"
        assert body["max_completion_tokens"] >= MIN_COMPLETION_TOKENS
        assert body["tool_choice"] == "required"
        assert body["messages"][0]["role"] == "system"
        assert all(tool["type"] == "function" for tool in body["tools"])
        # Every tool result answers a call the previous assistant turn made.
        open_calls: set[str] = set()
        for message in body["messages"]:
            if message["role"] == "assistant":
                open_calls = {call["id"] for call in message.get("tool_calls") or []}
            elif message["role"] == "tool":
                assert message["tool_call_id"] in open_calls
        answer = self.stand_in.messages.create(
            tools=[{"name": tool["function"]["name"]} for tool in body["tools"]],
            messages=_back_to_anthropic(body["messages"]),
        )
        calls = [
            _tool_call(block.id, block.name, block.input)
            for block in answer.content
            if block.type == "tool_use"
        ]
        return httpx.Response(200, json=_completion(*calls))


def _client_over(handler: Any) -> OpenAIChatClient:
    return OpenAIChatClient(
        api_key=FAKE_KEY,
        base_url="https://api.openai.test/v1",
        timeout=5,
        transport=httpx.MockTransport(handler),
    )


def test_all_four_agents_run_through_the_openai_adapter() -> None:
    fake = FakeOpenAI()
    results = run_live_check(_settings(), client_factory=lambda: (_client_over(fake.handler), None))
    for result in results:
        assert result.live, (result.agent, result.mode, result.reason, result.rejections)
        assert result.model == "gpt-5-mini"
        assert len(result.tools) >= 2, result.agent  # at least one read, then the submission
    assert len(fake.requests) >= 8


# ── Translation ──────────────────────────────────────────────────────────────────────────────


def test_tool_use_and_results_translate_to_openai_turns() -> None:
    messages = to_openai_messages(
        [{"type": "text", "text": "Be kind.", "cache_control": {"type": "ephemeral"}}],
        [
            {"role": "user", "content": "Begin."},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "c1", "name": "get_x", "input": {"a": 1}}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "c1", "content": "{}", "is_error": True}
                ],
            },
        ],
    )
    assert messages == [
        {"role": "system", "content": "Be kind."},
        {"role": "user", "content": "Begin."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_x", "arguments": '{"a": 1}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "ERROR: {}"},
    ]


def test_anthropic_only_options_never_reach_openai() -> None:
    body = _client_over(lambda _: httpx.Response(500)).request_body(
        model="gpt-5-mini",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system="s",
        tools=[{"name": "t", "input_schema": {"type": "object"}, "strict": True}],
        messages=[{"role": "user", "content": "hi"}],
    )
    assert "thinking" not in body and "output_config" not in body
    assert body["tools"][0]["function"] == {
        "name": "t",
        "description": "",
        "parameters": {"type": "object"},
    }
    assert body["max_completion_tokens"] == MIN_COMPLETION_TOKENS
    assert body["reasoning_effort"] == "medium"


def test_responses_map_to_stop_reasons_and_bad_arguments_become_empty() -> None:
    bad = _completion({"id": "c", "type": "function", "function": {"name": "t", "arguments": "{"}})
    response = from_openai_response(bad)
    assert response.stop_reason == "tool_use"
    assert response.content[0].input == {}
    refused = from_openai_response(
        {"choices": [{"message": {"refusal": "No."}, "finish_reason": "stop"}]}
    )
    assert refused.stop_reason == "refusal"
    assert from_openai_response({"choices": []}).content is None


# ── Failure, keys and configuration ──────────────────────────────────────────────────────────


def test_an_error_status_falls_back_and_never_carries_the_key_or_body() -> None:
    client = _client_over(lambda _: httpx.Response(401, json={"error": {"message": FAKE_KEY}}))
    with pytest.raises(OpenAIRequestError) as raised:
        client.messages.create(model="gpt-5-mini", max_tokens=10, messages=[])
    assert FAKE_KEY not in str(raised.value) and FAKE_KEY not in repr(client)
    assert raised.value.status_code == 401

    results = run_live_check(_settings(), client_factory=lambda: (client, None))
    assert {result.mode for result in results} == {"fallback_error"}
    assert {result.reason for result in results} == {"OpenAIRequestError"}


def test_the_builder_uses_the_teams_openai_settings() -> None:
    client, why = _build_client(_settings(), 5)
    assert isinstance(client, OpenAIChatClient) and why is None
    client, why = _build_client(_settings(openai_api_key=""), 5)
    assert client is None and "OPENAI_API_KEY" in (why or "")
    assert resolve_model(_settings()) == "gpt-5-mini"
    assert resolve_model(_settings(llm_model="gpt-5")) == "gpt-5"


def test_the_runtime_requires_the_key_and_the_offline_profile_refuses_openai() -> None:
    with pytest.raises(RuntimeConfigurationError, match="OPENAI_API_KEY"):
        validate_runtime(
            _settings(
                openai_api_key="",
                silverloop_runtime_profile="shared",
                database_url="postgresql+psycopg://u:p@db.example/test",
            )
        )
    with pytest.raises(RuntimeConfigurationError, match="offline fallback requires"):
        validate_runtime(_settings(silverloop_runtime_profile="offline", adapter_mode="fixture"))
