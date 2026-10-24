from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Final

# The one file that knows what "walk" means.
#
# Before this module existed the catalogue carried a single free-text `category` column
# ("Group class", "Social group", "Drop-in, self-guided") that was doing three unrelated jobs at
# once: a badge on the card, the learner's content axis and the diversity key. Those strings are
# *formats*, not content, so "not for me" on a morning walk taught a dislike of nine unrelated
# programmes -- tai chi, gardening, a pool class -- and the one axis a person actually names
# ("walk", "tai chi", "唱歌") had nowhere to go at all.
#
# Three closed vocabularies replace it:
#
#   `ActivityType`    what the thing *is*, single-valued.
#   `ActivityFamily`  the broad kind it belongs to, multi-label.
#   `Format`          how it is run -- what `category` was actually describing.
#
# and one alias table, `ALIASES`, shared by the keyword intent parser, catalogue normalisation and
# the tests that stop the two drifting apart. The rules are not negotiable per module:
#
#   * The parser never emits `OTHER`. `OTHER` exists for a catalogue row whose normalisation
#     found nothing, and it never matches a request.
#   * A word not in `ALIASES` stays in `ActivityIntent.unparsed_terms`. Unknown stays unknown.
#   * The alias table never enters an LLM prompt. The enum in the tool schema is the constraint,
#     and `activity_type_enum_values()` builds it from the enum at import time so the two cannot
#     disagree.
#   * Fixture listings carry hand-authored values; `normalise` exists to *check* them, never to
#     populate them in product code.


class ActivityType(StrEnum):
    """What a listing actually is, from the person's point of view.

    Single-valued and closed, so a stated preference can be validated and a "not for me" teaches
    something a person would recognise. Members are the canonical set in
    `docs/personalisation-v2-decisions.md` §2.
    """

    WALKING = "walking"
    TAI_CHI = "tai_chi"
    CHAIR_EXERCISE = "chair_exercise"
    STRETCH = "stretch"
    DANCE = "dance"
    SWIMMING = "swimming"
    GARDENING = "gardening"
    ARTS_CRAFTS = "arts_crafts"
    COOKING = "cooking"
    GAMES = "games"
    KARAOKE = "karaoke"
    LEARNING = "learning"
    VOLUNTEERING = "volunteering"
    SOCIAL_MEETUP = "social_meetup"
    MINDFULNESS = "mindfulness"
    READING = "reading"
    # Catalogue-only. The parser never emits it and it never matches an intent: it is how a
    # listing says "labelled, and none of the above", which is a different fact from "unlabelled".
    OTHER = "other"


class ActivityFamily(StrEnum):
    """The broad kind a type belongs to. Multi-label on purpose -- a tai chi session is genuinely
    both movement and mind-body, and forcing a single parent would make one of those a lie."""

    MOVEMENT = "movement"
    MIND_BODY = "mind_body"
    CREATIVE = "creative"
    SOCIAL = "social"
    LEARNING = "learning"
    NATURE = "nature"
    VOLUNTEERING = "volunteering"


class Format(StrEnum):
    """How a listing is run -- the structural job the free-text `category` column was doing badly.

    `category` stays as the display badge and is populated from `FORMAT_LABEL`, so the card still
    reads in words; nothing ranks or learns from it any more.
    """

    GROUP_CLASS = "group_class"
    GROUP_ACTIVITY = "group_activity"
    DROP_IN_GROUP = "drop_in_group"
    SELF_GUIDED = "self_guided"
    ONE_TO_ONE = "one_to_one"


FORMAT_LABEL: Final[dict[Format, str]] = {
    Format.GROUP_CLASS: "Group class",
    Format.GROUP_ACTIVITY: "Group activity",
    Format.DROP_IN_GROUP: "Drop-in group",
    Format.SELF_GUIDED: "Self-guided",
    Format.ONE_TO_ONE: "One to one",
}


