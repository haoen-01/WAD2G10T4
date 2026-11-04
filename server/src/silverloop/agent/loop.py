"""The bounded tool loop shared by the family-facing agents (catch-up, "Read my day", the typed
appointment draft).

One shape for all of them: the model calls read-only tools over a context the caller already
assembled through permission-checked reads, then calls one terminal *submit* tool. A deterministic
`validate` rules on the submission; a rejection goes back to the model with the reasons, as in the
outreach planner. The loop never raises for a provider problem and never touches the database --
every way it can end is an `LoopOutcome.status` the caller turns into its own fallback.

The client comes from the outreach planner's `_build_client`: the same providers (OpenAI,
Anthropic, Bedrock), the same `recorded` replay transport, and the same refusal to build anything
when a provider is not configured. `llm_source` tells a reader which one wrote a result.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Literal

from silverloop.agent.constants import resolve_model
from silverloop.config import Settings
from silverloop.logging_config import agent_logger, request_id_var

LoopStatus = Literal["submitted", "disabled", "error", "no_proposal"]
LlmSource = Literal["live", "recorded"]

# `(payload_json, one_line_summary, ok)` for one read tool call.
ReadTool = Callable[[str, dict[str, Any]], tuple[str, str, bool]]
ClientFactory = Callable[[], tuple[Any, str | None]]

# A person is waiting on every one of these loops (a card on Home, the "Read my day" button, the
# "Fill in the form" button), so the whole run has a deadline: no new model turn starts after it,
# and the result falls back. Kept well inside the browser's own wait (`AGENT_TIMEOUT_MS`, 60 s, in
# `client/src/services/careApi.ts`) so the person always gets an answer, never a timeout.
DEADLINE_SECONDS = 40.0
# The most one whole request may take, worst case, so it ends before the browser gives up (60 s),
# with a margin for the reads and the check. A turn is only started when even its worst case
# (every attempt timing out) still ends inside this, and each attempt's timeout is clamped so that
# one turn's worst case always fits. The SDK's own retries are switched off for these loops (the
# Anthropic SDK honours a `retry-after` of up to 60 s, which alone would outlast the browser): the
# loop retries itself, and only when the wait plus another attempt still ends inside this budget.
REQUEST_BUDGET_SECONDS = 55.0
# The SDK's back-off when the provider gives no usable `retry-after` (`anthropic._constants`).
INITIAL_RETRY_DELAY = 0.5
MAX_RETRY_DELAY = 8.0
# Reading a few facts and writing a short, checked answer needs little reasoning; a deterministic
# check approves every result. Low effort keeps each turn to a few seconds (measured with
# gpt-5-mini: about 9-13 s for the four turns of a typed appointment, against 22-25 s at medium).
DEFAULT_EFFORT = "low"


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


def attempt_timeout(settings: Settings) -> float:
    """One provider attempt's timeout: `llm_timeout_seconds`, clamped so that a turn with every
    retry timing out (`llm_max_retries` + 1 attempts) still fits in `REQUEST_BUDGET_SECONDS`."""
    attempts = max(0, settings.llm_max_retries) + 1
    return min(settings.llm_timeout_seconds, REQUEST_BUDGET_SECONDS / attempts)


def turn_worst_case(settings: Settings) -> float:
    """How long one model turn can take when every attempt times out."""
    return attempt_timeout(settings) * (max(0, settings.llm_max_retries) + 1)


def default_client(settings: Settings) -> tuple[Any, str | None]:
    """The planner's client with the SDK's retries off: `run_tool_loop` retries itself, within
    the request budget. The outreach planner keeps building its own client with SDK retries."""
    from silverloop.agent.planner import _build_client

    return _build_client(
        settings.model_copy(update={"llm_max_retries": 0}), attempt_timeout(settings)
    )


def _retry_after_seconds(headers: Any) -> float | None:
    """The provider's requested wait (`retry-after-ms`, then `retry-after` as seconds or an HTTP
    date), parsed as the Anthropic SDK does; None when absent or unreadable."""
    if headers is None:
        return None
    raw_ms = headers.get("retry-after-ms")
    if raw_ms is not None:
        try:
            return float(raw_ms) / 1000
        except (TypeError, ValueError):
            pass
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    try:
        return parsedate_to_datetime(str(raw)).timestamp() - time.time()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def retry_wait(error: BaseException, retries_done: int) -> float | None:
    """How long to wait before retrying `error`, or None when it is not worth retrying.

    The same rule the Anthropic SDK applies (it covers the Bedrock clients too): connection errors
    and timeouts, and 408 / 409 / 429 / 5xx unless `x-should-retry` says otherwise; the wait is
    the provider's `retry-after` when it is between 0 and 60 s, otherwise exponential back-off.
    Errors from other clients (OpenAI, the recorded replay) are never retried, as before.
    """
    try:
        import anthropic
    except ImportError:
        return None

    response: Any = None
    retryable = False
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, anthropic.APIStatusError):
            response = current.response
            should = response.headers.get("x-should-retry")
            if should in ("true", "false"):
                retryable = should == "true"
            else:
                status = response.status_code
                retryable = status in (408, 409, 429) or status >= 500
            break
        if isinstance(current, anthropic.APIConnectionError):
            retryable = True
            break
        current = current.__cause__
    if not retryable:
        return None

    after = _retry_after_seconds(getattr(response, "headers", None))
    if after is not None and 0 < after <= 60:
        return after
    return min(INITIAL_RETRY_DELAY * pow(2.0, retries_done), MAX_RETRY_DELAY)


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
    effort: str = DEFAULT_EFFORT,
    deadline_seconds: float = DEADLINE_SECONDS,
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
    started = time.monotonic()
    # OpenAI reads the effort as `reasoning_effort` (`agent.openai_client`). The other providers
    # are left exactly as they were: an older Anthropic model rejects `output_config` outright.
    extras: dict[str, Any] = (
        {"output_config": {"effort": effort}} if settings.llm_provider == "openai" else {}
    )

    def end(status: LoopStatus, reason: str | None = None, **kwargs: Any) -> LoopOutcome:
        # One line per run for the operator: what happened and how long it took. Never the
        # person's words, the model's output or a key.
        agent_logger().info(
            "agent_loop_finished",
            extra={
                "structured_fields": {
                    "request_id": request_id_var.get(),
                    "loop": submit_tool,
                    "model": model,
                    "status": status,
                    "reason": reason,
                    "steps": [step.tool_name for step in steps],
                    "rejections": len(rejections),
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            },
        )
        return LoopOutcome(
            status=status,
            steps=steps,
            rejections=rejections,
            reason=reason,
            model=model,
            **kwargs,
        )

    worst_turn = turn_worst_case(settings)
    attempts = max(0, settings.llm_max_retries) + 1
    per_attempt = attempt_timeout(settings)

    def create() -> Any:
        """One model turn: up to `attempts` calls, retrying only while the wait plus another
        attempt still ends inside the request budget. Raises the last error otherwise."""
        for attempt in range(attempts):
            try:
                return client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=[{"type": "text", "text": system}],
                    tools=tools,
                    messages=messages,
                    **extras,
                )
            except Exception as error:
                wait = retry_wait(error, attempt) if attempt + 1 < attempts else None
                elapsed = time.monotonic() - started
                if wait is None or elapsed + wait + per_attempt > REQUEST_BUDGET_SECONDS:
                    raise
                time.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover - the loop returns or raises

    for iteration in range(1, max(1, settings.llm_max_iterations) + 1):
        elapsed = time.monotonic() - started
        if iteration > 1 and (
            elapsed > deadline_seconds or elapsed + worst_turn > REQUEST_BUDGET_SECONDS
        ):
            # Another turn could run past the browser's wait: answer now, without a model.
            return end("error", "DeadlineExceeded")
        try:
            response = create()
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
                    return end("submitted", arguments=arguments)
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
