"""The bounded tool loop shared by the family-facing agents (catch-up, "Read my day", the typed
appointment draft).

One shape for all of them: the model calls read-only tools over a context the caller already
assembled through permission-checked reads, then calls one terminal *submit* tool. A deterministic
`validate` rules on the submission; a rejection goes back to the model with the reasons, as in the
outreach planner. The loop never raises for a provider problem and never touches the database --
every way it can end is an `LoopOutcome.status` the caller turns into its own fallback.

The client comes from the outreach planner's `_build_client`: the same providers (Anthropic,
Bedrock), the same `recorded` replay transport, and the same refusal to build anything when a
provider is not configured. Live providers stay off until the team's data-sharing review (issue
#10); `llm_source` tells a reader which one wrote a result.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from silverloop.agent.constants import resolve_model
from silverloop.config import Settings

LoopStatus = Literal["submitted", "disabled", "error", "no_proposal"]
LlmSource = Literal["live", "recorded"]

# `(payload_json, one_line_summary, ok)` for one read tool call.
ReadTool = Callable[[str, dict[str, Any]], tuple[str, str, bool]]
ClientFactory = Callable[[], tuple[Any, str | None]]


@dataclass
class LoopStep:
    iteration: int
    tool_name: str
    ok: bool
    summary: str


@dataclass
class LoopOutcome:
    status: LoopStatus
    # The approved submission's arguments; set only when `status == "submitted"`.
    arguments: dict[str, Any] | None = None
    steps: list[LoopStep] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    reason: str | None = None
    model: str | None = None


def llm_source(settings: Settings) -> LlmSource:
    """Whether an agent-written result came from a real provider or a replayed recording."""
    return "recorded" if settings.llm_provider == "recorded" else "live"


def default_client(settings: Settings) -> tuple[Any, str | None]:
    from silverloop.agent.planner import _build_client

    return _build_client(settings, settings.llm_timeout_seconds)


def unknown_tool(name: str) -> tuple[str, str, bool]:
    return json.dumps({"error": f"Unknown tool {name!r}."}), f"Unknown tool {name!r}.", False


def run_tool_loop(
    *,
    settings: Settings,
    system: str,
    tools: list[dict[str, Any]],
    brief: str,
    submit_tool: str,
    read_tool: ReadTool,
    validate: Callable[[dict[str, Any]], list[str]],
    max_tokens: int = 1024,
    approved_summary: str = "Check approved it.",
    client_factory: ClientFactory | None = None,
) -> LoopOutcome:
    """Run one bounded loop. Every exit that is not an approved submission says why."""
    if not settings.llm_enabled:
        return LoopOutcome(status="disabled", reason="LLM_ENABLED is false.")

    client, unavailable = (client_factory or (lambda: default_client(settings)))()
    if client is None:
        return LoopOutcome(status="disabled", reason=unavailable or "No client.")

    model = resolve_model(settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": brief}]
    steps: list[LoopStep] = []
    rejections: list[str] = []

    def end(status: LoopStatus, reason: str) -> LoopOutcome:
        return LoopOutcome(
            status=status, steps=steps, rejections=rejections, reason=reason, model=model
        )

    for iteration in range(1, max(1, settings.llm_max_iterations) + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system}],
                tools=tools,
                messages=messages,
            )
        except Exception as error:  # noqa: BLE001 - provider errors must degrade, never raise
            return end("error", type(error).__name__)

        if getattr(response, "stop_reason", None) == "refusal":
            return end("error", "Refusal")
        content = getattr(response, "content", None)
        if not isinstance(content, list | tuple):
            return end("error", "MalformedResponse")
        uses = [block for block in content if getattr(block, "type", None) == "tool_use"]
        if not uses:
            return end("no_proposal", "The model ended without submitting.")

        messages.append({"role": "assistant", "content": list(content)})
        results: list[dict[str, Any]] = []
        for block in uses:
            raw = getattr(block, "input", None)
            arguments = dict(raw) if isinstance(raw, dict) else {}
            if block.name == submit_tool:
                violations = validate(arguments)
                steps.append(
                    LoopStep(
                        iteration=iteration,
                        tool_name=submit_tool,
                        ok=not violations,
                        summary=approved_summary
                        if not violations
                        else f"Check rejected: {'; '.join(violations)}",
                    )
                )
                if not violations:
                    return LoopOutcome(
                        status="submitted",
                        arguments=arguments,
                        steps=steps,
                        rejections=rejections,
                        model=model,
                    )
                rejections.extend(violations)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "REJECTED: " + " ".join(violations),
                        "is_error": True,
                    }
                )
                continue
            payload, line, ok = read_tool(block.name, arguments)
            steps.append(LoopStep(iteration=iteration, tool_name=block.name, ok=ok, summary=line))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": payload,
                    "is_error": not ok,
                }
            )
        messages.append({"role": "user", "content": results})

    return end("no_proposal", "The iteration budget ran out before an approved submission.")
