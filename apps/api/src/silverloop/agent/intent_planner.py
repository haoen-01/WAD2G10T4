from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from silverloop.agent.constants import default_model_id
from silverloop.agent.planner import log_provider_failure
from silverloop.agent.prompt_safety import UNTRUSTED_TEXT_NOTICE, fence_untrusted
from silverloop.config import Settings
from silverloop.models import (
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    IndoorOutdoor,
    IntentParser,
    SocialPreference,
    TimeWindow,
)
from silverloop.ontology import activity_type_enum_values

# Reading a sentence into a typed request, with a model.
#
# The other half of "two parsers, one intent". `silverloop.intent.parse_intent` is the
# deterministic keyword reader that always works -- including under `demo:offline`, where
# `runtime.py` forbids the planner outright. This is the better reader, used when one is
# reachable, and it emits exactly the same `ActivityIntent`, so nothing downstream can tell them
# apart or needs to.
#
# What the model is allowed to do here is narrow: **translate a request into structure.** It never
# answers one. The one field that names an activity, `activity_types`, is a closed enum built from
# `ontology.ActivityType` at import: the model can say "they asked for a walk", never "here is a
# walk they should go on". It cannot invent a kind, an id, a title or a venue, because there is
# nowhere in the schema to put one -- the schema, not the prompt, is what prevents it.
#
# Every failure path returns the deterministic parse. A model that is unreachable, slow, refuses,
# returns no tool call, or returns something that does not validate costs the person nothing worse
# than the keyword reading they would have had anyway.

MAX_TOKENS = 512


@dataclass
class IntentTelemetry:
    """What one intent-parse attempt cost, filled in by `plan_intent` when the caller asks.

    The parse is the one LLM entry point in this repository that recorded *nothing* measurable:
    the search audit stored `intent_mode` and `parsed_by` and no latency, no usage and no model,
    so "the parser is worth its cost" had no denominator anywhere. This is an out-parameter
    rather than a third return value on purpose -- `plan_intent`'s `(intent, mode)` contract is
    used by four call sites and a dozen tests, and widening it would churn all of them to record
    a number most of them do not want.

    `attempted` is False whenever no request was made at all (planner off, empty text, no
    client), which is what keeps `llm_calls` a count of actual calls rather than of opportunities.
    """

    attempted: bool = False
    model: str | None = None
    latency_ms: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    fallback_error: str | None = None
    """The exception CLASS behind a `fallback_error` mode, or `None`.

    Set by whoever caught the failure -- `plan_intent` handles the provider call itself, and the
    repository's guard catches anything raised outside it. Never the exception's text:
    `log_provider_failure` puts that on the operator log with the request id, because this value
    reaches an append-only, coordinator-visible evidence row.
    """

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("input_tokens", 0)) + int(self.usage.get("output_tokens", 0))

    def as_evidence(self, mode: str) -> dict[str, Any]:
        """The compact record the search audit stores under `intent`. Counts and a class name
        only -- never the text the person typed, which this loop's audit has never carried."""
        return {
            "mode": mode,
            "attempted": self.attempted,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "usage": dict(sorted(self.usage.items())),
            "total_tokens": self.total_tokens,
            "fallback_error": self.fallback_error,
        }


_USAGE_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _record_usage(telemetry: IntentTelemetry, usage: Any) -> None:
    """Usage fields are optional on some responses; absent means zero, never an error."""
    if usage is None:
        return
    for name in _USAGE_FIELDS:
        telemetry.usage[name] = int(getattr(usage, name, 0) or 0)


SYSTEM_PROMPT = f"""You turn an older adult's request for something to do into a structured filter.

You are a translator, not an assistant. You never suggest, name, or describe an activity: your
only output is the `record_intent` tool call, and the schema has nowhere to put a recommendation.

Rules that matter more than being helpful:
- Only fill a field the person actually constrained. Everything defaults to "no preference", and
  leaving a field alone is always safer than guessing, because a wrong constraint silently hides
  the option they wanted.
- "Something nice", "anything really", "I don't mind" constrain nothing. Leave every field.
- Put anything you could not place into `unparsed_terms`. It is shown back to the person so they
  can correct you before anything acts on it. An empty list claims you understood everything.
- Dates are resolved against the day given in the request text. Never invent a date the person did
  not imply. A time of day on its own ("in the afternoon", "mornings are best") sets only
  `time_window` and leaves `on_date` null; set `on_date` only when they named a day ("today",
  "tomorrow", "on Saturday", a date).
- Distances are in metres. "Not too far", "nearby", "close to home" mean about 1000, and
  `distance_is_explicit` is true ONLY when the person gave a number. A phrase is a preference; a
  number is a limit, and only a limit is allowed to hide anything.
- A negated request fills an `excluded_*` field and NEVER the positive one. "Nothing outdoors"
  must not set `environment` to outdoor -- and must not set it to indoor either, because
  sheltered satisfies them too. Record what they ruled out; leave the axis alone.
- `activity_types` names only kinds the person literally asked for. A kind you infer from a mood
  ("something nice", "something to cheer me up") is a guess, and a guess here hides the thing
  they actually wanted.

{UNTRUSTED_TEXT_NOTICE}
"""


