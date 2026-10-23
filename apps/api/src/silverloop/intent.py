from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from silverloop.models import (
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    IndoorOutdoor,
    IntentParser,
    SocialPreference,
    TimeWindow,
)
from silverloop.ontology import (
    ACTIVITY_TYPE_LABEL,
    ALIASES,
    WEAK_ALIASES,
    ActivityType,
    search_needle,
)
from silverloop.preferences import NEARBY_RADIUS_M

# Turning a sentence into an `ActivityIntent`, without a model.
#
# This exists because of one line in CLAUDE.md: the full demo must work with SQLite, fixture
# adapters and `LLM_ENABLED=false`. If typing a request only worked when Bedrock was reachable,
# then the single most visible feature in the product would be the first thing to disappear when
# the venue wifi died -- which is precisely the scenario `pnpm demo:offline` exists for.
#
# So there are two parsers and one schema. The planner is better at real sentences and runs when
# it can; this one always runs. Everything downstream consumes `ActivityIntent` and cannot tell
# which produced it.
#
# It is deliberately crude, and its crudeness is made safe by three things rather than by
# cleverness:
#
#   1. Every field defaults to "no preference". A term this parser does not recognise narrows
#      nothing, so the failure mode is showing too much, never silently excluding the one option
#      the person actually wanted.
#   2. Anything it could not place goes into `unparsed_terms`, which the confirmation screen shows
#      back. A misread is corrected by the person *before* anything acts on it.
#   3. A *negated* term never sets the positive value on any axis. Bag-of-needles matching with
#      no sense of scope is how "nothing outdoors today" came back as a hard outdoor-only filter,
#      with a confirmation card that said "Outdoors" and reported nothing misunderstood -- the
#      worst shape a bug in this module can take, because the honesty valve claimed there was
#      nothing to correct.
#
# What it must never do is guess. "Something nice" does not become `intensity=light`.

# No bare "am"/"pm" here. They are clock suffixes, not words for a part of the day, and
# `_TIME_OF_DAY` already reads "9am" / "7 pm" / "9:30 am". Listed as plain needles they matched
# inside ordinary words -- "I am looking for something at night" contains "am", and because
# morning is tested first, asking for a night activity returned "In the morning".
_MORNING = ("morning", "早上")
_AFTERNOON = ("afternoon", "下午")
_EVENING = ("evening", "night", "tonight", "晚上")

_SOCIAL = (
    "social",
    "people",
    "others",
    "friends",
    "group",
    "together",
    "company",
    "meet",
    "befriend",
)
_SOLO = ("alone", "myself", "by my own", "on my own", "quiet", "solo")

_INDOOR = ("indoor", "indoors", "inside", "aircon", "air-con", "air conditioned")
_SHELTERED = ("sheltered", "covered", "out of the rain", "under shelter")
_OUTDOOR = ("outdoor", "outdoors", "outside", "fresh air")

# "Park" names a place, not an environment, and the sentence it most often appears in ("tai chi
# in the park") is about the activity. Read as a hint only when nothing else in the sentence
# named a kind of thing -- otherwise "gardening" became a hard outdoor filter and the content
# was lost, which is C-C5 exactly.
_WEAK_OUTDOOR = ("park",)

# "Seated", "sitting", "chair", "exercise", "active" and "workout" used to live here. They are
# names for *kinds of activity*, not levels of effort, and using them as proxies for an axis the
# schema did not have made "sit down exercise" a request for something energetic -- the opposite
# of what a seated class is. They now live in `ontology.ALIASES` / `FAMILY_ALIASES`.
_LIGHT = ("easy", "gentle", "light", "relaxing", "relaxed", "slow")
_MODERATE = ("brisk", "energetic")

# Ordered longest-first so "not too far" is matched before "far".
_NEARBY = (
    "not too far",
    "too far",
    "close to home",
    "close by",
    "nearby",
    "near me",
    "near",
    "close",
)

