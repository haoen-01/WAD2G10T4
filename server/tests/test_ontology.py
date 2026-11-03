"""The activity taxonomy: the one place that knows what "walk" means.

`ontology.py` exists because a single free-text `category` column was serving three masters at
once -- the card badge, the learner's content axis and the diversity key -- with no agreed
semantics, so "not for me" on a morning walk taught a dislike of tai chi. The module replaces it
with three closed vocabularies and one alias table.

These tests pin the rules the rest of the codebase is allowed to rely on:

1. The table is ordered longest phrase first. That ordering *is* the semantics -- it is the only
   reason "water exercise" is not read as a generic "exercise".
2. `normalise` never invents `OTHER`; "nothing matched" is `None`.
3. The enum value helpers are generated from the enums, so a member added to `ActivityType`
   reaches the LLM tool schema without anyone editing a hand-typed literal list.
"""

from __future__ import annotations

from datetime import date

import pytest

from silverloop.fixtures import _PROGRAMMES, _Programme, synthetic_activity_candidates
from silverloop.ontology import (
    ALIASES,
    FAMILY_ALIASES,
    FORMAT_LABEL,
    TYPE_FAMILIES,
    WEAK_ALIASES,
    ActivityFamily,
    ActivityType,
    Format,
    activity_type_enum_values,
    normalise,
    search_needle,
)

# ── The vocabularies are closed and complete ───────────────────────────────────────────────────


def test_every_activity_type_has_a_family_mapping() -> None:
    """A type with no entry would silently carry no families, which reads as "nothing is known"
    rather than "nobody filled it in" -- the exact confusion the ontology exists to remove."""
    assert set(TYPE_FAMILIES) == set(ActivityType)


def test_other_asserts_no_family() -> None:
    """`OTHER` means "labelled, and none of the above". Giving it a family would make it match."""
    assert TYPE_FAMILIES[ActivityType.OTHER] == frozenset()


def test_every_format_has_a_display_label() -> None:
    """`category` is populated from this map, so a missing entry is a card with no badge."""
    assert set(FORMAT_LABEL) == set(Format)
    assert all(label.strip() for label in FORMAT_LABEL.values())


def test_every_alias_maps_to_a_real_type_and_never_to_other() -> None:
    assert set(ALIASES.values()) <= set(ActivityType) - {ActivityType.OTHER}
    assert set(WEAK_ALIASES.values()) <= set(ActivityType) - {ActivityType.OTHER}
    assert set(FAMILY_ALIASES.values()) <= set(ActivityFamily)


def test_aliases_are_lower_case_and_stripped() -> None:
    """Every consumer lower-cases its haystack before looking here; an upper-case needle would
    simply never match and would look like a missing word rather than a typo in the table."""
    for phrase in (*ALIASES, *WEAK_ALIASES, *FAMILY_ALIASES):
        assert phrase == phrase.lower().strip(), phrase


# ── Longest phrase first ───────────────────────────────────────────────────────────────────────


def test_the_alias_table_is_ordered_longest_phrase_first() -> None:
    lengths = [len(phrase) for phrase in ALIASES]
    assert lengths == sorted(lengths, reverse=True)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # "exercise" alone is a family word; the longer phrase must win.
        ("Warm Water Exercise", ActivityType.SWIMMING),
        ("Seated Strength Basics", ActivityType.CHAIR_EXERCISE),
        ("Chair Mobility & Balance", ActivityType.CHAIR_EXERCISE),
        # "stretch" (7) beats "garden" (6), which is what stops a garden stretch reading as
        # gardening. Pinned because the fixture catalogue depends on it.
        ("Independent Garden Stretch", ActivityType.STRETCH),
        ("Tai Chi in the Park", ActivityType.TAI_CHI),
    ],
)
def test_a_longer_phrase_beats_a_shorter_one_inside_it(text: str, expected: ActivityType) -> None:
    assert normalise(text) is expected


# ── normalise ──────────────────────────────────────────────────────────────────────────────────


def test_normalise_returns_none_rather_than_other_when_nothing_matches() -> None:
    assert normalise("Bird Watching With Your Grandson") is None


def test_normalise_reads_the_title_before_the_description() -> None:
    """A description names the surroundings far more readily than the activity. Letting it
    outvote the title is how a stretch class held in a garden becomes gardening."""
    assert (
        normalise("Gentle Evening Stretch", "Held in the community garden, among the plants.")
        is ActivityType.STRETCH
    )


def test_normalise_falls_back_to_the_description_when_the_title_names_nothing() -> None:
    assert normalise("Thursdays at the Hub", "A slow walk along covered walkways.") is (
        ActivityType.WALKING
    )


def test_normalise_reads_chinese_runs_with_no_surrounding_spaces() -> None:
    """A Han character has no word boundary against its neighbour, so the Latin anchoring used
    for English needles can never match inside a Chinese phrase."""
    assert normalise("早上想去散步") is ActivityType.WALKING
    assert normalise("晚上唱歌") is ActivityType.KARAOKE


def test_a_weak_alias_only_answers_when_nothing_stronger_did() -> None:
    """A class is a format word wearing a content word's clothes: a cooking class is cooking."""
    assert normalise("Cooking Class") is ActivityType.COOKING
    assert normalise("Tuesday Class") is ActivityType.LEARNING