# Words that name today. A time of day on its own ("in the afternoon") does not: observed live on
# Claude Haiku 4.5 via Bedrock, the model read "something social in the afternoon" as today's date,
# which filtered 28 of 29 listings out of a request that never mentioned a day -- and it kept doing
# so after the prompt said not to. A date constraint hides options, so this one is checked in code.
_TODAY_WORDS = re.compile(
    r"\b(today|tonight|this (morning|afternoon|evening)|now|right away)\b", re.I
)


def _unasked_today(parsed: ActivityIntent, text: str, today: date) -> bool:
    """Whether the model pinned the request to today when nothing in it names today."""
    return parsed.on_date == today and not _TODAY_WORDS.search(text)


def _enum_values(enum_cls: type[Any], *, without: Any = None) -> list[str]:
    """The values of a `StrEnum`, for a tool schema.

    Built from the enum at import rather than typed out as literals. The hand-typed lists this
    replaces happened to match, but nothing pinned them: a member added to `TimeWindow` would
    have reached every other consumer and silently not the model, and a member removed would have
    been advertised to it and then rejected by `ActivityIntent` on arrival.
    """
    return [member.value for member in enum_cls if member is not without]


def _tool_definition(*, strict: bool) -> dict[str, Any]:
    definition: dict[str, Any] = {
        "name": "record_intent",
        "description": (
            "Record the structured request. Fill only fields the person actually constrained; "
            "leave the rest at their defaults."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "on_date": {
                    "type": ["string", "null"],
                    "description": "ISO date (YYYY-MM-DD), or null if no specific day was asked.",
                },
                "time_window": {"type": "string", "enum": _enum_values(TimeWindow)},
                "max_distance_m": {
                    "type": ["integer", "null"],
                    "description": "Metres. Null unless a distance limit was expressed.",
                },
                "distance_is_explicit": {
                    "type": "boolean",
                    "description": (
                        "True only if the person gave a number ('within 800m', 'under 2 km'). "
                        "False for a phrase such as 'nearby' or 'close to home'."
                    ),
                },
                "social_preference": {"type": "string", "enum": _enum_values(SocialPreference)},
                "environment": {"type": "string", "enum": _enum_values(ActivityEnvironment)},
                "intensity": {"type": "string", "enum": _enum_values(ActivityIntensity)},
                "language": {
                    "type": ["string", "null"],
                    "description": "A named language, or null. Never inferred from the request.",
                },
                "activity_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": activity_type_enum_values()},
                    "description": (
                        "Kinds of activity the person literally asked for. Empty unless they "
                        "named one; a word outside this list belongs in unparsed_terms."
                    ),
                },
                "excluded_activity_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": activity_type_enum_values()},
                    "description": "Kinds they ruled out ('no walking, my knee').",
                },
                "excluded_environments": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _enum_values(IndoorOutdoor, without=IndoorOutdoor.UNKNOWN),
                    },
                    "description": "Settings they ruled out ('nothing outdoors today').",
                },
                "excluded_social": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _enum_values(SocialPreference, without=SocialPreference.EITHER),
                    },
                    "description": "Company they ruled out ('I don't want a group class').",
                },
                "unparsed_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Words you could not place. Shown back to the person.",
                },
            },
            "required": [
                "on_date",
                "time_window",
                "max_distance_m",
                "distance_is_explicit",
                "social_preference",
                "environment",
                "intensity",
                "language",
                "activity_types",
                "excluded_activity_types",
                "excluded_environments",
                "excluded_social",
                "unparsed_terms",
            ],
            "additionalProperties": False,
        },
    }
    # No `maxItems` anywhere above: strict tool use rejects the keyword outright (Bedrock answers
    # 400 "For 'array' type, property 'maxItems' is not supported"), which silently sent every live
    # request to the keyword fallback. The bounds are not lost -- `ActivityIntent` enforces the
    # same `max_length` on each list, and an over-long answer lands in `fallback_invalid`.
    # Bedrock's InvokeModel surface rejects the presence of this key, not merely a false value.
    return {**definition, "strict": True} if strict else definition