# `ActivityIntent.max_distance_m` is bounded at this in the contract. A person typing "within
# 100km" is expressing "distance is not a constraint", and the honest response is to widen the
# search to the widest thing we can represent -- not to reject their sentence. Before this clamp
# the parser raised a ValidationError and the request failed outright.
_MAX_DISTANCE_M = 50_000

_LANGUAGES = {
    "english": "English",
    "mandarin": "Mandarin",
    "chinese": "Mandarin",
    "malay": "Malay",
    "tamil": "Tamil",
    "hokkien": "Hokkien",
    "cantonese": "Cantonese",
}

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_RELATIVE_DAYS = ("today", "tomorrow")
_VAGUE_DAYS = ("this week", "sometime")

# Words that carry no constraint. Left out of `unparsed_terms` so the confirmation screen is not
# padded with "I did not understand: i, want, to, a". The negators are here too: a person who
# says "don't" has been understood perfectly well, and reporting it back as a word we could not
# place would undermine the one screen that makes this parser safe.
_STOPWORD_TEXT = """
    a also an and any anything are around at be because been but can cannot can't cant could
    do does doing
    dislike dont don't for from get hate avoid
    go going good have how i id ill im in is it id like ll me more my never no not nothing
    nowhere of on or out please
    prefer rather really see should show within some something somewhere take tell than
    that the there
    they this to too want was we what when where which who will with without would you your
    """
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())

# A negator anywhere in the three word-tokens before a needle flips it: "no walking",
# "I don't want a group class", "nothing outdoors today". Three is what the probe needs
# ("don't want a group class" puts two words between them) and no more -- widen it and an
# unrelated "no" two clauses back starts excluding things nobody ruled out.
_NEGATORS = frozenset(
    {
        "not",
        "no",
        "nothing",
        "nowhere",
        "never",
        "don't",
        "dont",
        "without",
        "cannot",
        "can't",
        "cant",
        # Aversion verbs rule a thing out as plainly as "no" does. "I hate karaoke" and "avoid
        # tai chi" used to parse as requests *for* karaoke and tai chi, which the confirm card did
        # show back -- but a card that says the opposite of the sentence is the bug, not the fix.
        "avoid",
        "hate",
        "dislike",
    }
)
_NEGATION_LOOKBACK = 3
# Filler the look-back sees through, so that the three tokens it counts are the ones that carry
# meaning. "I don't want to do tai chi" puts "want to do" between the negator and the activity;
# counted as three, they pushed "don't" out of the window and the sentence became a request for
# tai chi. The list is short on purpose: a content word still uses up a slot, so an unrelated
# "no" two clauses back still governs nothing.
_NEGATION_TRANSPARENT = frozenset({"want", "to", "do", "a", "an", "the", "any", "some", "go"})

# Chinese is written without spaces, so a negator sits directly against the phrase it negates and
# there are no tokens to count back over. Measured in characters instead, wide enough for
# 不要/不想/别 plus one intervening character.
_CJK_NEGATORS = ("不要", "不想", "不能", "别")
_CJK_NEGATION_LOOKBACK_CHARS = 4

_DISTANCE_KM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:km|kilometre|kilometer|k)\b")
_DISTANCE_M = re.compile(r"(\d+)\s*(?:m|metre|meter)s?\b")
_TIME_OF_DAY = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b")
# Chinese runs are their own tokens. `[a-z']+` alone silently dropped every CJK word in the
# sentence, so a Mandarin-typing senior was shown "In the morning" with an empty `unparsed_terms`
# -- a card claiming full understanding of a sentence half of which had vanished.
_WORD = re.compile(r"[a-z']+|[一-鿿]+")
_CJK_RUN = re.compile(r"[一-鿿]+")
_LATIN_WORD = re.compile(r"^[a-z']+$")


@dataclass(frozen=True)
class _Match:
    """A needle found in the sentence, and whether the person was ruling it out.

    `start`/`end` are the span in the lowered text, which is what lets two matches on the same
    words be told apart -- "craft" inside an already-matched "art and craft" is not a second
    request.
    """

    needle: str
    negated: bool
    start: int
    end: int


