"""The keyword intent parser: the part of the user-initiated loop that has to run with no model.

`runtime.py` refuses `LLM_ENABLED=true` under the `offline` profile, so `parse_intent` is what
answers a typed request when the planner cannot -- which is also the exact moment (venue wifi
dead, `pnpm demo:offline`) the feature must not silently degrade. Its safety is built on two rules
stated in its own module docstring, and these tests exist to hold the codebase to them:

1. Every field defaults to "no preference". An unrecognised term must narrow nothing.
2. Anything the parser could not place is reported in `unparsed_terms`, and nothing it *did*
   understand may appear there -- a false "I did not understand X" on a correctly parsed request
   would teach a reader to stop trusting the confirmation screen.

`describe_intent` is the other half: what actually gets shown back, in the reader's own words.
"""

from __future__ import annotations

from datetime import date

import pytest

from silverloop.intent import (
    _AFTERNOON,
    _DISTANCE_QUALIFIERS,
    _EFFORT_QUALIFIERS,
    _EVENING,
    _INDOOR,
    _LANGUAGES,
    _LIGHT,
    _MODERATE,
    _MORNING,
    _NEARBY,
    _OUTDOOR,
    _QUALIFIERS,
    _RELATIVE_DAYS,
    _SHELTERED,
    _SOCIAL,
    _SOLO,
    _WEAK_OUTDOOR,
    _WEEKDAYS,
    describe_intent,
    parse_intent,
)
from silverloop.models import (
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    IndoorOutdoor,
    IntentParser,
    SocialPreference,
    TimeWindow,
)
from silverloop.ontology import ALIASES, WEAK_ALIASES, ActivityType

TODAY = date(2026, 9, 6)  # a Sunday


def parse(text: str) -> ActivityIntent:
    return parse_intent(text, today=TODAY)


# ── Every field defaults to "no preference" ─────────────────────────────────────────────────────


def test_an_unrecognised_sentence_narrows_nothing() -> None:
    """The core safety property: a word the parser cannot place must never become a filter."""
    intent = parse("something completely unclassifiable and made up qwzxfoo")

    assert intent.on_date is None
    assert intent.time_window == TimeWindow.ANY
    assert intent.max_distance_m is None
    assert intent.social_preference == SocialPreference.EITHER
    assert intent.environment == ActivityEnvironment.EITHER
    assert intent.intensity == ActivityIntensity.EITHER
    assert intent.language is None


def test_empty_text_also_narrows_nothing_and_is_not_an_error() -> None:
    intent = parse("")
    assert intent == ActivityIntent(
        raw_text=None, parsed_by=IntentParser.KEYWORD, unparsed_terms=[]
    )


def test_must_never_guess_bird_watching_with_grandson() -> None:
    """The example from the parser's own docstring: "something nice" must not become `light`.

    Nothing here is a recognised keyword, so every field must stay at "no preference" and every
    content word must be handed back as something the person should confirm.
    """
    intent = parse("I want to do bird watching with my grandson")

    assert intent.on_date is None
    assert intent.time_window == TimeWindow.ANY
    assert intent.max_distance_m is None
    assert intent.social_preference == SocialPreference.EITHER
    assert intent.environment == ActivityEnvironment.EITHER
    assert intent.intensity == ActivityIntensity.EITHER
    assert intent.language is None
    assert set(intent.unparsed_terms) >= {"bird", "watching", "grandson"}


# ── Specific recognised phrases ─────────────────────────────────────────────────────────────────


def test_not_wanting_to_walk_too_far_yields_a_distance_limit() -> None:
    intent = parse("I don't want to walk too far")
    assert intent.max_distance_m is not None
    assert intent.max_distance_m > 0


def test_tomorrow_morning_yields_the_right_date_and_window() -> None:
    intent = parse("tomorrow morning")
    assert intent.on_date == date(2026, 9, 7)
    assert intent.time_window == TimeWindow.MORNING


def test_today_and_a_named_weekday_are_also_understood() -> None:
    assert parse("today").on_date == TODAY
    # 2026-09-06 is a Sunday; the next Wednesday is three days later.
    assert parse("let's do something on wednesday").on_date == date(2026, 9, 9)


def test_meet_people_yields_social() -> None:
    intent = parse("meet people")
    assert intent.social_preference == SocialPreference.SOCIAL