def test_an_alias_never_matches_inside_a_longer_word() -> None:
    """Anchored at the start of a word: "art" must not be found inside "particular"."""
    assert normalise("A particular kind of afternoon") is None


def test_an_alias_never_matches_as_a_prefix_of_a_longer_word_either() -> None:
    """Red team P2-7. Anchored at the start but not at the end, every short alias was a prefix
    trap: "arthritis" asked for arts and crafts and "Singapore" asked for singing, both with
    nothing reported as misunderstood. Offering an arts and crafts class to someone who
    mentioned their arthritis is a bad failure for this population specifically.
    """
    assert normalise("I have arthritis") is None
    assert normalise("somewhere in Singapore") is None
    assert normalise("I use a walker") is None
    assert normalise("my son is a teacher") is None
    assert normalise("I need a cookie") is None
    assert normalise("I am ready to go out") is None
    assert normalise("swimwear") is None
    assert normalise("poolside") is None
    assert normalise("chessboard") is None
    assert normalise("learner") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Walking Group", ActivityType.WALKING),
        ("Morning Walks", ActivityType.WALKING),
        ("Gentle Stretches", ActivityType.STRETCH),
        ("Community Gardening", ActivityType.GARDENING),
        ("Crafts Afternoon", ActivityType.ARTS_CRAFTS),
        ("Crafting Circle", ActivityType.ARTS_CRAFTS),
        ("Cooking Together", ActivityType.COOKING),
        ("Reading Corner", ActivityType.READING),
        ("Learning Something New", ActivityType.LEARNING),
    ],
)
def test_an_alias_still_matches_its_plural_and_ing_forms(text: str, expected: ActivityType) -> None:
    """The forms the anchor deliberately keeps: "-s", "-es" and "-ing" are spelled out in
    `_NEEDLE_SUFFIXES`, so "walk" still covers "walking" and "walks" without a second entry."""
    assert normalise(text) is expected


# ── search_needle: the primitive both the parser and the catalogue share ────────────────────────


def test_search_needle_reports_where_the_match_started() -> None:
    """The intent parser's negation look-back reads back over the tokens *before* a match, so a
    matcher that could not say where a match began could not support negation at all."""
    match = search_needle("i want to go for a walk", "walk")
    assert match is not None
    assert match.start() == len("i want to go for a ")


def test_search_needle_is_the_same_rule_for_both_callers() -> None:
    assert search_needle("indoors", "indoor") is not None
    assert search_needle("delighted", "light") is None
    # Both ends, not just the start: an open prefix is what made "art" find "arthritis".
    assert search_needle("arthritis", "art") is None
    assert search_needle("arts and crafts", "art") is not None


# ── The tool-schema enum is generated, never typed ─────────────────────────────────────────────


def test_the_tool_enum_is_every_type_except_other() -> None:
    assert activity_type_enum_values() == [
        member.value for member in ActivityType if member is not ActivityType.OTHER
    ]
    assert ActivityType.OTHER.value not in activity_type_enum_values()


def test_the_tool_enum_values_are_the_enum_values_verbatim() -> None:
    """The LLM parser validates its payload through `ActivityIntent`, so a schema value that is
    not an enum value would be advertised to the model and then rejected on arrival."""
    for value in activity_type_enum_values():
        assert ActivityType(value)


# ── The catalogue and the alias table must not drift apart ─────────────────────────────────────
#
# Every fixture listing carries a hand-authored `activity_type`, because product code must never
# infer one from prose. That leaves two independent statements about the same listing -- the hand
# label, and what the alias table makes of the listing's own words -- and nothing but these tests
# stops them diverging once somebody edits a title or adds an alias.


@pytest.mark.parametrize("programme", _PROGRAMMES, ids=lambda programme: programme.slug)
def test_every_fixture_programme_normalises_to_its_hand_labelled_activity_type(
    programme: _Programme,
) -> None:
    assert normalise(programme.title, programme.description) is programme.activity_type


@pytest.mark.parametrize("programme", _PROGRAMMES, ids=lambda programme: programme.slug)
def test_every_fixture_programme_claims_at_least_one_family(programme: _Programme) -> None:
    """An empty family list is indistinguishable from "nobody filled it in", and a listing that
    asserts no family can never be reached by a family-level preference."""
    assert programme.activity_families
    assert set(programme.activity_families) <= set(ActivityFamily)


def test_the_catalogue_badge_is_the_format_label_and_nothing_else() -> None:
    """`category` is a rendering of `format` now, not a field anyone types. Pinned because the
    badge is the only surface where the old free-text column is still visible, and a listing that
    drifted back to hand-typed text would quietly restore the column's second job."""
    candidates = synthetic_activity_candidates(date(2026, 9, 6))
    assert candidates
    for candidate in candidates:
        assert candidate.format is not None
        assert candidate.category == FORMAT_LABEL[candidate.format]


def test_the_fixture_catalogue_never_labels_a_listing_other() -> None:
    """`OTHER` is reserved for a listing that genuinely is none of the sixteen kinds. Every
    fixture is one of them, so using it here would only be hiding a missing enum member."""
    assert all(programme.activity_type is not ActivityType.OTHER for programme in _PROGRAMMES)