def _is_negated(haystack: str, start: int) -> bool:
    """Whether a negator governs the match beginning at `start`.

    A ≤3-token look-back over a fixed list, not a general parser: every negated phrasing in the
    audit probe ("no walking", "nothing outdoors", "I don't want a group class", "不要散步") is
    covered by it, and anything cleverer would be a dependency and a new class of surprise.
    """
    prefix = haystack[:start]
    recent = [
        token
        for token in _WORD.findall(prefix)
        if _LATIN_WORD.match(token) and token not in _NEGATION_TRANSPARENT
    ]
    if any(token in _NEGATORS for token in recent[-_NEGATION_LOOKBACK:]):
        return True
    tail = prefix[-_CJK_NEGATION_LOOKBACK_CHARS:]
    return any(negator in tail for negator in _CJK_NEGATORS)


def _has_negator(haystack: str) -> bool:
    """Whether the sentence rules anything out at all, anywhere."""
    if any(token in _NEGATORS for token in _WORD.findall(haystack)):
        return True
    return any(negator in haystack for negator in _CJK_NEGATORS)


def _find(haystack: str, needles: tuple[str, ...]) -> _Match | None:
    """First needle that appears at a word boundary, with its negation, or `None`.

    Anchored at the start of a word but deliberately not at the end (see `ontology.search_needle`)
    so "indoor" still matches "indoors" and "walk" matches "walking" -- while "am" can no longer
    match inside "I am" and "light" cannot match inside "delightful". Plain substring matching is
    what turned a request for a night activity into a morning one.
    """
    for needle in needles:
        found = search_needle(haystack, needle)
        if found is not None:
            return _Match(
                needle=needle,
                negated=_is_negated(haystack, found.start()),
                start=found.start(),
                end=found.end(),
            )
    return None


def _parse_date(text: str, today: date) -> tuple[date | None, list[str]]:
    """A single day, when one was named and not ruled out.

    "Not tomorrow" is a real thing to say and it does not mean "tomorrow": the day is left unset,
    and the word is still consumed so the card does not claim to have missed it. There is no
    `excluded_dates` field and none is invented -- "some other day" is not a filter anyone can act
    on with the honesty this module requires.
    """
    if match := _find(text, _RELATIVE_DAYS):
        if match.negated:
            return None, [match.needle]
        ahead = 0 if match.needle == "today" else 1
        return today + timedelta(days=ahead), [match.needle]
    if match := _find(text, _VAGUE_DAYS):
        # A real constraint, but not a single day. Left unset rather than invented.
        return None, [match.needle]
    if match := _find(text, tuple(_WEEKDAYS)):
        if match.negated:
            return None, [match.needle]
        ahead = (_WEEKDAYS[match.needle] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead), [match.needle]
    return None, []


def _clamp_distance(metres: float) -> int:
    return max(0, min(int(metres), _MAX_DISTANCE_M))


def _parse_distance(text: str) -> tuple[int | None, bool, list[str], tuple[int, int] | None]:
    """A distance, and whether the person gave it as a number.

    The flag is the whole point. "Within 800 m" is a limit someone knows they have; "near me" is
    a preference, and reading it as a hard 1 km cut-off removed half the catalogue -- including
    the 1.2 km sheltered walk -- from a person who had asked for nothing of the sort. The phrase
    still yields a figure, because "close by" does mean something and the ranker should use it;
    it simply never filters (`activity_search._too_far`).
    """
    kilometres = _DISTANCE_KM.search(text)
    if kilometres:
        return (
            _clamp_distance(float(kilometres.group(1)) * 1000),
            True,
            [kilometres.group(0)],
            kilometres.span(),
        )
    metres = _DISTANCE_M.search(text)
    if metres:
        return _clamp_distance(float(metres.group(1))), True, [metres.group(0)], metres.span()
    match = _find(text, _NEARBY)
    if match:
        span = (match.start, match.end)
        if match.negated:
            return None, False, [match.needle], span
        return NEARBY_RADIUS_M, False, [match.needle], span
    return None, False, [], None