# The default families for a type. A listing may hand-author a wider set -- an outdoor walk with a
# group is MOVEMENT *and* NATURE *and* SOCIAL, none of which is true of every walk -- so this is
# the floor, not the whole answer. `OTHER` deliberately has none: it asserts nothing.
TYPE_FAMILIES: Final[dict[ActivityType, frozenset[ActivityFamily]]] = {
    ActivityType.WALKING: frozenset({ActivityFamily.MOVEMENT}),
    ActivityType.TAI_CHI: frozenset({ActivityFamily.MIND_BODY, ActivityFamily.MOVEMENT}),
    ActivityType.CHAIR_EXERCISE: frozenset({ActivityFamily.MOVEMENT}),
    ActivityType.STRETCH: frozenset({ActivityFamily.MOVEMENT, ActivityFamily.MIND_BODY}),
    ActivityType.DANCE: frozenset({ActivityFamily.MOVEMENT, ActivityFamily.SOCIAL}),
    ActivityType.SWIMMING: frozenset({ActivityFamily.MOVEMENT}),
    ActivityType.GARDENING: frozenset({ActivityFamily.NATURE, ActivityFamily.CREATIVE}),
    ActivityType.ARTS_CRAFTS: frozenset({ActivityFamily.CREATIVE}),
    ActivityType.COOKING: frozenset({ActivityFamily.CREATIVE, ActivityFamily.LEARNING}),
    ActivityType.GAMES: frozenset({ActivityFamily.SOCIAL}),
    ActivityType.KARAOKE: frozenset({ActivityFamily.SOCIAL, ActivityFamily.CREATIVE}),
    ActivityType.LEARNING: frozenset({ActivityFamily.LEARNING}),
    ActivityType.VOLUNTEERING: frozenset({ActivityFamily.VOLUNTEERING, ActivityFamily.SOCIAL}),
    ActivityType.SOCIAL_MEETUP: frozenset({ActivityFamily.SOCIAL}),
    ActivityType.MINDFULNESS: frozenset({ActivityFamily.MIND_BODY}),
    ActivityType.READING: frozenset({ActivityFamily.LEARNING}),
    ActivityType.OTHER: frozenset(),
}


# English, Singlish and Chinese phrases for each type. Every entry is a phrase that appears in the
# parser probe (the regression table in `tests/test_intent.py`) or in a fixture listing -- this is a
# working vocabulary, not an attempt at a lexicon, and a word that is not here stays unknown.
#
# Authored grouped by type for readability; `ALIASES` below re-sorts the whole table longest
# phrase first, which is what makes "water exercise" beat "exercise" and "seated strength" beat
# "stretch" regardless of the order anyone types them in here.
_ALIAS_SOURCE: Final[tuple[tuple[ActivityType, tuple[str, ...]], ...]] = (
    (
        ActivityType.WALKING,
        ("walk", "walking", "walks", "stroll", "jalan", "jalan jalan", "散步", "走走"),
    ),
    (
        ActivityType.TAI_CHI,
        ("tai chi", "taichi", "taiji", "qigong", "qi gong", "太极", "气功"),
    ),
    (
        ActivityType.CHAIR_EXERCISE,
        (
            "chair exercise",
            "seated exercise",
            "sit down exercise",
            "sitting exercise",
            "chair mobility",
            "seated strength",
        ),
    ),
    (ActivityType.STRETCH, ("stretch", "stretching", "拉筋")),
    (ActivityType.SWIMMING, ("water exercise", "pool", "aqua", "swim", "swimming", "游泳")),
    (ActivityType.DANCE, ("dance", "dancing", "line dance", "zumba", "跳舞")),
    (ActivityType.GARDENING, ("garden", "gardening", "plants", "种花", "园艺")),
    (
        ActivityType.ARTS_CRAFTS,
        (
            "craft",
            "crafts",
            "art",
            "art and craft",
            "handicraft",
            "beading",
            "sewing",
            "painting",
            "手工",
        ),
    ),
    (ActivityType.COOKING, ("cook", "cooking", "baking", "煮饭", "烹饪")),
    (ActivityType.GAMES, ("games", "mahjong", "chess", "bingo", "cards", "麻将")),
    (ActivityType.KARAOKE, ("sing", "singing", "karaoke", "choir", "唱歌")),
    (ActivityType.READING, ("read", "reading", "books", "library", "newspaper", "看书")),
    (ActivityType.LEARNING, ("learn", "learning", "course", "talk", "workshop", "学")),
    (ActivityType.VOLUNTEERING, ("volunteer", "volunteering", "help out", "义工")),
    (
        ActivityType.SOCIAL_MEETUP,
        ("tea", "chat", "kopi", "makan", "meet up", "kakis", "befriending", "聊天", "喝茶"),
    ),
    (ActivityType.MINDFULNESS, ("meditation", "breathing", "mindfulness", "relaxation", "冥想")),
)