def test_alone_or_quiet_yields_solo() -> None:
    intent = parse("something quiet, on my own")
    assert intent.social_preference == SocialPreference.SOLO


def test_indoors_yields_indoor_environment() -> None:
    intent = parse("indoors")
    assert intent.environment == ActivityEnvironment.INDOOR


def test_within_800m_and_2km_both_parse() -> None:
    assert parse("within 800m").max_distance_m == 800
    assert parse("something within 2km of home").max_distance_m == 2000


def test_in_mandarin_yields_language() -> None:
    intent = parse("something in Mandarin")
    assert intent.language == "Mandarin"


def test_chinese_is_also_recognised_as_mandarin() -> None:
    """`_LANGUAGES` maps the colloquial term to the same label as the language's own name."""
    assert parse("in Chinese please").language == "Mandarin"


def test_a_clock_time_resolves_to_the_correct_window() -> None:
    assert parse("something at 9am").time_window == TimeWindow.MORNING
    assert parse("something at 2pm").time_window == TimeWindow.AFTERNOON
    assert parse("something at 7pm").time_window == TimeWindow.EVENING


def test_light_and_moderate_intensity_phrases() -> None:
    assert parse("something gentle and relaxing").intensity == ActivityIntensity.LIGHT
    assert parse("a brisk workout").intensity == ActivityIntensity.MODERATE


# ── `unparsed_terms` must not contain words the parser actually understood ─────────────────────


def test_understood_words_never_appear_in_unparsed_terms() -> None:
    """The regression this suite exists to pin.

    "indoors" and "meet" were once reported as not-understood on a request that parsed
    perfectly, because the parser picked a *different* synonym ("people" over "meet", the
    literal substring "indoor" over "indoors") and only checked the phrase it had consumed.
    """
    intent = parse("meet people indoors")

    assert intent.social_preference == SocialPreference.SOCIAL
    assert intent.environment == ActivityEnvironment.INDOOR
    assert "meet" not in intent.unparsed_terms
    assert "indoors" not in intent.unparsed_terms
    assert "people" not in intent.unparsed_terms
    assert intent.unparsed_terms == []


@pytest.mark.parametrize(
    "text",
    [
        "tomorrow morning, meet people, not too far, indoors, gentle, in mandarin",
        "something social and outdoors this afternoon within 1km",
    ],
)
def test_a_fully_understood_sentence_reports_no_unparsed_terms(text: str) -> None:
    intent = parse(text)
    assert intent.unparsed_terms == []


def test_a_partially_understood_sentence_only_reports_the_part_it_missed() -> None:
    """ "Abseiling" is outside the alias table, so it is reported rather than guessed at.

    This used to be phrased with "mahjong", which the taxonomy now knows (see
    `test_a_word_the_alias_table_knows_is_no_longer_reported_as_misunderstood`). The property
    under test is unchanged: an unknown content word reaches the confirmation screen and a
    recognised one does not.
    """
    intent = parse("tomorrow morning, but also some abseiling")
    assert intent.on_date == date(2026, 9, 7)
    assert intent.time_window == TimeWindow.MORNING
    assert "abseiling" in intent.unparsed_terms
    assert "tomorrow" not in intent.unparsed_terms
    assert "morning" not in intent.unparsed_terms


def test_a_word_the_alias_table_knows_is_no_longer_reported_as_misunderstood() -> None:
    """The other half of the same rule. "Mahjong" is in `ontology.ALIASES`, so it now reaches the
    search as a kind of activity instead of being handed back as "I did not understand"."""
    intent = parse("tomorrow morning, but also some mahjong")
    assert intent.activity_types == [ActivityType.GAMES]
    assert intent.unparsed_terms == []


# ── describe_intent: reader-facing, never a field dump ──────────────────────────────────────────


_ALL_ENUM_VALUES = {
    member.value
    for enum_cls in (TimeWindow, SocialPreference, ActivityEnvironment, ActivityIntensity)
    for member in enum_cls
}


def test_describe_intent_never_emits_a_raw_enum_value_or_field_name() -> None:
    intent = parse("tomorrow morning, meet people, not too far, indoors, gentle, in mandarin")
    lines = describe_intent(intent)

    assert lines, "a fully specified intent must still produce reader-facing lines"
    for line in lines:
        assert line not in _ALL_ENUM_VALUES
        # No raw field names such as "time_window" or "max_distance_m" leaking into copy.
        assert "_" not in line