def _parse_time_window(text: str) -> tuple[TimeWindow, list[str]]:
    clock = _TIME_OF_DAY.search(text)
    if clock:
        hour = int(clock.group(1)) % 12
        if clock.group(3) == "pm":
            hour += 12
        window = (
            TimeWindow.MORNING
            if hour < 12
            else TimeWindow.AFTERNOON
            if hour < 17
            else TimeWindow.EVENING
        )
        return window, [clock.group(0)]
    for window, needles in (
        (TimeWindow.MORNING, _MORNING),
        (TimeWindow.AFTERNOON, _AFTERNOON),
        (TimeWindow.EVENING, _EVENING),
    ):
        match = _find(text, needles)
        if match:
            # "Not in the morning" leaves the window open rather than asserting the morning.
            # There is no `excluded_time_windows` on the contract, so the honest reading is the
            # weaker one: show everything, and say so on the card.
            return (TimeWindow.ANY if match.negated else window), [match.needle]
    return TimeWindow.ANY, []


def _parse_activity_types(
    text: str, *, qualified_by: tuple[int, int] | None
) -> tuple[list[ActivityType], list[ActivityType], list[str], bool]:
    """Every kind of activity the sentence names, split into asked-for and ruled-out, plus
    whether a negated qualifier asked for somewhere closer.

    Walks the alias table longest phrase first and skips any hit overlapping a span already
    taken, so "art and craft" is one request rather than two and "water exercise" is not also
    read as generic exercise.

    A negated activity word is an exclusion **only when the negation was about the activity**.
    "I don't want to walk too far", "I can't walk far", "no long walks" and "I don't walk much"
    are all sentences about a limit, and `_governing_qualifier` is what tells them apart from
    "no walking". Without it every one of the 95 alias needles could be hard-excluded by a bare
    "far" -- an exclusion is a hard filter, it removes the 1.2 km *sheltered* walk this parser
    exists to keep, and the confirmation card then tells the person they asked for that. It is
    the most expensive mistake this module can make.

    Never emits `ActivityType.OTHER`, and never guesses: a word outside the table stays in
    `unparsed_terms` exactly as before, which is the difference between "I have not been taught
    the word mahjong" and "I have decided mahjong means games".
    """
    wanted: list[ActivityType] = []
    excluded: list[ActivityType] = []
    consumed: list[str] = []
    spans: list[tuple[int, int]] = []
    near_requested = False

    for phrase, activity_type in ALIASES.items():
        found = search_needle(text, phrase)
        if found is None:
            continue
        if any(start < found.end() and found.start() < end for start, end in spans):
            continue
        spans.append((found.start(), found.end()))
        consumed.append(phrase)
        if not _is_negated(text, found.start()):
            if activity_type not in wanted:
                wanted.append(activity_type)
            continue
        qualifier = _governing_qualifier(
            text, found.start(), found.end(), qualified_by=qualified_by
        )
        if qualifier is not None:
            consumed.append(qualifier.phrase)
            near_requested = near_requested or qualifier.names_a_distance
            continue
        if activity_type not in excluded:
            excluded.append(activity_type)

    # A format word standing in for a kind of thing, believed only when the sentence named no
    # kind at all: "a cooking class" is cooking, "a class on Tuesday" is learning something.
    #
    # Never believed in a sentence that negates anything, at any distance. "I don't want a group
    # class" is about the *format*, which the intent has no axis for, and the negator is four
    # tokens from "class" -- outside the look-back, so the word would otherwise be read as a
    # positive request to learn something in a sentence that asked for the opposite. Weak
    # evidence in a negated sentence is worth consuming and nothing more.
    if not wanted and not _has_negator(text):
        for phrase, activity_type in WEAK_ALIASES.items():
            if search_needle(text, phrase) is None:
                continue
            consumed.append(phrase)
            wanted.append(activity_type)
            break

    # `max_length=5` on both contract fields. Truncating is honest here in a way that guessing
    # never is: the first five are the ones the person wrote first.
    return wanted[:5], excluded[:5], consumed, near_requested