def _longest_first[T](pairs: Iterable[tuple[str, T]]) -> dict[str, T]:
    """Longest phrase first, then alphabetical so the order is stable across interpreters.

    Ordering *is* the semantics here: every consumer walks the table top to bottom and takes the
    first hit, which is the only reason "water exercise" is not read as a generic "exercise" and
    "seated strength" is not read as a stretch.
    """
    return dict(sorted(pairs, key=lambda pair: (-len(pair[0]), pair[0])))


ALIASES: Final[dict[str, ActivityType]] = _longest_first(
    (phrase, activity_type) for activity_type, phrases in _ALIAS_SOURCE for phrase in phrases
)


# Words that name a *family* but no type: "exercise" says movement and nothing more precise.
# Listed here so nothing mistakes them for a type -- they used to sit in the intent parser's
# `_MODERATE` table, which is how "sit down exercise" came back as a request for something
# energetic. Nothing consumes them yet: `ActivityIntent` has no family axis
# (`docs/personalisation-v2-decisions.md` §9), so a bare "exercise" honestly stays in
# `unparsed_terms` rather than being swallowed by a card that then claims to have understood it.
FAMILY_ALIASES: Final[dict[str, ActivityFamily]] = _longest_first(
    (
        ("exercise", ActivityFamily.MOVEMENT),
        ("workout", ActivityFamily.MOVEMENT),
        ("活动", ActivityFamily.MOVEMENT),
    )
)


# Reader-facing names, for the confirmation card and anywhere else a person sees one of these.
# An enum value ("arts_crafts") must never reach a screen, and the phrasing lives next to the
# enum so a new member cannot be added without someone deciding what to call it.
ACTIVITY_TYPE_LABEL: Final[dict[ActivityType, str]] = {
    ActivityType.WALKING: "Walking",
    ActivityType.TAI_CHI: "Tai chi",
    ActivityType.CHAIR_EXERCISE: "Chair exercise",
    ActivityType.STRETCH: "Stretching",
    ActivityType.DANCE: "Dancing",
    ActivityType.SWIMMING: "Swimming",
    ActivityType.GARDENING: "Gardening",
    ActivityType.ARTS_CRAFTS: "Arts and crafts",
    ActivityType.COOKING: "Cooking",
    ActivityType.GAMES: "Games",
    ActivityType.KARAOKE: "Singing",
    ActivityType.LEARNING: "Learning something",
    ActivityType.VOLUNTEERING: "Volunteering",
    ActivityType.SOCIAL_MEETUP: "Meeting people",
    ActivityType.MINDFULNESS: "Something calming",
    ActivityType.READING: "Reading",
    ActivityType.OTHER: "Something else",
}


# Aliases only believed when nothing else in the sentence named a type. "Cooking class" is a
# cooking session, not a course about classes; "a class" on its own is a request to learn
# something. Audit C authored this qualification against `class`; it has no other members yet.
WEAK_ALIASES: Final[dict[str, ActivityType]] = {"class": ActivityType.LEARNING}