def test_describe_intent_returns_a_non_empty_list_even_for_an_empty_intent() -> None:
    lines = describe_intent(ActivityIntent())
    assert lines
    assert all(isinstance(line, str) and line.strip() for line in lines)


def test_describe_intent_reads_distance_in_the_units_the_person_used() -> None:
    assert "800 m" in describe_intent(parse("within 800m"))[0]
    assert "2 km" in describe_intent(parse("within 2km"))[0]


def test_describe_intent_only_describes_fields_that_were_actually_constrained() -> None:
    """A field left at "no preference" must not generate a line implying it was set."""
    lines = describe_intent(parse("indoors"))
    assert lines == ["Indoors"]


# ── Boundary condition surfaced by exercising the free-text distance parser ─────────────────────


def test_a_very_large_typed_distance_does_not_crash_the_parser() -> None:
    """`ActivityIntent.max_distance_m` is contractually bounded to 50km (`le=50_000`).

    The free-text regex has no such ceiling: it will happily capture "60km" as 60000. This is a
    real, reachable boundary for `POST /v1/activities/search` (the keyword parser is exactly what
    the offline profile falls back to), and a person is not prevented from typing an unreasonable
    distance. `parse_intent` must handle that gracefully -- by clamping, ignoring, or otherwise
    keeping "no preference" as the failure mode -- rather than raising past its own caller.

    If this fails, the defect is in `intent.py`: either the distance parser must cap at the
    model's own bound, or the model's bound needs revisiting, but a `ValidationError` escaping a
    plain parsing function is not the crude-but-safe behaviour the module's docstring promises.
    """
    intent = parse("something within 60km")
    assert intent.max_distance_m is None or intent.max_distance_m <= 50_000


# ── Substring matching, and why it is now anchored ────────────────────────────────────────────


def test_i_am_does_not_turn_a_night_request_into_a_morning_one() -> None:
    """Reported from the running product: asking for something at night answered "in the morning".

    `_MORNING` listed the bare string "am" and matching was plain substring, so the "am" in "I am"
    matched -- and morning is tested before evening. Any sentence containing "I am" became a
    morning request, which is most of the natural ways a person phrases one of these.
    """
    for text in (
        "I am looking for something at night",
        "I am free this evening",
        "I am hoping for something tonight",
    ):
        assert parse_intent(text, today=TODAY).time_window is TimeWindow.EVENING, text


def test_clock_times_still_parse_without_bare_am_and_pm_needles() -> None:
    """Removing "am"/"pm" from the word lists must not cost us real clock times.

    `_TIME_OF_DAY` reads them, and it is the only thing that should: they are suffixes on a
    number, not words for a part of the day.
    """
    assert parse_intent("something at 9:30 am", today=TODAY).time_window is TimeWindow.MORNING
    assert parse_intent("something at 7pm", today=TODAY).time_window is TimeWindow.EVENING


def test_a_needle_never_matches_inside_a_longer_word() -> None:
    """Anchored at the start of a word, so "light" cannot be found inside "delighted"."""
    intent = parse_intent("I am delighted to find something", today=TODAY)
    assert intent.intensity is ActivityIntensity.EITHER


def test_a_needle_still_matches_a_plural_or_inflected_form() -> None:
    """Anchored at the START of a word only -- "indoor" must still match "indoors"."""
    assert parse_intent("something indoors", today=TODAY).environment is ActivityEnvironment.INDOOR


# ── Negation ───────────────────────────────────────────────────────────────────────────────────
#
# The bug this section exists for: `"nothing outdoors today"` was read as `environment=outdoor`
# and then hard-filtered to it, so the person was shown the single outdoor listing and nothing
# else -- with a confirmation card that said "Outdoors" and reported nothing misunderstood. The
# same inversion reached `social_preference` ("I don't want a group class" excluded every
# self-guided listing) and `intensity`.
#
# `test_a_negated_needle_never_yields_the_positive_value` is therefore a property test over every
# needle in every table rather than three hand-written cases: the three that were found by hand
# were not the three that mattered most.