# How close a qualifier has to sit beside an activity word before it is read as the thing the
# negator was actually about. Wide enough for "walk too far", "walk very far" and "far to walk",
# narrow enough that a distance in a later clause does not reach back over it.
_QUALIFIER_GAP = 8

# Words a negation can be *about*, standing beside the activity rather than in place of it.
#
# Split by what each one names, because only one of the two can be acted on honestly:
#
#   * A negated distance is a request for somewhere closer -- the very reading `_NEARBY` already
#     gives "not too far" -- so a *soft* ceiling is recorded, never a hard one and never a number
#     the person did not say.
#   * A negated effort word is not turned into `LIGHT`. `_MODERATE` deliberately refuses to read
#     "nothing brisk" as a request for something gentle, and "I can't walk fast" is the same
#     complement guess. The word is consumed, the axis is left open, and nothing is excluded.
#
# Every phrase here contains "far" or "long" exactly when it names a distance, which is what
# `_names_a_distance` reads -- including the spans `_parse_distance` produces ("too far",
# "not too far", "2 km"), so both routes into `_governing_qualifier` answer the same question
# the same way.
_DISTANCE_QUALIFIERS: tuple[str, ...] = (
    "too far",
    "that far",
    "so far",
    "very far",
    "far",
    "too long",
    "very long",
    "long way",
    "long",
)
_EFFORT_QUALIFIERS: tuple[str, ...] = (
    "too much",
    "so much",
    "very much",
    "much",
    "a lot",
    "too fast",
    "very fast",
    "fast",
    "too quickly",
    "quickly",
)
# Longest first, so "too far" is reported rather than the "far" inside it.
_QUALIFIERS: tuple[str, ...] = tuple(
    sorted({*_DISTANCE_QUALIFIERS, *_EFFORT_QUALIFIERS}, key=len, reverse=True)
)
_LONGEST_QUALIFIER = max(len(phrase) for phrase in _QUALIFIERS)

# A qualifier reaches over ordinary words but never over the end of a clause: past a comma or a
# joining word it belongs to something else the person said. "Walk, but nothing far" is two
# statements, and the second is not a qualification of the first.
_CLAUSE_BREAK = re.compile(r"[,.;:!?]|\b(?:but|and|or|because|then)\b")


@dataclass(frozen=True)
class _Qualifier:
    """The word a negation turned out to be about, and whether it names a distance."""

    phrase: str
    names_a_distance: bool


def _names_a_distance(phrase: str) -> bool:
    return "far" in phrase or "long" in phrase


def _qualifier_follows(end: int, qualified_by: tuple[int, int] | None) -> bool:
    if qualified_by is None:
        return False
    start, _ = qualified_by
    return end <= start <= end + _QUALIFIER_GAP


def _qualifier_after(text: str, end: int) -> str | None:
    """A qualifier sitting just behind an activity word: "walk far", "walk very much"."""
    window = text[end : end + _QUALIFIER_GAP + _LONGEST_QUALIFIER]
    for phrase in _QUALIFIERS:
        found = re.search(rf"\b{re.escape(phrase)}\b", window)
        if found is None or found.start() > _QUALIFIER_GAP:
            continue
        if _CLAUSE_BREAK.search(window[: found.start()]):
            continue
        return phrase
    return None


def _qualifier_before(text: str, start: int) -> str | None:
    """A qualifier sitting just in front of one: "no long walks", "nothing far to walk"."""
    window = text[max(0, start - _QUALIFIER_GAP - _LONGEST_QUALIFIER) : start]
    for phrase in _QUALIFIERS:
        found = None
        for candidate in re.finditer(rf"\b{re.escape(phrase)}\b", window):
            found = candidate
        if found is None or len(window) - found.end() > _QUALIFIER_GAP:
            continue
        if _CLAUSE_BREAK.search(window[found.end() :]):
            continue
        return phrase
    return None


