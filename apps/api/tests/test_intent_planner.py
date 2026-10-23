"""The model half of "two parsers, one intent" (F24).

`silverloop.intent.parse_intent` is the deterministic reader that always works, including under
`demo:offline` where `runtime.py` forbids the planner. This module is the better reader, and these
tests pin the property that makes shipping it safe: **every failure path returns the deterministic
parse**, so a person is never worse off than the keyword reading they would have had anyway.

They also pin the boundary. The model translates a request into structure; it never answers one.
`ActivityIntent` has no field that could name an activity, so the schema -- not the prompt -- is
what stops a model recommending something.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from silverloop.agent import constants, plan_intent
from silverloop.agent.intent_planner import _tool_definition
from silverloop.config import Settings
from silverloop.intent import parse_intent
from silverloop.models import (
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    IndoorOutdoor,
    IntentParser,
    SocialPreference,
    TimeWindow,
)
from silverloop.ontology import ActivityType, activity_type_enum_values

TODAY = date(2026, 9, 6)
TEXT = "I am looking for something with other people at night, nothing far"

_WELL_FORMED = {
    "on_date": None,
    "time_window": "evening",
    "max_distance_m": 800,
    "social_preference": "social",
    "environment": "either",
    "intensity": "either",
    "language": None,
    "unparsed_terms": [],
}


def _settings(*, llm_enabled: bool) -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="shared" if llm_enabled else "offline",
        auth_enabled=False,
        llm_enabled=llm_enabled,
    )


def _client_returning(payload: dict[str, object]):
    block = SimpleNamespace(type="tool_use", name="record_intent", input=payload)
    response = SimpleNamespace(content=[block], usage=None, stop_reason="tool_use")
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: response))
    return lambda: (client, None)


def _client_raising():
    def explode(**_: object) -> None:
        raise RuntimeError("network unreachable")

    client = SimpleNamespace(messages=SimpleNamespace(create=explode))
    return lambda: (client, None)


@pytest.fixture
def keyword_intent():
    return parse_intent(TEXT, today=TODAY)


def test_the_planner_being_off_returns_the_deterministic_parse(keyword_intent) -> None:
    """The offline demo must keep typed requests working -- this is why two parsers exist."""
    intent, mode = plan_intent(
        TEXT, today=TODAY, settings=_settings(llm_enabled=False), fallback=keyword_intent
    )
    assert mode == "fallback_disabled"
    assert intent.parsed_by is IntentParser.KEYWORD


def test_a_well_formed_reading_is_used_and_labelled(keyword_intent) -> None:
    intent, mode = plan_intent(
        TEXT,
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=keyword_intent,
        client_factory=_client_returning(_WELL_FORMED),
    )
    assert mode == "agent"
    assert intent.parsed_by is IntentParser.LLM
    assert intent.time_window is TimeWindow.EVENING
    assert intent.max_distance_m == 800


def test_an_unusable_reading_falls_back_rather_than_being_half_trusted(keyword_intent) -> None:
    """The typed schema is the guardrail: a value outside it is not a request, so the
    deterministic reading stands rather than a partially-accepted one."""
    intent, mode = plan_intent(
        TEXT,
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=keyword_intent,
        client_factory=_client_returning(
            {**_WELL_FORMED, "time_window": "whenever", "max_distance_m": -5}
        ),
    )
    assert mode == "fallback_invalid"
    assert intent.parsed_by is IntentParser.KEYWORD


def test_a_provider_failure_degrades_instead_of_propagating(keyword_intent) -> None:
    intent, mode = plan_intent(
        TEXT,
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=keyword_intent,
        client_factory=_client_raising(),
    )
    assert mode == "fallback_error"
    assert intent.parsed_by is IntentParser.KEYWORD


def test_a_turn_with_no_tool_call_falls_back(keyword_intent) -> None:
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Have you tried gardening?")],
        usage=None,
        stop_reason="end_turn",
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: response))
    intent, mode = plan_intent(
        TEXT,
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=keyword_intent,
        client_factory=lambda: (client, None),
    )
    assert mode == "fallback_no_proposal"
    assert intent.parsed_by is IntentParser.KEYWORD


def test_a_blank_llm_model_still_reaches_the_model_with_a_pinned_id(keyword_intent) -> None:
    """`Settings.llm_model` defaults to "" -- a deployment that only sets `LLM_ENABLED=true` must
    not send an empty `model` and get a 400 back, silently degrading to the keyword parser on
    every single request. A blank model must fall back to the provider's pinned default, exactly
    as `agent.planner` already does.
    """
    captured: dict[str, object] = {}

    def capturing_create(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        block = SimpleNamespace(type="tool_use", name="record_intent", input=_WELL_FORMED)
        return SimpleNamespace(content=[block], usage=None, stop_reason="tool_use")

    client = SimpleNamespace(messages=SimpleNamespace(create=capturing_create))
    settings = _settings(llm_enabled=True).model_copy(update={"llm_model": ""})

    intent, mode = plan_intent(
        TEXT,
        today=TODAY,
        settings=settings,
        fallback=keyword_intent,
        client_factory=lambda: (client, None),
    )

    assert mode == "agent"
    assert intent.parsed_by is IntentParser.LLM
    assert captured["model"], "a blank llm_model must still send a non-empty, pinned model id"
    assert captured["model"] == constants.default_model_id(settings.llm_provider)


def test_the_schema_gives_a_recommendation_nowhere_to_go(keyword_intent) -> None:
    """A model that tries to answer rather than translate cannot: extra keys are rejected, so the
    deterministic reading stands. This is the boundary held structurally rather than by prompt."""
    intent, mode = plan_intent(
        TEXT,
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=keyword_intent,
        client_factory=_client_returning(
            {**_WELL_FORMED, "recommended_activity": "Karaoke & Social Hour"}
        ),
    )
    assert mode == "fallback_invalid"
    assert intent.parsed_by is IntentParser.KEYWORD


# ── The tool schema is generated from the enums, never typed out ───────────────────────────────
#
# C-C7: the enum lists in `_tool_definition` were hand-written literals. They happened to match
# the `StrEnum`s at the time, and nothing pinned it -- a member added to `TimeWindow` would have
# reached every other consumer and silently not the model, and a member removed would have been
# advertised to it and then rejected by `ActivityIntent` on arrival.


def _properties() -> dict[str, dict[str, object]]:
    schema = _tool_definition(strict=False)["input_schema"]
    return schema["properties"]


@pytest.mark.parametrize(
    ("field", "enum_cls"),
    [
        ("time_window", TimeWindow),
        ("social_preference", SocialPreference),
        ("environment", ActivityEnvironment),
        ("intensity", ActivityIntensity),
    ],
)
def test_every_scalar_enum_in_the_tool_schema_is_the_enum_itself(
    field: str, enum_cls: type[object]
) -> None:
    assert _properties()[field]["enum"] == [member.value for member in enum_cls]


def test_the_activity_type_enum_comes_from_the_ontology_and_omits_other() -> None:
    """A model that answered `other` would be asserting "some kind of thing, but not one we have
    a word for", which is not a request anyone can act on."""
    for field in ("activity_types", "excluded_activity_types"):
        values = _properties()[field]["items"]["enum"]
        assert values == activity_type_enum_values()
        assert ActivityType.OTHER.value not in values