_AXIS_TABLES: list[tuple[str, tuple[str, ...]]] = [
    ("time_window", (*_MORNING, *_AFTERNOON, *_EVENING)),
    ("social_preference", (*_SOCIAL, *_SOLO)),
    ("environment", (*_INDOOR, *_SHELTERED, *_OUTDOOR, *_WEAK_OUTDOOR)),
    ("intensity", (*_LIGHT, *_MODERATE)),
    ("max_distance_m", _NEARBY),
    ("language", tuple(_LANGUAGES)),
    ("on_date", (*_WEEKDAYS, *_RELATIVE_DAYS)),
    ("activity_types", (*ALIASES, *WEAK_ALIASES)),
]

_ALL_NEEDLES: frozenset[str] = frozenset(
    needle for _, needles in _AXIS_TABLES for needle in needles
)

# "Not too far" is its own entry in `_NEARBY` -- an idiom meaning "nearby", not the negation of
# "too far" -- so prefixing "not" to it produces a different phrase rather than a negated one.
# Excluded here by construction rather than by hand, and pinned separately below.
_EVERY_NEEDLE: list[tuple[str, str]] = [
    (axis, needle)
    for axis, needles in _AXIS_TABLES
    for needle in needles
    if f"not {needle}" not in _ALL_NEEDLES
]

_UNCONSTRAINED: dict[str, object] = {
    "time_window": TimeWindow.ANY,
    "social_preference": SocialPreference.EITHER,
    "environment": ActivityEnvironment.EITHER,
    "intensity": ActivityIntensity.EITHER,
    "max_distance_m": None,
    "language": None,
    "on_date": None,
    "activity_types": [],
}


@pytest.mark.parametrize(("axis", "needle"), _EVERY_NEEDLE)
def test_a_negated_needle_never_yields_the_positive_value(axis: str, needle: str) -> None:
    """For every needle in every table: `not <needle>` must leave that axis unconstrained.

    Not "must yield the opposite" -- there is no safe opposite. "Not outdoors" is satisfied by
    both indoors and sheltered, so choosing either would narrow the search to somewhere the
    person never named. The only honest reading of a negation is an exclusion plus an open axis.
    """
    assert getattr(parse(f"not {needle}"), axis) == _UNCONSTRAINED[axis]


@pytest.mark.parametrize(("axis", "needle"), _EVERY_NEEDLE)
def test_a_negated_needle_is_still_consumed(axis: str, needle: str) -> None:
    """A negated word was understood, and saying otherwise is the second half of the original
    bug: a card that reports "I did not understand: outdoors" after correctly excluding outdoor
    listings teaches a reader to distrust the one screen that makes this parser safe."""
    unparsed = parse(f"not {needle}").unparsed_terms
    assert all(term not in needle for term in unparsed), unparsed


def test_not_too_far_is_an_idiom_for_nearby_rather_than_a_negated_distance() -> None:
    """The one phrase the property test above cannot cover, because "not too far" is itself an
    entry in `_NEARBY`. A person who says it is asking for something close, not refusing to name
    a distance -- and they gave no number, so it still never filters."""
    intent = parse("not too far")

    assert intent.max_distance_m == 1000
    assert intent.distance_is_explicit is False


def test_nothing_outdoors_excludes_outdoor_rather_than_requiring_it() -> None:
    intent = parse("nothing outdoors today")

    assert intent.environment is ActivityEnvironment.EITHER
    assert intent.excluded_environments == [IndoorOutdoor.OUTDOOR]
    assert intent.unparsed_terms == []
    assert "Not outdoors" in describe_intent(intent)


def test_i_dont_want_a_group_class_excludes_company_without_requiring_it() -> None:
    """Review N2: the SOLO-before-SOCIAL table order was thought to rescue this case. It did not
    -- the sentence set `social_preference=SOCIAL`, which hard-excluded every self-guided
    listing, i.e. exactly the opposite of what was asked for."""
    intent = parse("I don't want a group class")

    assert intent.social_preference is SocialPreference.EITHER
    assert intent.excluded_social == [SocialPreference.SOCIAL]
    assert "Not with a group" in describe_intent(intent)


def test_no_walking_excludes_the_activity_type() -> None:
    intent = parse("no walking, my knee pain")

    assert intent.activity_types == []
    assert intent.excluded_activity_types == [ActivityType.WALKING]
    assert "Not walking" in describe_intent(intent)


