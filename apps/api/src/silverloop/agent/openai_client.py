"""OpenAI as an agent provider, behind the same `messages.create` surface as the others.

Every agent loop (the outreach and activity planners, the threshold calibrator, the catch-up,
"Read my day" and the typed appointment) talks to its client through one Anthropic-shaped call:
`client.messages.create(model, max_tokens, system, tools, messages, ...)` returning an object
with `content` blocks (`text`, `tool_use` with `id`/`name`/`input`), a `stop_reason` and `usage`.
`OpenAIChatClient` keeps that surface and translates both ways to OpenAI's Chat Completions
function calling, so no loop, tool, guardrail or fallback changes for this provider:

* system blocks -> one `system` message; tools -> `{"type": "function", "function": ...}`
  (`input_schema` becomes `parameters`; `strict` and other Anthropic-only keys are dropped -- the
  deterministic checks, not the schema, are what every result has to pass);
* an assistant turn's `tool_use` blocks -> `tool_calls`; a user turn's `tool_result` blocks ->
  one `tool` message each (OpenAI requires them straight after the assistant turn);
* `finish_reason` -> `stop_reason` (`tool_calls` -> `tool_use`, `length` -> `max_tokens`,
  a refusal or `content_filter` -> `refusal`), usage -> `input_tokens` / `output_tokens`.

Anthropic-only request options (`thinking`, `output_config`, `cache_control`) are ignored.

It uses `httpx`, as the assistant's OpenAI call already does: no new dependency. The key comes
from `OPENAI_API_KEY`, the team's existing setting, and is only ever put in the Authorization
header. A failed request raises `OpenAIRequestError` carrying the HTTP status alone -- never the
response body, which can echo the request -- and the loops record only the exception's class.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

import httpx

# Reasoning models spend completion tokens on thinking before they write anything, so a budget
# sized for the answer alone can end in an empty reply. Never ask for less than this.
MIN_COMPLETION_TOKENS = 4096

_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


class OpenAIRequestError(Exception):
    """The provider answered with an error status. Carries the status only, by design."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"OpenAI request failed with HTTP {status_code}.")
        self.status_code = status_code


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Iterable):
        return "\n".join(
            str(_field(block, "text", "")) for block in content if _field(block, "type") == "text"
        )
    return ""


def to_openai_tools(tools: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in tools
    ]


def to_openai_messages(system: Any, messages: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic-shaped `system` + `messages` -> Chat Completions `messages`."""
    out: list[dict[str, Any]] = []
    if system_text := _text_of(system):
        out.append({"role": "system", "content": system_text})
    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        blocks = list(content)
        if role == "assistant":
            calls = [
                {
                    "id": _field(block, "id"),
                    "type": "function",
                    "function": {
                        "name": _field(block, "name"),
                        "arguments": json.dumps(_field(block, "input") or {}),
                    },
                }
                for block in blocks
                if _field(block, "type") == "tool_use"
            ]
            turn: dict[str, Any] = {"role": "assistant", "content": _text_of(blocks) or None}
            if calls:
                turn["tool_calls"] = calls
            out.append(turn)
            continue
        text_parts: list[str] = []
        for block in blocks:
            kind = _field(block, "type")
            if kind == "tool_result":
                result = _field(block, "content", "")
                body = result if isinstance(result, str) else _text_of(result)
                if _field(block, "is_error"):
                    body = f"ERROR: {body}"
                out.append(
                    {"role": "tool", "tool_call_id": _field(block, "tool_use_id"), "content": body}
                )
            elif kind == "text":
                text_parts.append(str(_field(block, "text", "")))
        if text_parts:
            out.append({"role": "user", "content": "\n".join(text_parts)})
    return out


def _tool_choice(choice: Any) -> Any:
    # Unset means "required", not OpenAI's "auto": in every Care+ loop a turn that calls no tool
    # can only end in a fallback, so the model is always asked for a tool call.
    if choice is None:
        return "required"
    kind = _field(choice, "type")
    if kind == "any":
        return "required"
    if kind == "tool":
        return {"type": "function", "function": {"name": _field(choice, "name")}}
    if kind == "none":
        return "none"
    return "auto"


def from_openai_response(body: Mapping[str, Any]) -> SimpleNamespace:
    """Chat Completions response -> the Anthropic-shaped object every loop reads."""
    choices = body.get("choices") or []
    if not choices:
        # No choice at all: the loops treat a non-list `content` as a malformed response.
        return SimpleNamespace(content=None, stop_reason=None, usage=None)
    choice = choices[0]
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")
    blocks: list[SimpleNamespace] = []
    if text := message.get("content"):
        blocks.append(SimpleNamespace(type="text", text=text))
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        blocks.append(
            SimpleNamespace(
                type="tool_use",
                id=call.get("id"),
                name=function.get("name"),
                input=arguments if isinstance(arguments, dict) else {},
            )
        )
    if message.get("refusal") or finish == "content_filter":
        stop_reason = "refusal"
    elif finish == "tool_calls" or any(block.type == "tool_use" for block in blocks):
        stop_reason = "tool_use"
    elif finish == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "end_turn"
    usage = body.get("usage") or {}
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        model=body.get("model"),
        usage=SimpleNamespace(
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_read_input_tokens=int(
                (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            ),
            cache_creation_input_tokens=0,
        ),
    )


class OpenAIChatClient:
    """`client.messages.create(...)` over OpenAI Chat Completions. See the module docstring."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        effort: str = "medium",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 5.0))
        self._effort = _EFFORT.get(effort, "medium")
        self._transport = transport
        self.messages = SimpleNamespace(create=self._create)

    def __repr__(self) -> str:  # never show the header that carries the key
        return f"OpenAIChatClient(url={self._url!r})"

    def request_body(self, **kwargs: Any) -> dict[str, Any]:
        model = str(kwargs["model"])
        body: dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(kwargs.get("system"), kwargs.get("messages") or []),
            "max_completion_tokens": max(int(kwargs.get("max_tokens") or 0), MIN_COMPLETION_TOKENS),
        }
        if tools := kwargs.get("tools"):
            body["tools"] = to_openai_tools(tools)
            body["tool_choice"] = _tool_choice(kwargs.get("tool_choice"))
        if model.startswith(("gpt-5", "o")):
            body["reasoning_effort"] = self._effort
        return body

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        body = self.request_body(**kwargs)
        with httpx.Client(timeout=self._timeout, transport=self._transport) as http:
            response = http.post(self._url, json=body, headers=self._headers)
        if response.status_code >= 400:
            raise OpenAIRequestError(response.status_code)
        return from_openai_response(response.json())