def test_the_exclusion_enums_omit_the_values_that_could_not_be_excluded() -> None:
    """ "Unknown" is not a setting anyone can rule out, and "either" is not company anyone can."""
    assert (
        IndoorOutdoor.UNKNOWN.value not in _properties()["excluded_environments"]["items"]["enum"]
    )
    assert SocialPreference.EITHER.value not in _properties()["excluded_social"]["items"]["enum"]


def test_every_schema_property_is_a_field_the_contract_actually_has() -> None:
    """The schema is the guardrail: a property with no home on `ActivityIntent` would be
    advertised to the model, filled in, and then silently dropped by Pydantic."""
    assert set(_properties()) <= set(ActivityIntent.model_fields)


def _schema_keys(node: object) -> set[str]:
    if isinstance(node, dict):
        keys = set(node)
        for value in node.values():
            keys |= _schema_keys(value)
        return keys
    if isinstance(node, list):
        return set().union(*(_schema_keys(item) for item in node)) if node else set()
    return set()


@pytest.mark.parametrize("strict", [True, False])
def test_the_tool_schema_uses_no_keyword_strict_tool_use_rejects(strict: bool) -> None:
    """Bedrock rejected the whole request with a 400 for `maxItems`, so every live search fell back
    to the keyword reading without anyone seeing it. The list bounds live on `ActivityIntent`."""
    assert "maxItems" not in _schema_keys(_tool_definition(strict=strict))