@pytest.mark.parametrize(
    "sentence",
    [
        "I don't want to do tai chi",
        "don't want to do any tai chi",
        "avoid tai chi",
        "I hate tai chi",
        "I dislike tai chi, my knees",
    ],
)
def test_an_aversion_or_a_negator_behind_filler_still_excludes_the_activity(sentence: str) -> None:
    """Re-verification residual 3. "I don't want to do tai chi" parsed as a request *for* tai chi:
    "want to do" used up the three-token look-back, and "avoid"/"hate" were not negators at all.
    The confirm card showed the misreading back, which is the safety net working -- but a card
    that says the opposite of the sentence is the bug, not something to lean on."""
    intent = parse(sentence)

    assert intent.activity_types == []
    assert intent.excluded_activity_types == [ActivityType.TAI_CHI]
    assert "Not tai chi" in describe_intent(intent)
    assert all(term not in {"avoid", "hate", "dislike"} for term in intent.unparsed_terms)


def test_a_negator_several_content_words_back_still_governs_nothing() -> None:
    """The look-back sees through filler, not through meaning. A "no" that opens the sentence and
    then three real words later a request is a request."""
    intent = parse("no rush, but I would enjoy tai chi")

    assert intent.activity_types == [ActivityType.TAI_CHI]
    assert intent.excluded_activity_types == []


def test_a_negated_intensity_leaves_the_axis_open_rather_than_taking_the_complement() -> None:
    """There is no `excluded_intensity` on the contract, so "nothing gentle" cannot be recorded
    as an exclusion -- and it must certainly not be recorded as a request for something brisk."""
    intent = parse("nothing gentle")

    assert intent.intensity is ActivityIntensity.EITHER
    assert intent.unparsed_terms == []


def test_a_distance_qualifier_takes_the_negation_back_from_the_activity() -> None:
    """ "I don't want to walk too far" is a sentence about *far*. Excluding walking would hide
    every walk from someone asking for a short one, and an exclusion is a hard filter."""
    intent = parse("I don't want to walk too far")

    assert intent.excluded_activity_types == []
    assert intent.max_distance_m == 1000
    assert intent.distance_is_explicit is False


_EVERY_ALIAS_AND_QUALIFIER: list[tuple[str, str]] = [
    (needle, qualifier) for needle in ALIASES for qualifier in _QUALIFIERS
]


@pytest.mark.parametrize(("needle", "qualifier"), _EVERY_ALIAS_AND_QUALIFIER)
def test_a_qualifier_beside_a_negated_activity_word_never_becomes_an_exclusion(
    needle: str, qualifier: str
) -> None:
    """Red team P1-2, as a property over all 95 alias needles × every qualifier.

    `_qualifier_follows` only fired when `_parse_distance` had matched, and `_NEARBY` carries
    "too far" but not a bare "far". So "I can't walk far" -- a person describing what their legs
    will do -- hard-excluded walking, and 95 of 95 needles were reachable the same way. A hard
    filter removes every walk in the catalogue, including the 1.2 km *sheltered* one this parser
    exists to keep, and the card then tells the person they asked for that.
    """
    for sentence in (
        f"no need to {needle} {qualifier}",
        f"I can't {needle} {qualifier}",
        f"no {qualifier} {needle}",
    ):
        intent = parse(sentence)
        assert intent.excluded_activity_types == [], sentence
        # Nor the mirror error: a negated word is never the positive request either.
        assert intent.activity_types == [], sentence


@pytest.mark.parametrize("qualifier", _DISTANCE_QUALIFIERS)
def test_a_negated_distance_qualifier_asks_for_somewhere_closer(qualifier: str) -> None:
    """The half that can be honestly acted on. "Not far" is the reading `_NEARBY` already gives
    "not too far", so it records the same soft ceiling -- soft, because no number was offered."""
    intent = parse(f"I can't walk {qualifier}")

    assert intent.max_distance_m == 1000
    assert intent.distance_is_explicit is False
    assert describe_intent(intent) == ["Somewhere close by"]


@pytest.mark.parametrize("qualifier", _EFFORT_QUALIFIERS)
def test_a_negated_effort_qualifier_records_nothing_at_all(qualifier: str) -> None:
    """And the half that cannot. "I can't walk fast" names no axis this contract has: turning it
    into `LIGHT` is the complement guess `_MODERATE` already refuses to make for "nothing
    brisk", and turning it into an exclusion is the bug above. It is consumed and nothing more.
    """
    intent = parse(f"I can't walk {qualifier}")

    assert intent.excluded_activity_types == []
    assert intent.activity_types == []
    assert intent.intensity is ActivityIntensity.EITHER
    assert intent.max_distance_m is None
    assert intent.unparsed_terms == []