def _governing_qualifier(
    text: str, start: int, end: int, *, qualified_by: tuple[int, int] | None
) -> _Qualifier | None:
    """What a negated activity word's negation was actually about, when it was not the activity.

    Three shapes, each of them one sentence about a limit rather than about a kind of thing: a
    distance phrase the parser has already read sitting right behind the word ("I don't want to
    walk too far", "no walking over 2 km"), a bare qualifier behind it ("I can't walk far", "I
    don't walk much"), and one in front of it ("no long walks", "nothing far to walk").

    `None` means the negation really was about the activity -- "no walking", "不要散步" -- and
    only then is it an exclusion.
    """
    if _qualifier_follows(end, qualified_by) and qualified_by is not None:
        phrase = text[qualified_by[0] : qualified_by[1]].strip()
        return _Qualifier(phrase=phrase, names_a_distance=_names_a_distance(phrase))
    phrase = _qualifier_after(text, end) or _qualifier_before(text, start)
    if phrase is None:
        return None
    return _Qualifier(phrase=phrase, names_a_distance=_names_a_distance(phrase))


# Every term this module can act on. Used only to decide whether a word belongs in
# `unparsed_terms`, and it matters more than it looks: reporting "I did not understand: indoors"
# on a request that was understood perfectly would train people to distrust the confirmation
# screen, which is the one thing standing between a crude parser and a wrong answer.
_RECOGNISED: frozenset[str] = frozenset(
    word
    for phrase in (
        *_MORNING,
        *_AFTERNOON,
        *_EVENING,
        *_SOCIAL,
        *_SOLO,
        *_INDOOR,
        *_SHELTERED,
        *_OUTDOOR,
        *_WEAK_OUTDOOR,
        *_LIGHT,
        *_MODERATE,
        *_NEARBY,
        *_LANGUAGES,
        *_WEEKDAYS,
        *ALIASES,
        *WEAK_ALIASES,
        *_RELATIVE_DAYS,
        *_VAGUE_DAYS,
    )
    for word in _WORD.findall(phrase)
)

# The Chinese half of `_STOPWORDS`: pronouns, the verbs of wanting and going, and the particles
# that hold a sentence together. Chinese is written without spaces, so these cannot be filtered
# token by token the way the English list is -- they have to be cut out of the run before what is
# left can be reported. Without them "早上想去散步" comes back as "I did not understand 想去",
# which is true of no word the person was actually asking about.
_CJK_STOPWORDS = (
    "可以",
    "我",
    "你",
    "他",
    "她",
    "想",
    "要",
    "去",
    "来",
    "的",
    "了",
    "在",
    "和",
    "有",
    "做",
)

# Everything Han-script this module knows: the needles from the tables above, the negators, and
# the function words. A run is reported only once every one of them has been cut out of it, which
# is what keeps an unknown word visible while 散步 is claimed as understood.
_RECOGNISED_CJK: tuple[str, ...] = tuple(
    sorted(
        {
            *(term for term in _RECOGNISED if _CJK_RUN.fullmatch(term)),
            *_CJK_NEGATORS,
            *_CJK_STOPWORDS,
        },
        key=len,
        reverse=True,
    )
)


def _is_recognised(word: str, consumed: list[str]) -> bool:
    """Whether a word was acted on, or is vocabulary this module knows but did not need.

    Matching is by prefix in both directions so "indoors" is covered by the needle "indoor", and
    a synonym the parser saw but did not pick (it took "people" over "meet") is not reported as a
    failure to understand.
    """
    if any(word in phrase or phrase in word for phrase in consumed):
        return True
    return any(word.startswith(term) or term.startswith(word) for term in _RECOGNISED)


def _unparsed_terms(lowered: str, consumed: list[str]) -> list[str]:
    """Everything the parser could not place, in the order it was written.

    Two passes, because the two scripts need different rules. Latin words are filtered by length
    and by a stopword list. A Han run cannot be: it is written without spaces, so the run has to
    have every phrase the parser knows cut out of it before whatever is left can be reported --
    and no length filter, because a Chinese word is routinely one or two characters and dropping
    those is how 散步 and 唱歌 disappeared from a card that then claimed to have understood
    everything.
    """
    terms = [
        word
        for word in dict.fromkeys(_WORD.findall(lowered))
        if _LATIN_WORD.match(word)
        and len(word) > 2
        and word not in _STOPWORDS
        and not _is_recognised(word, consumed)
    ]

    residue = lowered
    for phrase in sorted({*consumed, *_RECOGNISED_CJK}, key=len, reverse=True):
        if _CJK_RUN.search(phrase):
            residue = residue.replace(phrase, " ")
    terms += [run for run in dict.fromkeys(_CJK_RUN.findall(residue))]
    return terms