def test_the_list_bounds_the_schema_no_longer_states_are_still_enforced() -> None:
    fallback = parse_intent("something to do", today=TODAY)
    too_many = activity_type_enum_values()[:6]
    intent, mode = plan_intent(
        "something to do",
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=fallback,
        client_factory=_client_returning({**_WELL_FORMED, "activity_types": too_many}),
    )
    assert mode == "fallback_invalid"
    assert intent == fallback


def test_every_schema_property_is_required() -> None:
    """`strict` tool use requires it, and a model that may omit a field is a model that can
    quietly leave an exclusion out of a sentence that contained one."""
    schema = _tool_definition(strict=False)["input_schema"]
    assert set(schema["required"]) == set(schema["properties"])


def test_a_model_naming_an_activity_kind_is_accepted_and_one_inventing_a_word_is_not() -> None:
    """The closed enum is the whole boundary: the model may say "they asked for a walk", and
    cannot say anything the ontology has no word for."""
    named = plan_intent(
        "I want to go for a walk",
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=parse_intent("I want to go for a walk", today=TODAY),
        client_factory=_client_returning({**_WELL_FORMED, "activity_types": ["walking"]}),
    )
    assert named[1] == "agent"
    assert named[0].activity_types == [ActivityType.WALKING]

    invented = plan_intent(
        "I want to go abseiling",
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=parse_intent("I want to go abseiling", today=TODAY),
        client_factory=_client_returning({**_WELL_FORMED, "activity_types": ["abseiling"]}),
    )
    assert invented[1] == "fallback_invalid"
    assert invented[0].activity_types == []
    assert invented[0].unparsed_terms == ["abseiling"]


def test_a_negated_request_records_the_exclusion_without_a_positive_value() -> None:
    intent, mode = plan_intent(
        "nothing outdoors today",
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=parse_intent("nothing outdoors today", today=TODAY),
        client_factory=_client_returning(
            {**_WELL_FORMED, "time_window": "any", "excluded_environments": ["outdoor"]}
        ),
    )

    assert mode == "agent"
    assert intent.environment is ActivityEnvironment.EITHER
    assert intent.excluded_environments == [IndoorOutdoor.OUTDOOR]


def test_the_intent_prompt_states_the_same_nearby_radius_the_ranker_uses() -> None:
    """The prompt tells the model what "nearby" means in metres; the ranker's own figure is
    `preferences.NEARBY_RADIUS_M`. The prompt is not edited to import it (that would change every
    recorded request), so this pins the two together instead."""
    from silverloop.agent.intent_planner import SYSTEM_PROMPT
    from silverloop.preferences import NEARBY_RADIUS_M

    assert f"about {NEARBY_RADIUS_M}" in SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("something social in the afternoon", False),
        ("mornings are best for me", False),
        ("something this afternoon", True),
        ("anything today", True),
        ("tonight, somewhere close", True),
    ],
)
def test_a_date_of_today_is_kept_only_when_the_request_names_today(text: str, kept: bool) -> None:
    """A time of day alone is not a day. Pinning it to today hides every other day's listings."""
    intent, mode = plan_intent(
        text,
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=parse_intent(text, today=TODAY),
        client_factory=_client_returning({**_WELL_FORMED, "on_date": TODAY.isoformat()}),
    )
    assert mode == "agent"
    assert intent.on_date == (TODAY if kept else None)


def test_a_named_other_day_is_left_alone() -> None:
    saturday = TODAY + timedelta(days=(5 - TODAY.weekday()) % 7 or 7)
    intent, _ = plan_intent(
        "a walk on Saturday",
        today=TODAY,
        settings=_settings(llm_enabled=True),
        fallback=parse_intent("a walk on Saturday", today=TODAY),
        client_factory=_client_returning({**_WELL_FORMED, "on_date": saturday.isoformat()}),
    )
    assert intent.on_date == saturday