def test_a_qualifier_in_a_later_clause_does_not_reach_back_over_the_comma() -> None:
    """The guard is a qualification, not a licence: past a comma or a joining word the qualifier
    belongs to something else the person said, and a real exclusion must survive it."""
    intent = parse("no walking, and nothing far")

    assert intent.excluded_activity_types == [ActivityType.WALKING]


def test_a_chinese_negator_reads_the_same_way() -> None:
    intent = parse("不要散步")

    assert intent.activity_types == []
    assert intent.excluded_activity_types == [ActivityType.WALKING]


# ── Activity content ───────────────────────────────────────────────────────────────────────────


def test_a_walk_parses_to_an_activity_type_and_leaves_unparsed_terms_empty() -> None:
    """22 of the 35 phrasings in the audit probe named a kind of activity and not one of them
    reached the search; "walk" came back as "I did not understand"."""
    intent = parse("a morning sheltered walk")

    assert intent.activity_types == [ActivityType.WALKING]
    assert intent.time_window is TimeWindow.MORNING
    assert intent.environment is ActivityEnvironment.SHELTERED
    assert intent.unparsed_terms == []


def test_an_ordinary_word_is_never_read_as_a_request_hiding_inside_it() -> None:
    """Red team P2-7. `search_needle` anchored a needle at the start of a word and not at the
    end, so every short alias was a prefix trap: "I have arthritis" asked for arts and crafts and
    "somewhere in Singapore" asked for singing. `activity_types` is soft, so nothing was removed
    -- but it carries the heaviest ranking factor and the tier, and the confirmation card, which
    is this parser's stated safety valve, showed the wrong thing.
    """
    for text in (
        "I have arthritis",
        "something for my arthritic knees",
        "somewhere in Singapore",
        "I use a walker",
        "my son is a teacher",
        "I need a cookie",
        "I am ready to go out",
        "the teahouse",
        "swimwear",
        "poolside",
        "chessboard",
        "learner",
    ):
        assert parse(text).activity_types == [], text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a walk", ActivityType.WALKING),
        ("walking", ActivityType.WALKING),
        ("morning walks", ActivityType.WALKING),
        ("stretches", ActivityType.STRETCH),
        ("I like gardening", ActivityType.GARDENING),
        ("crafts", ActivityType.ARTS_CRAFTS),
        ("cooking", ActivityType.COOKING),
        ("I read the newspaper", ActivityType.READING),
        ("singing", ActivityType.KARAOKE),
    ],
)
def test_the_forms_the_anchor_keeps_still_reach_the_search(
    text: str, expected: ActivityType
) -> None:
    """The other half of the same rule: closing the anchor must not cost the plural and "-ing"
    forms people actually type."""
    assert parse(text).activity_types == [expected]


def test_gardening_sets_an_activity_type_and_not_an_environment() -> None:
    """ "Garden" used to sit in `_OUTDOOR`, so asking for gardening became a hard outdoor filter
    and the one thing the person actually named was thrown away."""
    intent = parse("gardening")

    assert intent.activity_types == [ActivityType.GARDENING]
    assert intent.environment is ActivityEnvironment.EITHER


def test_a_seated_class_is_not_read_as_something_energetic() -> None:
    """ "Exercise" sat in `_MODERATE` and "chair"/"seated"/"sitting" in `_LIGHT`, so "sit down
    exercise" came back as a request for something brisk -- the opposite of a seated class."""
    intent = parse("sit down exercise")

    assert intent.activity_types == [ActivityType.CHAIR_EXERCISE]
    assert intent.intensity is ActivityIntensity.EITHER
    assert intent.unparsed_terms == []


def test_a_place_name_is_read_as_an_environment_only_when_nothing_named_a_kind() -> None:
    assert parse("somewhere in the park").environment is ActivityEnvironment.OUTDOOR
    assert parse("tai chi in the park").environment is ActivityEnvironment.EITHER
    assert parse("tai chi in the park").activity_types == [ActivityType.TAI_CHI]


def test_an_unknown_content_word_stays_unknown() -> None:
    """The rule that makes the alias table safe: it never guesses. "Abseiling" is not in the
    table, so it is handed back rather than mapped to the nearest thing."""
    intent = parse("abseiling")

    assert intent.activity_types == []
    assert intent.unparsed_terms == ["abseiling"]