def parse_intent(text: str, *, today: date) -> ActivityIntent:
    """Read a typed request into structure, claiming nothing the words did not say."""
    lowered = f" {text.lower().strip()} "
    consumed: list[str] = []

    on_date, matched = _parse_date(lowered, today)
    consumed += matched
    time_window, matched = _parse_time_window(lowered)
    consumed += matched
    max_distance_m, distance_is_explicit, matched, distance_span = _parse_distance(lowered)
    consumed += matched
    activity_types, excluded_activity_types, matched, near_requested = _parse_activity_types(
        lowered, qualified_by=distance_span
    )
    consumed += matched
    if near_requested and max_distance_m is None and not distance_is_explicit:
        # "I can't walk far" names a limit, and it is the same limit `_NEARBY` already reads out
        # of "not too far". Soft, never explicit: no number was offered, so it ranks and never
        # filters (`activity_search._too_far`), and the card says "Somewhere close by" rather
        # than quoting metres back at someone who never gave any.
        max_distance_m = NEARBY_RADIUS_M

    # Every axis below follows the same rule: a negated needle produces an exclusion, never the
    # positive value and never its complement. "Not outdoors" is satisfied by both indoors and
    # sheltered, so inventing either would narrow the search to a place the person never named.
    social = SocialPreference.EITHER
    excluded_social: list[SocialPreference] = []
    for value, needles in ((SocialPreference.SOLO, _SOLO), (SocialPreference.SOCIAL, _SOCIAL)):
        match = _find(lowered, needles)
        if match is None:
            continue
        consumed.append(match.needle)
        if match.negated:
            excluded_social.append(value)
        else:
            social = value
        break

    environment = ActivityEnvironment.EITHER
    excluded_environments: list[IndoorOutdoor] = []
    for value, listed, needles in (
        (ActivityEnvironment.SHELTERED, IndoorOutdoor.SHELTERED, _SHELTERED),
        (ActivityEnvironment.INDOOR, IndoorOutdoor.INDOOR, _INDOOR),
        (ActivityEnvironment.OUTDOOR, IndoorOutdoor.OUTDOOR, _OUTDOOR),
    ):
        match = _find(lowered, needles)
        if match is None:
            continue
        consumed.append(match.needle)
        if match.negated:
            excluded_environments.append(listed)
        else:
            environment = value
        break

    # "In the park" is about where, but only when the sentence did not already say what. Reading
    # a place name as an environment whatever else was said is how "gardening" became a hard
    # outdoor filter with the content thrown away.
    environment_is_open = (
        environment is ActivityEnvironment.EITHER
        and not excluded_environments
        and not activity_types
    )
    if environment_is_open and (match := _find(lowered, _WEAK_OUTDOOR)):
        consumed.append(match.needle)
        if match.negated:
            excluded_environments.append(IndoorOutdoor.OUTDOOR)
        else:
            environment = ActivityEnvironment.OUTDOOR

    intensity = ActivityIntensity.EITHER
    for value, needles in (
        (ActivityIntensity.LIGHT, _LIGHT),
        (ActivityIntensity.MODERATE, _MODERATE),
    ):
        match = _find(lowered, needles)
        if match is None:
            continue
        consumed.append(match.needle)
        # No `excluded_intensity` on the contract, so a negated needle simply leaves the axis
        # open. "Nothing tiring" must not become "something tiring"; turning it into LIGHT would
        # be the complement guess this module refuses to make everywhere else.
        if not match.negated:
            intensity = value
        break

    language: str | None = None
    if match := _find(lowered, tuple(_LANGUAGES)):
        consumed.append(match.needle)
        if not match.negated:
            language = _LANGUAGES[match.needle]

    return ActivityIntent(
        raw_text=text.strip() or None,
        on_date=on_date,
        time_window=time_window,
        max_distance_m=max_distance_m,
        distance_is_explicit=distance_is_explicit,
        social_preference=social,
        environment=environment,
        intensity=intensity,
        language=language,
        activity_types=activity_types,
        excluded_activity_types=excluded_activity_types,
        excluded_environments=excluded_environments,
        excluded_social=excluded_social,
        parsed_by=IntentParser.KEYWORD,
        unparsed_terms=_unparsed_terms(lowered, consumed),
    )


