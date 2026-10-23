"""The deterministic stand-in that produced this repository's committed recordings.

THIS IS NOT A MODEL. It is a rule, written down, wearing a model's request/response shape so that
`RecordedClient` in record mode can capture it and the benchmark arm can replay it. Nothing it
produces is evidence about any model's behaviour, and every artifact built from its recordings
says so in its own banner.

What it does, exactly
---------------------
`ScriptedRankingModel` plays the activity-ranking loop in two turns:

1. call `get_activity_options` (the allow-list, exactly as the system prompt instructs);
2. call `propose_activity_order` with an order derived from the returned options by two rules,
   applied in this sequence:

   **A -- variety.** If the first three options do not have three distinct categories, promote
   the highest-ranked option whose category has not been offered yet into the duplicate's slot.
   Repeated until the top three are distinct or no unused category remains.

   **B -- narrowing.** After A, drop any option at position 6 or later whose category already
   appears earlier in the order, but never offer fewer than `MIN_OFFERED`.

   Both rules read only the fields `get_activity_options` actually returns. Rule A fires on the
   cases where the production ranker's own diversity pass left a repeat in the top three; rule B
   fires where the tail repeats a category. Neither fires everywhere, which is the point -- an
   arm where the stand-in always agreed, or always disagreed, would measure nothing.

`ScriptedIntentModel` plays the single-call intent parse: it fills the fields the deterministic
reader would fill, and additionally pushes anything it could not place into `unparsed_terms`.

Synthetic latency and tokens
----------------------------
Both models declare a `latency_ms` and a `usage` on every response, derived deterministically
from the request's own hash and size. They are **synthesised, not measured** -- recording the
microseconds this rule takes would be a worse lie than a declared stand-in value, and a stored
zero would silently disable the latency machinery this arm exists to exercise. Every surface that
prints them marks them SYNTHETIC.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from silverloop.agent.constants import MAX_PROMOTION
from silverloop.agent.tools import (
    PROPOSE_ACTIVITY_ORDER_TOOL_NAME,
)

SCRIPT_VERSION = "scripted-stand-in-v1"

# The model id recorded on every entry. Deliberately not a real model id: a reader who greps the
# recordings must find a name that cannot be mistaken for a provider's.
SCRIPTED_MODEL_ID = "synthetic-scripted-stand-in-v1"

# Rule B's floor. Narrowing below this would start moving the top-3 metrics, and this stand-in is
# not here to manufacture a metric change -- `activity_search` owns what a person is shown.
MIN_OFFERED = 5

# Rule B only considers positions from here on, so it can never touch the top of the list.
NARROWING_FROM_POSITION = 6

_TOP_K = 3


def _block_id(request_text: str) -> str:
    """A tool_use id derived from the request, never from a call counter.

    A counter would give the identical request two different ids depending on how many cases ran
    before it, which makes two recording files disagree about the same key -- `load_recordings`
    refuses to load that, correctly. Deriving it from the request keeps every fixture consistent
    with every other.
    """
    return f"call_{hashlib.sha256(request_text.encode('utf-8')).hexdigest()[:12]}"


def _synthetic_latency_ms(key_material: str) -> int:
    """A stable pseudo-latency in [350, 1750) ms, derived from the request. SYNTHETIC."""
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    return 350 + (int(digest[:6], 16) % 1400)


def _synthetic_usage(request_text: str, output_items: int) -> dict[str, int]:
    """Token counts of the right order of magnitude for this request. SYNTHETIC."""
    return {
        "input_tokens": max(1, len(request_text) // 4),
        "output_tokens": 32 + 6 * max(0, output_items),
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


class _Block:
    """A response content block, shaped like the provider's."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class _Response:
    def __init__(
        self, content: list[Any], *, stop_reason: str, usage: dict[str, int], latency_ms: int
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Block(**usage)
        self.latency_ms = latency_ms


def _request_text(kwargs: dict[str, Any]) -> str:
    """A stable string of the whole request, for the synthetic latency/token derivation."""
    try:
        return json.dumps(kwargs, sort_keys=True, default=repr)
    except (TypeError, ValueError):
        return repr(kwargs)


def _first_user_text(kwargs: dict[str, Any]) -> str:
    messages = kwargs.get("messages") or []
    if not messages:
        return ""
    content = messages[0].get("content") if isinstance(messages[0], dict) else None
    return content if isinstance(content, str) else ""


def _option_payload(kwargs: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The most recent `get_activity_options` payload anywhere in the conversation.

    Searched backwards over every turn, not just the last one: after a guardrail rejection the
    final turn carries the verdict's prose, and a stand-in that only looked there would "forget"
    the allow-list and propose nothing -- an artefact of the stub, not of the loop.
    """
    messages = kwargs.get("messages") or []
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            payload = block.get("content")
            if not isinstance(payload, str):
                continue
            try:
                document = json.loads(payload)
            except (TypeError, ValueError):
                continue
            options = document.get("options") if isinstance(document, dict) else None
            if isinstance(options, list):
                return [option for option in options if isinstance(option, dict)]
    return None


def scripted_order(options: list[dict[str, Any]]) -> list[str]:
    """Rules A and B over the payload `get_activity_options` returned. Pure and deterministic."""
    keys = [str(option.get("activity_key", "")) for option in options]
    categories = {str(option.get("activity_key", "")): option.get("category") for option in options}

    # Rule A -- variety in the top three.
    ordered = list(keys)
    position = 0
    seen: list[Any] = []
    while position < min(_TOP_K, len(ordered)):
        category = categories.get(ordered[position])
        if category not in seen:
            seen.append(category)
            position += 1
            continue
        # A replacement may come only from within `MAX_PROMOTION` places of the slot it would
        # fill: the guardrail rejects any order that lifts a listing further than that above
        # its deterministic rank, and a scripted stand-in that ignored the bound would measure
        # its own rejections rather than the arm.
        replacement = next(
            (
                key
                for key in ordered[position + 1 : position + 1 + MAX_PROMOTION]
                if categories.get(key) not in seen and categories.get(key) is not None
            ),
            None,
        )
        if replacement is None:
            # Nothing left with an unseen category: the repeat stands rather than being dropped.
            seen.append(category)
            position += 1
            continue
        ordered.remove(replacement)
        ordered.insert(position, replacement)
        seen.append(categories.get(replacement))
        position += 1

    # Rule B -- drop tail repeats, never below MIN_OFFERED.
    kept: list[str] = []
    kept_categories: list[Any] = []
    dropped = 0
    for index, key in enumerate(ordered, start=1):
        category = categories.get(key)
        repeats = category is not None and category in kept_categories
        # Hiding an option lifts everything below it by one place, and the guardrail measures
        # promotion on the final position -- so at most `MAX_PROMOTION` drops in total.
        if (
            index >= NARROWING_FROM_POSITION
            and repeats
            and len(kept) >= MIN_OFFERED
            and dropped < MAX_PROMOTION
        ):
            dropped += 1
            continue
        kept.append(key)
        kept_categories.append(category)
    return kept


@dataclass
class ScriptedRankingModel:
    """A `messages.create`-shaped stand-in for the activity-ranking loop.

    `invent_key_once` exists for one adversarial fixture: it makes the first proposal include a
    key that was never permitted, so the recorded fixture exercises the guardrail rejection and
    the model's revision turn. The benchmark recordings never set it -- a stand-in scripted to
    violate would put a fabricated rejection rate into a published table.
    """

    invent_key_once: bool = False
    _invented: bool = field(default=False, init=False)

    @property
    def messages(self) -> ScriptedRankingModel:
        return self

    def create(self, **kwargs: Any) -> Any:
        request_text = _request_text(kwargs)
        latency_ms = _synthetic_latency_ms(request_text)
        options = _option_payload(kwargs)

        if options is None:
            # First turn: ask for the allow-list, exactly as the system prompt instructs.
            return _Response(
                [
                    _Block(
                        type="tool_use",
                        id=_block_id(request_text),
                        name="get_activity_options",
                        input={},
                    )
                ],
                stop_reason="tool_use",
                usage=_synthetic_usage(request_text, 0),
                latency_ms=latency_ms,
            )

        ordered = scripted_order(options)
        if self.invent_key_once and not self._invented:
            self._invented = True
            ordered = ["activity-never-permitted", *ordered]

        return _Response(
            [
                _Block(
                    type="tool_use",
                    id=_block_id(request_text),
                    name=PROPOSE_ACTIVITY_ORDER_TOOL_NAME,
                    input={
                        "ordered_keys": ordered,
                        "reasoning": (
                            "Scripted stand-in: varied the first three categories, then dropped "
                            "tail options repeating a category already offered."
                        ),
                    },
                )
            ],
            stop_reason="tool_use",
            usage=_synthetic_usage(request_text, len(ordered)),
            latency_ms=latency_ms,
        )


@dataclass
class ScriptedIntentModel:
    """A `messages.create`-shaped stand-in for the single-call intent parse.

    `answers` maps the fenced request text (matched by substring, first match wins) to the exact
    `record_intent` arguments to return. A request with no scripted answer returns a fully
    unconstrained reading with the whole request in `unparsed_terms` -- the honest "I could not
    place any of this" answer, and the one the schema is designed to make cheap.
    """

    answers: tuple[tuple[str, dict[str, Any]], ...] = ()

    @property
    def messages(self) -> ScriptedIntentModel:
        return self

    def create(self, **kwargs: Any) -> Any:
        request_text = _request_text(kwargs)
        user_text = _first_user_text(kwargs)
        arguments = self._answer_for(user_text)
        return _Response(
            [
                _Block(
                    type="tool_use",
                    id=_block_id(request_text),
                    name="record_intent",
                    input=arguments,
                )
            ],
            stop_reason="tool_use",
            usage=_synthetic_usage(request_text, len(arguments)),
            latency_ms=_synthetic_latency_ms(request_text),
        )

    def _answer_for(self, user_text: str) -> dict[str, Any]:
        lowered = user_text.lower()
        for marker, arguments in self.answers:
            if marker.lower() in lowered:
                return dict(arguments)
        return {
            "on_date": None,
            "time_window": "any",
            "max_distance_m": None,
            "social_preference": "either",
            "environment": "either",
            "intensity": "either",
            "language": None,
            "unparsed_terms": [],
        }


# ── The review-threshold calibrator (ADR 0008) ────────────────────────────────────────────────

THRESHOLD_READ_TOOLS: tuple[str, ...] = (
    "get_episode_activity",
    "get_context_evidence",
    "get_review_history",
    "get_threshold_history",
    "get_normal_variability",
)

SCRIPTED_CALIBRATE_REASONING = (
    "Scripted stand-in: the coordinator's structured reason was not a concern for this person, so "
    "it proposes waiting one more low day before asking a coordinator, one step within the "
    "allowed range."
)
SCRIPTED_NO_CHANGE_REASONING = (
    "Scripted stand-in: the structured reason does not support a looser setting, so the review "
    "setting stays as it is."
)
SCRIPTED_TIGHTEN_REASONING = (
    "Scripted stand-in: a review reached the coordinator later than it should have, so it "
    "proposes asking one step sooner."
)
SCRIPTED_WRITE_UP = (
    "Scripted stand-in: Care+ went back to the earlier review setting after the change was "
    "checked. The reasoning behind the earlier change is being reviewed."
)

_SETTING_IN_BRIEF = re.compile(r"at least (\d+)% below baseline for at least (\d+) valid-wear days")


def _assistant_turns(kwargs: dict[str, Any]) -> int:
    return sum(
        1
        for message in kwargs.get("messages") or []
        if isinstance(message, dict) and message.get("role") == "assistant"
    )


def _last_submission_refused(kwargs: dict[str, Any]) -> bool:
    messages = kwargs.get("messages") or []
    last = messages[-1] if messages else None
    content = last.get("content") if isinstance(last, dict) else None
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict)
        and block.get("is_error") is True
        and str(block.get("content", "")).startswith("REJECTED")
        for block in content
    )


@dataclass
class ScriptedThresholdModel:
    """A `messages.create`-shaped stand-in for the review-threshold calibrator's three tasks.

    NOT A MODEL. Its rules, exactly:

    1. First turn: call the five read tools.
    2. `submit_write_up` offered (the write-up task): submit `SCRIPTED_WRITE_UP`, citing the revert
       alias the brief names.
    3. The brief says a review "should have reached them sooner" (the tighten task): propose one
       step sooner -- one day fewer above three days, else 5 points lower, never below 30%.
    4. Otherwise (calibrate): with the structured reason `not_a_concern`, propose one more low day
       (or 5 points more at five days); with any other reason, or after the gate refused a
       submission, propose no change.

    Every submission cites the triggering review alias (when the brief names one) and
    `variability`. Latency and tokens are synthesised from the request, as for the other stand-ins.
    """

    @property
    def messages(self) -> ScriptedThresholdModel:
        return self

    def create(self, **kwargs: Any) -> Any:
        request_text = _request_text(kwargs)
        latency_ms = _synthetic_latency_ms(request_text)
        brief = _first_user_text(kwargs)
        names = [
            str(tool.get("name")) for tool in kwargs.get("tools") or [] if isinstance(tool, dict)
        ]
        if _assistant_turns(kwargs) == 0:
            blocks = [
                _Block(
                    type="tool_use",
                    id=_block_id(f"{request_text}#{index}"),
                    name=name,
                    input={},
                )
                for index, name in enumerate(THRESHOLD_READ_TOOLS)
            ]
            return _Response(
                blocks,
                stop_reason="tool_use",
                usage=_synthetic_usage(request_text, 0),
                latency_ms=latency_ms,
            )
        if "submit_write_up" in names:
            revert = re.search(r"The revert (threshold:\d+)", brief)
            return self._one(
                request_text,
                latency_ms,
                "submit_write_up",
                {
                    "text": SCRIPTED_WRITE_UP,
                    "cited_evidence_ids": [revert.group(1)] if revert else ["variability"],
                },
            )
        review = re.search(r"review:\d+", brief)
        cited = [review.group(0), "variability"] if review else ["variability"]
        setting = _SETTING_IN_BRIEF.search(brief)
        severity, persistence = (
            (int(setting.group(1)), int(setting.group(2))) if setting else (40, 3)
        )
        no_change = {
            "cause": "worked_as_intended",
            "proposed_severity_pct": None,
            "proposed_persistence_days": None,
            "reasoning": SCRIPTED_NO_CHANGE_REASONING,
            "cited_evidence_ids": cited,
        }
        if _last_submission_refused(kwargs):
            arguments = no_change
        elif "should have reached them sooner" in brief:
            if persistence > 3:
                change = {
                    "proposed_severity_pct": None,
                    "proposed_persistence_days": persistence - 1,
                }
            elif severity - 5 >= 30:
                change = {"proposed_severity_pct": severity - 5, "proposed_persistence_days": None}
            else:
                change = {"proposed_severity_pct": None, "proposed_persistence_days": None}
            arguments = {
                **no_change,
                **change,
                "reasoning": SCRIPTED_TIGHTEN_REASONING,
            }
        elif "override_reason: not_a_concern." in brief:
            change = (
                {"proposed_severity_pct": None, "proposed_persistence_days": persistence + 1}
                if persistence < 5
                else {"proposed_severity_pct": severity + 5, "proposed_persistence_days": None}
            )
            arguments = {
                **no_change,
                **change,
                "cause": "too_tight_for_person",
                "reasoning": SCRIPTED_CALIBRATE_REASONING,
            }
        else:
            arguments = no_change
        return self._one(request_text, latency_ms, "propose_threshold_change", arguments)

    @staticmethod
    def _one(request_text: str, latency_ms: int, name: str, arguments: dict[str, Any]) -> Any:
        return _Response(
            [_Block(type="tool_use", id=_block_id(request_text), name=name, input=arguments)],
            stop_reason="tool_use",
            usage=_synthetic_usage(request_text, len(arguments)),
            latency_ms=latency_ms,
        )


__all__ = [
    "MIN_OFFERED",
    "NARROWING_FROM_POSITION",
    "SCRIPTED_MODEL_ID",
    "SCRIPT_VERSION",
    "ScriptedIntentModel",
    "ScriptedRankingModel",
    "ScriptedThresholdModel",
    "scripted_order",
]