def test_the_parser_never_emits_other() -> None:
    for text in ("something nice", "anything really", "abseiling", "qwzxfoo"):
        intent = parse(text)
        assert ActivityType.OTHER not in intent.activity_types
        assert ActivityType.OTHER not in intent.excluded_activity_types


def test_cjk_content_words_reach_an_activity_type_rather_than_vanishing() -> None:
    """`_WORD` was `[a-z']+`, so every Chinese word in the sentence was dropped before anything
    looked at it -- and dropped from `unparsed_terms` too, so the card claimed to have understood
    a sentence half of which had disappeared."""
    morning_walk = parse("早上 想去 散步")
    assert morning_walk.time_window is TimeWindow.MORNING
    assert morning_walk.activity_types == [ActivityType.WALKING]

    evening_song = parse("晚上 唱歌")
    assert evening_song.time_window is TimeWindow.EVENING
    assert evening_song.activity_types == [ActivityType.KARAOKE]


def test_an_unknown_chinese_word_is_reported_rather_than_dropped() -> None:
    intent = parse("我要打麻将")

    assert intent.activity_types == [ActivityType.GAMES]
    assert intent.unparsed_terms == ["打"]


def test_at_most_five_activity_types_reach_the_contract() -> None:
    """`max_length=5` on the field. Truncating is honest; raising a ValidationError out of a
    plain parsing function is not, and a sentence naming six kinds is a real thing to type."""
    intent = parse("walking, tai chi, gardening, cooking, mahjong, karaoke and reading")

    assert len(intent.activity_types) == 5


# ── A distance phrase is not a distance ────────────────────────────────────────────────────────


def test_only_a_number_marks_the_distance_as_explicit() -> None:
    """ "Near me" is a preference; "within 800 m" is a limit someone knows they have. Only the
    second is a barrier, and only the second filters (`activity_search._too_far`)."""
    phrase = parse("something near me")
    assert phrase.max_distance_m == 1000
    assert phrase.distance_is_explicit is False

    number = parse("within 800m")
    assert number.max_distance_m == 800
    assert number.distance_is_explicit is True


def test_a_vague_distance_is_described_as_one() -> None:
    """Quoting "within about 1 km" back at someone who said "close by" invents a precision they
    never offered, and it is not a limit anything actually enforces."""
    assert describe_intent(parse("something close by")) == ["Somewhere close by"]
    assert describe_intent(parse("within 800m")) == ["Within about 800 m"]


# ── The audit probe, as a regression table ─────────────────────────────────────────────────────
#
# Every phrasing from the parser audit, which ran these 35 sentences through the parser and
# recorded what came back: 22 of them named a kind of activity and not one
# reached the search, two Chinese sentences lost half their words silently, three were read as
# their own opposite, and two content words were misfiled onto other axes.
#
# Pinned here as data rather than prose so the next change to a table, an alias or the negation
# rule has to state what it did to all 35 at once. Only fields that were actually constrained are
# listed; everything absent must still be at "no preference", which the assertion checks.
#
# "no need to walk far" is in here because it used to be recorded as a known limitation: the
# negator governs "far", not "walk", and every one of the 95 alias needles could be hard-excluded
# by a bare "far" behind it. A qualifier beside a negated activity word is now read as the thing
# the negation was about (`intent._governing_qualifier`), so this sentence asks for somewhere
# closer and rules nothing out.