_CJK = re.compile(r"[一-鿿]")

# The only endings a needle may pick up. Named and closed, rather than left open: an open prefix
# made every short alias a trap -- "art" found "arthritis", "sing" found "Singapore", "read"
# found "ready", "cook" found "cookie", "walk" found "walker", "tea" found "teacher", "pool"
# found "poolside", "chess" found "chessboard", "learn" found "learner" -- and because
# `activity_types` is soft nothing was filtered out, so the only trace was a confirmation card
# offering arts and crafts to someone who had mentioned arthritis, with nothing listed as
# misunderstood. For this population that particular one is a bad failure.
#
# "-es" earns its place on "stretches"; "-ing" on "walking" and "crafting". Doubled-consonant
# and irregular forms ("swimming", "dancing") are spelled out in `_ALIAS_SOURCE` instead, where
# a reader can see them.
_NEEDLE_SUFFIXES: Final[tuple[str, ...]] = ("es", "ing", "s")
_NEEDLE_SUFFIX_PATTERN: Final[str] = f"(?:{'|'.join(_NEEDLE_SUFFIXES)})?"


def search_needle(haystack: str, needle: str) -> re.Match[str] | None:
    """Find `needle` in `haystack`, anchored the way the intent parser anchors every needle.

    Latin phrases are anchored at **both** ends, with `_NEEDLE_SUFFIXES` allowed in between, so
    "indoor" still matches "indoors" and "walk" matches "walking" while neither "am" inside
    "I am" nor "art" inside "arthritis" matches at all. Chinese runs carry no word boundaries
    (`\\b` between two Han characters does not exist), so they are matched as plain substrings;
    anchoring them the Latin way is exactly the bug that made 散步 vanish from a sentence the
    parser claimed to understand.

    Lives here rather than in `intent.py` because the catalogue normaliser and the parser must
    agree on what "contains a walk" means, and two copies of this rule already drifted once.
    """
    if _CJK.search(needle):
        return re.search(re.escape(needle), haystack)
    return re.search(rf"\b{re.escape(needle)}{_NEEDLE_SUFFIX_PATTERN}\b", haystack)


def activity_type_enum_values() -> list[str]:
    """The `ActivityType` values a request may name, for a tool schema.

    Built from the enum so a member added here reaches the LLM parser without anyone editing a
    hand-typed literal list -- the drift audit C-C7 found in `intent_planner.py`. `OTHER` is
    excluded: it is a catalogue label, and a model that emitted it would be asserting "some kind
    of thing, but not one we have a word for", which is not a request anyone can act on.
    """
    return [member.value for member in ActivityType if member is not ActivityType.OTHER]


def activity_family_enum_values() -> list[str]:
    return [member.value for member in ActivityFamily]


def format_enum_values() -> list[str]:
    return [member.value for member in Format]


def normalise(title: str, description: str | None = None) -> ActivityType | None:
    """The `ActivityType` a listing's own words name, or `None` when they name nothing.

    A **checking** tool, not a writer. Fixture listings hand-author their type precisely so no
    product code has to guess one from prose; `test_ontology.py` then asserts this function
    reproduces every hand label, so the alias table and the catalogue cannot drift apart without
    a test saying so.

    The title is read first and the description only as a fallback: a description mentions the
    surroundings ("a slow loop through the garden") far more readily than it names the activity,
    and letting that outvote the title is how "Independent Garden Stretch" becomes gardening.
    Never returns `OTHER` -- "nothing matched" is `None`, and turning that into a label would
    assert a fact the words do not support.
    """
    for text in (title, description):
        if not text:
            continue
        lowered = text.lower()
        for phrase, activity_type in ALIASES.items():
            if search_needle(lowered, phrase) is not None:
                return activity_type
        for phrase, activity_type in WEAK_ALIASES.items():
            if search_needle(lowered, phrase) is not None:
                return activity_type
    return None