_SCHEMA_KEYS: frozenset[str] = frozenset(
    _tool_definition(strict=False)["input_schema"]["properties"]
)


def _build_client(settings: Settings) -> tuple[Any, str | None]:
    from silverloop.agent.planner import _build_client as build

    return build(settings, settings.llm_timeout_seconds)


def plan_intent(
    text: str,
    *,
    today: date,
    settings: Settings,
    fallback: ActivityIntent,
    client_factory: Callable[[], tuple[Any, str | None]] | None = None,
    telemetry: IntentTelemetry | None = None,
) -> tuple[ActivityIntent, str]:
    """Read `text` into an `ActivityIntent`, returning `(intent, mode)`.

    `fallback` is the deterministic parse, computed by the caller before this runs -- so a valid,
    fully usable answer exists whether or not a model is ever reached, and an identical one when
    the planner is switched off. `mode` names which happened, so the audit can record it rather
    than leaving a reader to guess whether the model was involved.
    """
    if not settings.llm_enabled:
        return fallback, "fallback_disabled"
    if not text.strip():
        return fallback, "fallback_disabled"

    factory = client_factory or (lambda: _build_client(settings))
    client, unavailable = factory()
    if client is None:
        return fallback, "fallback_disabled"

    modern = settings.llm_request_profile == "modern"
    system_blocks: list[dict[str, Any]] = [{"type": "text", "text": SYSTEM_PROMPT}]
    if modern:
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}
    request_extras: dict[str, Any] = {}
    if modern and not (
        settings.llm_provider == "bedrock" and settings.llm_bedrock_endpoint == "invoke"
    ):
        request_extras["output_config"] = {"effort": settings.llm_effort}

    model = settings.llm_model.strip() or default_model_id(settings.llm_provider)
    if telemetry is not None:
        telemetry.attempted = True
        telemetry.model = model
    started = time.perf_counter()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            **request_extras,
            system=system_blocks,
            tools=[_tool_definition(strict=modern)],
            tool_choice={"type": "tool", "name": "record_intent"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Today is {today.isoformat()}.\n"
                        f"The person asked: {fence_untrusted(text.strip())}"
                    ),
                }
            ],
        )
    except Exception as error:  # noqa: BLE001 - a provider failure must degrade, never propagate
        if telemetry is not None:
            # A failed call still cost time, and a failure that is invisible in the cost record
            # is the one that never gets fixed.
            telemetry.latency_ms = int((time.perf_counter() - started) * 1000)
            telemetry.fallback_error = log_provider_failure(error, loop="intent", model=model)
        return fallback, "fallback_error"

    if telemetry is not None:
        telemetry.latency_ms = int((time.perf_counter() - started) * 1000)
        _record_usage(telemetry, getattr(response, "usage", None))

    tool_uses = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
    if not tool_uses:
        return fallback, "fallback_no_proposal"

    payload = tool_uses[0].input
    # Pydantic ignores unknown keys, so a model that answered instead of translating would have
    # its recommendation silently dropped and the rest of its reading accepted. The effect would
    # be safe -- there is nowhere for a recommendation to go -- but a model returning fields
    # outside the schema is a signal worth acting on, not one worth discarding quietly. On the
    # `modern` profile the provider enforces this via `strict`; Bedrock's InvokeModel surface
    # rejects that key entirely, so the check has to exist here too.
    if not isinstance(payload, dict) or set(payload) - _SCHEMA_KEYS:
        return fallback, "fallback_invalid"

    try:
        parsed = ActivityIntent(
            **payload,
            raw_text=text.strip(),
            parsed_by=IntentParser.LLM,
        )
    except (ValidationError, TypeError):
        # The schema is the guardrail here: anything that does not fit the typed request is not a
        # request, and the deterministic reading stands rather than a half-trusted one.
        return fallback, "fallback_invalid"

    if _unasked_today(parsed, text, today):
        parsed = parsed.model_copy(update={"on_date": None})

    return parsed, "agent"