_TIME_WINDOW_WORDS = {
    TimeWindow.MORNING: "in the morning",
    TimeWindow.AFTERNOON: "in the afternoon",
    TimeWindow.EVENING: "in the evening",
}

_SOCIAL_WORDS = {
    SocialPreference.SOCIAL: "With other people",
    SocialPreference.SOLO: "On your own",
}

_NOT_SOCIAL_WORDS = {
    SocialPreference.SOCIAL: "Not with a group",
    SocialPreference.SOLO: "Not on your own",
}

_ENVIRONMENT_WORDS = {
    ActivityEnvironment.INDOOR: "Indoors",
    ActivityEnvironment.OUTDOOR: "Outdoors",
    ActivityEnvironment.SHELTERED: "Somewhere sheltered",
}

_NOT_ENVIRONMENT_WORDS = {
    IndoorOutdoor.INDOOR: "Not indoors",
    IndoorOutdoor.OUTDOOR: "Not outdoors",
    IndoorOutdoor.SHELTERED: "Nothing sheltered",
}

_INTENSITY_WORDS = {
    ActivityIntensity.LIGHT: "Something gentle",
    ActivityIntensity.MODERATE: "Something more active",
}


def describe_intent(intent: ActivityIntent) -> list[str]:
    """The "here is what I understood" lines, in the person's own terms.

    This is the step that makes a crude parser acceptable: whatever was misread is on the screen
    before anything is acted on. It is therefore written for a reader, not as a field dump -- no
    enum values, no metres where a person said "not too far", and no line at all for a field
    nobody constrained.

    An exclusion gets a line of its own ("Not outdoors"). Without one, the safest possible
    reading of a negated sentence -- narrow nothing, exclude one thing -- would be invisible, and
    a person who had been understood perfectly would see no evidence of it.
    """
    lines: list[str] = []

    if intent.on_date is not None:
        lines.append(_long_date(intent.on_date))
    window = _TIME_WINDOW_WORDS.get(intent.time_window)
    if window:
        lines.append(window[0].upper() + window[1:])
    if intent.max_distance_m is not None:
        if not intent.distance_is_explicit:
            # They said "close by", not a number. Quoting one back invents a precision they
            # never offered, and it is not a limit anything actually enforces.
            lines.append("Somewhere close by")
        elif intent.max_distance_m >= 1000:
            lines.append(f"Within about {intent.max_distance_m / 1000:g} km")
        else:
            lines.append(f"Within about {intent.max_distance_m} m")
    if social := _SOCIAL_WORDS.get(intent.social_preference):
        lines.append(social)
    lines += [_NOT_SOCIAL_WORDS[value] for value in intent.excluded_social]
    if environment := _ENVIRONMENT_WORDS.get(intent.environment):
        lines.append(environment)
    lines += [_NOT_ENVIRONMENT_WORDS[value] for value in intent.excluded_environments]
    if intensity := _INTENSITY_WORDS.get(intent.intensity):
        lines.append(intensity)
    lines += [ACTIVITY_TYPE_LABEL[value] for value in intent.activity_types]
    lines += [
        f"Not {ACTIVITY_TYPE_LABEL[value].lower()}" for value in intent.excluded_activity_types
    ]
    if intent.language:
        lines.append(f"In {intent.language}")

    if not lines:
        lines.append("Anything that suits you")
    return lines


def _long_date(value: date) -> str:
    return f"{value.strftime('%A')} {value.day} {value.strftime('%B')}"