_PROBE: list[tuple[str, dict[str, object], list[str]]] = [
    (
        "a morning sheltered walk",
        {
            "time_window": TimeWindow.MORNING,
            "environment": ActivityEnvironment.SHELTERED,
            "activity_types": [ActivityType.WALKING],
        },
        [],
    ),
    (
        "something social nearby tomorrow morning",
        {
            "on_date": date(2026, 9, 7),
            "time_window": TimeWindow.MORNING,
            "max_distance_m": 1000,
            "social_preference": SocialPreference.SOCIAL,
        },
        [],
    ),
    ("I want to do tai chi", {"activity_types": [ActivityType.TAI_CHI]}, []),
    ("craft", {"activity_types": [ActivityType.ARTS_CRAFTS]}, []),
    (
        "cooking class in Mandarin",
        {"language": "Mandarin", "activity_types": [ActivityType.COOKING]},
        [],
    ),
    ("nothing outdoors today", {"excluded_environments": [IndoorOutdoor.OUTDOOR]}, []),
    ("somewhere quiet by myself", {"social_preference": SocialPreference.SOLO}, []),
    ("not too far, under 1 km", {"max_distance_m": 1000, "distance_is_explicit": True}, []),
    ("sit down exercise", {"activity_types": [ActivityType.CHAIR_EXERCISE]}, []),
    ("gardening", {"activity_types": [ActivityType.GARDENING]}, []),
    ("learn something", {"activity_types": [ActivityType.LEARNING]}, []),
    ("karaoke", {"activity_types": [ActivityType.KARAOKE]}, []),
    ("walk", {"activity_types": [ActivityType.WALKING]}, []),
    (
        "I want to go for a walk this evening",
        {"time_window": TimeWindow.EVENING, "activity_types": [ActivityType.WALKING]},
        [],
    ),
    ("can go swimming or not", {"activity_types": [ActivityType.SWIMMING]}, []),
    ("anything got tai chi in the park", {"activity_types": [ActivityType.TAI_CHI]}, ["got"]),
    ("I dont want group class, want to be alone", {"social_preference": SocialPreference.SOLO}, []),
    (
        "something with my friends after lunch",
        {"social_preference": SocialPreference.SOCIAL},
        ["lunch"],
    ),
    ("singing, in Hokkien", {"language": "Hokkien", "activity_types": [ActivityType.KARAOKE]}, []),
    ("reading corner", {"activity_types": [ActivityType.READING]}, ["corner"]),
    ("no walking, my knee pain", {"excluded_activity_types": [ActivityType.WALKING]}, ["knee"]),
    ("don't want anything tiring", {}, ["tiring"]),
    (
        "chair exercise near my block",
        {"max_distance_m": 1000, "activity_types": [ActivityType.CHAIR_EXERCISE]},
        ["block"],
    ),
    (
        "want to jalan jalan tomorrow",
        {"on_date": date(2026, 9, 7), "activity_types": [ActivityType.WALKING]},
        [],
    ),
    (
        "早上 想去 散步",
        {"time_window": TimeWindow.MORNING, "activity_types": [ActivityType.WALKING]},
        [],
    ),
    (
        "晚上 唱歌",
        {"time_window": TimeWindow.EVENING, "activity_types": [ActivityType.KARAOKE]},
        [],
    ),
    (
        "something in Chinese this afternoon, not far",
        {"time_window": TimeWindow.AFTERNOON, "language": "Mandarin"},
        [],
    ),
    (
        "mahjong with kakis",
        {"activity_types": [ActivityType.GAMES, ActivityType.SOCIAL_MEETUP]},
        [],
    ),
    ("exercise but indoor because raining", {"environment": ActivityEnvironment.INDOOR}, []),
    ("volunteering", {"activity_types": [ActivityType.VOLUNTEERING]}, []),
    (
        "art and craft on Saturday",
        {"on_date": date(2026, 9, 12), "activity_types": [ActivityType.ARTS_CRAFTS]},
        [],
    ),
    (
        "stretching class 3km",
        {
            "max_distance_m": 3000,
            "distance_is_explicit": True,
            "activity_types": [ActivityType.STRETCH],
        },
        [],
    ),
    ("I am free this evening, nothing much", {"time_window": TimeWindow.EVENING}, ["free", "much"]),
    ("not outdoor", {"excluded_environments": [IndoorOutdoor.OUTDOOR]}, []),
    ("no need to walk far", {"max_distance_m": 1000}, ["need"]),
]

_CONSTRAINABLE = (
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
)


@pytest.mark.parametrize(("text", "expected", "unparsed"), _PROBE, ids=[row[0] for row in _PROBE])
def test_the_audit_probe_parses_the_way_it_is_documented_to(
    text: str, expected: dict[str, object], unparsed: list[str]
) -> None:
    intent = parse(text)
    empty = ActivityIntent()

    for field in _CONSTRAINABLE:
        want = expected.get(field, getattr(empty, field))
        assert getattr(intent, field) == want, f"{text!r}: {field}"
    assert intent.unparsed_terms == unparsed, text


def test_the_probe_covers_every_phrasing_the_audit_recorded() -> None:
    """35 sentences in `audit-C.md` §0; a row quietly dropped from the table would make this
    suite weaker without anything failing."""
    assert len(_PROBE) == 35
    assert len({row[0] for row in _PROBE}) == 35
