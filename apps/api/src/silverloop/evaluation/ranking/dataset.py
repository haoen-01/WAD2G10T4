"""The frozen synthetic catalogue, personas and query templates E1 scores against.

Everything in this module is invented for evaluation. Every `ActivityCandidate` is labelled
`source=AAC_FIXTURE, integration_status=FIXTURE` -- the same honesty discipline `fixtures.py`
applies to the product's own demo data -- and no persona here is a real senior: `PersonaBrief` is
a synthetic authoring device, not a record of anyone's stated preferences.

## Information asymmetry, and why it is the whole point

A benchmark that grades a ranker against the same signal it was built from is circular. So the
"ground truth" here (`labels.grade_candidate`) is read from a `PersonaBrief` the ranker never
sees: hard constraints, stated tastes, stated avoids, a mobility radius and a informal narrative.
The ranker instead receives an OBSERVATION TRACE -- a partial, noisy replay of interactions
(`PersonaBrief.trace`, folded through the production `apply_decline`/`apply_enjoyment` and a small
per-listing engagement tally) from which its `ActivityPreferences` and `ActivityEngagement` map
are derived (`traces.py`). The trace is a genuinely imperfect proxy for the brief: a decline
reason maps to exactly one `PreferenceDimension` (see `preferences.DECLINE_REASON_DIMENSIONS`),
so a persona whose true avoid is a *category* teaches the ranker nothing about it if her only
recorded decline against that category was reasoned `TOO_FAR` (which moves DISTANCE, not
CATEGORY) -- exactly the asymmetry a real system lives with, and exactly what stops this benchmark
from grading a ranker against its own inputs.

## The one place the label rule had to be resolved rather than merely followed

The specification for grades 0-1 reads: "1 = constraints satisfied but hits a soft avoid; 0 =
... hits a stated avoid, or is inside the decline cooldown", which names two different kinds of
avoid without defining them separately. This module resolves that by giving every persona two
avoid lists: `soft_avoids` (grade 1 when hit) and `hard_avoids` ("stated", grade 0 when hit) --
the same distinction the product itself draws between an inferred dislike and something a person
said outright (`PreferenceStance.AVOID`). See `labels.py` for the exact lexicographic rule this
produces.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from silverloop.local_time import at_local
from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    ActivityLocation,
    ActivitySource,
    DeclineReason,
    DistanceBasis,
    Enjoyment,
    IndoorOutdoor,
    IntegrationStatus,
    LikedAspect,
    PreferenceDimension,
    SocialPreference,
    TimeWindow,
)
from silverloop.ontology import ActivityType

# Tuesday. Chosen so `on_date=FROZEN_TODAY` in the "Tuesday morning indoors gentle" template lines
# up with the catalogue's own Tuesday-morning listings without any timezone surprise --
# `local_time.at_local` still does the real +08:00 conversion, this only fixes which calendar day
# "Tuesday" refers to for the whole frozen dataset.
FROZEN_TODAY: date = date(2026, 9, 8)
assert FROZEN_TODAY.strftime("%A") == "Tuesday"

RETRIEVED_AT = at_local(FROZEN_TODAY, 0, 0)


def _at(offset_days: int, hour: int, minute: int = 0) -> datetime:
    return at_local(FROZEN_TODAY + timedelta(days=offset_days), hour, minute)


# What each of the twelve programme kinds in this catalogue actually *is*, hand-authored exactly
# like the fixture listings are. The `category` column here was doing the content job by accident
# -- its values ("Tai Chi", "Mahjong") are contents, not the format labels the product's own
# `category` holds -- so it kept working while the product's did not. The type is populated from
# it rather than left null, because a benchmark whose content axis is silently `None` measures a
# ranker that cannot see content, which is not the ranker.
#
# This is a *schema* addition on hand-authored rows, not a change to any relevance grade: no
# `labels.py` entry and no `BRIEF` is touched.
_CATEGORY_TYPES: dict[str, ActivityType] = {
    "Tai Chi": ActivityType.TAI_CHI,
    "Qigong": ActivityType.TAI_CHI,
    "Gardening": ActivityType.GARDENING,
    "Karaoke": ActivityType.KARAOKE,
    "Community Choir": ActivityType.KARAOKE,
    "Board Games": ActivityType.GAMES,
    "Chess Club": ActivityType.GAMES,
    "Mahjong": ActivityType.GAMES,
    "Line Dancing": ActivityType.DANCE,
    "Walking Group": ActivityType.WALKING,
    "Watercolour": ActivityType.ARTS_CRAFTS,
    "Aqua Aerobics": ActivityType.SWIMMING,
}


def _candidate(
    activity_id: str,
    title: str,
    provider: str,
    category: str,
    *,
    offset: int,
    hour: int,
    environment: IndoorOutdoor,
    intensity: ActivityIntensity | None,
    social: SocialPreference | None,
    distance_m: int | None,
    language_tags: list[str],
    availability: ActivityAvailability = ActivityAvailability.AVAILABLE,
) -> ActivityCandidate:
    return ActivityCandidate(
        activity_id=activity_id,
        source=ActivitySource.AAC_FIXTURE,
        integration_status=IntegrationStatus.FIXTURE,
        title=title,
        provider=provider,
        start_at=_at(offset, hour),
        location=ActivityLocation(name=f"{provider} Centre"),
        category=category,
        activity_type=_CATEGORY_TYPES[category],
        indoor_outdoor=environment,
        intensity=intensity,
        social_shape=social,
        language_tags=language_tags,
        capacity=20,
        availability=availability,
        retrieved_at=RETRIEVED_AT,
        distance_m=distance_m,
        distance_basis=DistanceBasis.LISTING_STATIC
        if distance_m is not None
        else DistanceBasis.UNKNOWN,
    )


IN = IndoorOutdoor.INDOOR
OUT = IndoorOutdoor.OUTDOOR
SHELT = IndoorOutdoor.SHELTERED
UNK = IndoorOutdoor.UNKNOWN
LIGHT = ActivityIntensity.LIGHT
MOD = ActivityIntensity.MODERATE
SOCIAL = SocialPreference.SOCIAL
SOLO = SocialPreference.SOLO
FULL = ActivityAvailability.FULL
EN = ["English"]
ZH = ["Mandarin"]
NONE_LANG: list[str] = []

# (id, title, provider, category, offset(0=Tue), hour, environment, intensity, social, distance_m,
#  language_tags, availability)
_ROWS: tuple[tuple, ...] = (
    # -- Tai Chi: mostly outdoor, light, social --------------------------------------------------
    (
        "tai-chi-1",
        "Sunrise Tai Chi",
        "Community Wellness",
        "Tai Chi",
        0,
        8,
        OUT,
        LIGHT,
        SOCIAL,
        300,
        EN,
        None,
    ),
    (
        "tai-chi-2",
        "Sunrise Tai Chi",
        "Community Wellness",
        "Tai Chi",
        1,
        8,
        OUT,
        LIGHT,
        SOCIAL,
        3200,
        EN,
        None,
    ),
    (
        "tai-chi-3",
        "Evening Tai Chi",
        "Community Wellness",
        "Tai Chi",
        3,
        19,
        OUT,
        LIGHT,
        SOLO,
        700,
        EN,
        None,
    ),
    (
        "tai-chi-4",
        "Indoor Tai Chi",
        "Community Wellness",
        "Tai Chi",
        4,
        9,
        IN,
        LIGHT,
        SOCIAL,
        None,
        EN,
        None,
    ),
    (
        "tai-chi-5",
        "Tai Chi (Mandarin)",
        "Community Wellness",
        "Tai Chi",
        0,
        9,
        OUT,
        MOD,
        SOCIAL,
        900,
        ZH,
        None,
    ),
    # -- Gardening: outdoor, light, mostly solo --------------------------------------------------
    (
        "gardening-1",
        "Community Garden Morning",
        "Green Fingers CC",
        "Gardening",
        0,
        9,
        OUT,
        LIGHT,
        SOLO,
        400,
        EN,
        None,
    ),
    (
        "gardening-2",
        "Community Garden Morning",
        "Green Fingers CC",
        "Gardening",
        1,
        9,
        OUT,
        LIGHT,
        SOLO,
        2600,
        EN,
        None,
    ),
    (
        "gardening-3",
        "Herb Bed Workshop",
        "Green Fingers CC",
        "Gardening",
        2,
        15,
        OUT,
        LIGHT,
        SOCIAL,
        1800,
        EN,
        None,
    ),
    (
        "gardening-4",
        "Evening Gardening Club",
        "Green Fingers CC",
        "Gardening",
        5,
        18,
        OUT,
        LIGHT,
        SOLO,
        900,
        EN,
        None,
    ),
    (
        "gardening-5",
        "Rooftop Garden",
        "Green Fingers CC",
        "Gardening",
        0,
        10,
        UNK,
        LIGHT,
        None,
        None,
        EN,
        None,
    ),
    # -- Karaoke: indoor, moderate, social --------------------------------------------------------
    (
        "karaoke-1",
        "Golden Voices Karaoke",
        "Harmony Hall",
        "Karaoke",
        0,
        15,
        IN,
        MOD,
        SOCIAL,
        1200,
        EN,
        None,
    ),
    (
        "karaoke-2",
        "Golden Voices Karaoke",
        "Harmony Hall",
        "Karaoke",
        3,
        19,
        IN,
        MOD,
        SOCIAL,
        1200,
        EN,
        None,
    ),
    (
        "karaoke-3",
        "Karaoke for Beginners",
        "Harmony Hall",
        "Karaoke",
        1,
        10,
        IN,
        LIGHT,
        SOCIAL,
        4200,
        EN,
        None,
    ),
    (
        "karaoke-4",
        "Mandarin Karaoke Night",
        "Harmony Hall",
        "Karaoke",
        4,
        19,
        IN,
        MOD,
        SOCIAL,
        2000,
        ZH,
        None,
    ),
    (
        "karaoke-5",
        "Karaoke (Fully Booked)",
        "Harmony Hall",
        "Karaoke",
        0,
        15,
        IN,
        MOD,
        SOCIAL,
        500,
        EN,
        FULL,
    ),
    # -- Board Games: indoor, light, mixed social -------------------------------------------------
    (
        "boardgames-1",
        "Tuesday Board Games",
        "Neighbourhood Club",
        "Board Games",
        0,
        10,
        IN,
        LIGHT,
        SOCIAL,
        600,
        EN,
        None,
    ),
    (
        "boardgames-2",
        "Solo Puzzle Corner",
        "Neighbourhood Club",
        "Board Games",
        0,
        9,
        IN,
        LIGHT,
        SOLO,
        600,
        EN,
        None,
    ),
    (
        "boardgames-3",
        "Weekend Board Games",
        "Neighbourhood Club",
        "Board Games",
        4,
        14,
        IN,
        LIGHT,
        SOCIAL,
        3400,
        EN,
        None,
    ),
    (
        "boardgames-4",
        "Board Games (unlisted setting)",
        "Neighbourhood Club",
        "Board Games",
        2,
        10,
        UNK,
        LIGHT,
        None,
        800,
        EN,
        None,
    ),
    (
        "boardgames-5",
        "Evening Board Games",
        "Neighbourhood Club",
        "Board Games",
        5,
        19,
        IN,
        LIGHT,
        SOLO,
        1500,
        EN,
        None,
    ),
    # -- Line Dancing: a SERIES -- one provider/title, three sessions ----------------------------
    (
        "linedance-1",
        "Line Dancing Circle",
        "Golden Steps CC",
        "Line Dancing",
        0,
        9,
        IN,
        MOD,
        SOCIAL,
        500,
        EN,
        None,
    ),
    (
        "linedance-2",
        "Line Dancing Circle",
        "Golden Steps CC",
        "Line Dancing",
        1,
        9,
        IN,
        MOD,
        SOCIAL,
        500,
        EN,
        None,
    ),
    (
        "linedance-3",
        "Line Dancing Circle",
        "Golden Steps CC",
        "Line Dancing",
        2,
        9,
        IN,
        MOD,
        SOCIAL,
        500,
        EN,
        None,
    ),
    (
        "linedance-4",
        "Line Dancing (Evening)",
        "Golden Steps CC",
        "Line Dancing",
        3,
        18,
        IN,
        MOD,
        SOCIAL,
        3300,
        EN,
        None,
    ),
    (
        "linedance-5",
        "Line Dancing (Far)",
        "Golden Steps CC",
        "Line Dancing",
        0,
        9,
        IN,
        MOD,
        SOCIAL,
        6200,
        EN,
        None,
    ),
    # -- Chess Club: indoor, light, mixed, some UNKNOWN social -----------------------------------
    (
        "chess-1",
        "Chess Club Morning",
        "Thinkers CC",
        "Chess Club",
        0,
        9,
        IN,
        LIGHT,
        None,
        700,
        EN,
        None,
    ),
    (
        "chess-2",
        "Chess Club Afternoon",
        "Thinkers CC",
        "Chess Club",
        1,
        14,
        IN,
        LIGHT,
        SOLO,
        700,
        EN,
        None,
    ),
    (
        "chess-3",
        "Chess Tournament",
        "Thinkers CC",
        "Chess Club",
        4,
        10,
        IN,
        MOD,
        SOCIAL,
        2900,
        EN,
        None,
    ),
    (
        "chess-4",
        "Chess Club (unlisted setting)",
        "Thinkers CC",
        "Chess Club",
        0,
        9,
        UNK,
        None,
        None,
        None,
        NONE_LANG,
        None,
    ),
    (
        "chess-5",
        "Evening Chess",
        "Thinkers CC",
        "Chess Club",
        5,
        19,
        IN,
        LIGHT,
        SOLO,
        1100,
        EN,
        None,
    ),
    # -- Community Choir: indoor, moderate, social -----------------------------------------------
    (
        "choir-1",
        "Community Choir Rehearsal",
        "Voices Together",
        "Community Choir",
        0,
        10,
        IN,
        MOD,
        SOCIAL,
        1600,
        EN,
        None,
    ),
    (
        "choir-2",
        "Community Choir Rehearsal",
        "Voices Together",
        "Community Choir",
        1,
        10,
        IN,
        MOD,
        SOCIAL,
        1600,
        EN,
        None,
    ),
    (
        "choir-3",
        "Choir for Beginners",
        "Voices Together",
        "Community Choir",
        0,
        15,
        IN,
        LIGHT,
        SOCIAL,
        400,
        EN,
        None,
    ),
    (
        "choir-4",
        "Evening Choir",
        "Voices Together",
        "Community Choir",
        3,
        19,
        IN,
        MOD,
        SOCIAL,
        2400,
        EN,
        None,
    ),
    (
        "choir-5",
        "Mandarin Choir",
        "Voices Together",
        "Community Choir",
        4,
        10,
        IN,
        MOD,
        SOCIAL,
        900,
        ZH,
        None,
    ),
    # -- Walking Group: outdoor, light, social ---------------------------------------------------
    (
        "walking-1",
        "Morning Walking Group",
        "Parkside Seniors",
        "Walking Group",
        0,
        8,
        OUT,
        LIGHT,
        SOCIAL,
        350,
        EN,
        None,
    ),
    (
        "walking-2",
        "Morning Walking Group",
        "Parkside Seniors",
        "Walking Group",
        1,
        8,
        OUT,
        LIGHT,
        SOCIAL,
        350,
        EN,
        None,
    ),
    (
        "walking-3",
        "Evening Walking Group",
        "Parkside Seniors",
        "Walking Group",
        0,
        18,
        OUT,
        LIGHT,
        SOCIAL,
        500,
        EN,
        None,
    ),
    (
        "walking-4",
        "Solo Reflective Walk",
        "Parkside Seniors",
        "Walking Group",
        5,
        19,
        OUT,
        LIGHT,
        SOLO,
        800,
        EN,
        None,
    ),
    (
        "walking-5",
        "Walking Group (Fully Booked)",
        "Parkside Seniors",
        "Walking Group",
        0,
        8,
        OUT,
        LIGHT,
        SOCIAL,
        300,
        EN,
        FULL,
    ),
    # -- Watercolour Class: sheltered, light, solo -----------------------------------------------
    (
        "watercolour-1",
        "Watercolour Basics",
        "Studio Bloom",
        "Watercolour",
        0,
        10,
        SHELT,
        LIGHT,
        SOLO,
        1300,
        EN,
        None,
    ),
    (
        "watercolour-2",
        "Watercolour Basics",
        "Studio Bloom",
        "Watercolour",
        1,
        10,
        SHELT,
        LIGHT,
        SOLO,
        1300,
        EN,
        None,
    ),
    (
        "watercolour-3",
        "Evening Watercolour",
        "Studio Bloom",
        "Watercolour",
        3,
        19,
        SHELT,
        LIGHT,
        SOLO,
        4100,
        EN,
        None,
    ),
    (
        "watercolour-4",
        "Watercolour Social",
        "Studio Bloom",
        "Watercolour",
        0,
        15,
        SHELT,
        LIGHT,
        SOCIAL,
        1300,
        EN,
        None,
    ),
    (
        "watercolour-5",
        "Watercolour (unlisted distance)",
        "Studio Bloom",
        "Watercolour",
        2,
        10,
        SHELT,
        LIGHT,
        SOLO,
        None,
        EN,
        None,
    ),
    # -- Mahjong Afternoon: indoor, light, social -------------------------------------------------
    (
        "mahjong-1",
        "Mahjong Afternoon",
        "Silver Years Club",
        "Mahjong",
        0,
        14,
        IN,
        LIGHT,
        SOCIAL,
        600,
        ZH,
        None,
    ),
    (
        "mahjong-2",
        "Mahjong Afternoon",
        "Silver Years Club",
        "Mahjong",
        1,
        14,
        IN,
        LIGHT,
        SOCIAL,
        600,
        ZH,
        None,
    ),
    (
        "mahjong-3",
        "Mahjong (English-friendly)",
        "Silver Years Club",
        "Mahjong",
        4,
        14,
        IN,
        LIGHT,
        SOCIAL,
        2800,
        EN,
        None,
    ),
    (
        "mahjong-4",
        "Mahjong Evening",
        "Silver Years Club",
        "Mahjong",
        5,
        19,
        IN,
        LIGHT,
        SOCIAL,
        1900,
        ZH,
        None,
    ),
    (
        "mahjong-5",
        "Mahjong (unlisted language)",
        "Silver Years Club",
        "Mahjong",
        0,
        14,
        IN,
        LIGHT,
        SOCIAL,
        700,
        NONE_LANG,
        None,
    ),
    # -- Aqua Aerobics: indoor pool, moderate, social, further out -------------------------------
    (
        "aqua-1",
        "Aqua Aerobics",
        "Splash Seniors",
        "Aqua Aerobics",
        0,
        9,
        IN,
        MOD,
        SOCIAL,
        3900,
        EN,
        None,
    ),
    (
        "aqua-2",
        "Aqua Aerobics",
        "Splash Seniors",
        "Aqua Aerobics",
        1,
        9,
        IN,
        MOD,
        SOCIAL,
        3900,
        EN,
        None,
    ),
    (
        "aqua-3",
        "Gentle Aqua Class",
        "Splash Seniors",
        "Aqua Aerobics",
        4,
        10,
        IN,
        LIGHT,
        SOCIAL,
        4400,
        EN,
        None,
    ),
    (
        "aqua-4",
        "Evening Aqua Aerobics",
        "Splash Seniors",
        "Aqua Aerobics",
        3,
        19,
        IN,
        MOD,
        SOCIAL,
        6100,
        EN,
        None,
    ),
    (
        "aqua-5",
        "Aqua Aerobics (unlisted intensity)",
        "Splash Seniors",
        "Aqua Aerobics",
        0,
        9,
        IN,
        None,
        SOCIAL,
        3900,
        EN,
        None,
    ),
    # -- Qigong: sheltered/outdoor, light, solo, evening-friendly --------------------------------
    (
        "qigong-1",
        "Evening Qigong",
        "Quiet Garden",
        "Qigong",
        0,
        19,
        SHELT,
        LIGHT,
        SOLO,
        600,
        EN,
        None,
    ),
    (
        "qigong-2",
        "Evening Qigong",
        "Quiet Garden",
        "Qigong",
        1,
        19,
        SHELT,
        LIGHT,
        SOLO,
        600,
        EN,
        None,
    ),
    ("qigong-3", "Morning Qigong", "Quiet Garden", "Qigong", 0, 8, OUT, LIGHT, SOLO, 400, EN, None),
    (
        "qigong-4",
        "Social Qigong",
        "Quiet Garden",
        "Qigong",
        4,
        19,
        SHELT,
        LIGHT,
        SOCIAL,
        2200,
        EN,
        None,
    ),
    (
        "qigong-5",
        "Qigong (unlisted setting)",
        "Quiet Garden",
        "Qigong",
        5,
        19,
        UNK,
        LIGHT,
        SOLO,
        900,
        EN,
        None,
    ),
)


def _build_catalogue() -> tuple[ActivityCandidate, ...]:
    candidates = []
    for row in _ROWS:
        (
            activity_id,
            title,
            provider,
            category,
            offset,
            hour,
            environment,
            intensity,
            social,
            distance_m,
            language_tags,
            availability,
        ) = row
        candidates.append(
            _candidate(
                activity_id,
                title,
                provider,
                category,
                offset=offset,
                hour=hour,
                environment=environment,
                intensity=intensity,
                social=social,
                distance_m=distance_m,
                language_tags=list(language_tags),
                availability=availability or ActivityAvailability.AVAILABLE,
            )
        )
    return tuple(candidates)


CATALOGUE: tuple[ActivityCandidate, ...] = _build_catalogue()
CATALOGUE_BY_ID: dict[str, ActivityCandidate] = {c.activity_id: c for c in CATALOGUE}

assert len(CATALOGUE) == len(_ROWS) == 60, "the frozen catalogue drifted from its own row count"
assert len(CATALOGUE_BY_ID) == len(CATALOGUE), "duplicate activity_id in the frozen catalogue"


# ── Personas ─────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeclineEvent:
    activity_id: str
    reason: DeclineReason
    day: date


@dataclass(frozen=True)
class EnjoymentEvent:
    activity_id: str
    enjoyment: Enjoyment
    liked: tuple[LikedAspect, ...]
    day: date


@dataclass(frozen=True)
class InterestEvent:
    """An "I'm interested" tap with no follow-through yet -- real engagement evidence
    (`ActivityEngagement.interested`), but too weak on its own to move any dimension preference,
    the same discipline `apply_decline`/`apply_enjoyment` apply to a bare reasonless tap.
    """

    activity_id: str
    day: date


@dataclass(frozen=True)
class StatedPreferenceEvent:
    """A preference the persona stated in her own words -- the one trace event that reaches the
    ranker as `source="senior_statement"`, full-strength and `confirmed=True`, mirroring
    `PUT .../activity-preferences/{dimension}/{value}`.
    """

    dimension: PreferenceDimension
    value: str
    strength: float
    stated_text: str


TraceEvent = DeclineEvent | EnjoymentEvent | InterestEvent | StatedPreferenceEvent


@dataclass(frozen=True)
class PersonaBrief:
    """The information-asymmetry seam (see module docstring). `stated_tastes`/`soft_avoids`/
    `hard_avoids` and `trace` are BOTH read from this one object, but by two different callers for
    two different purposes: `labels.grade_candidate` reads the tastes/avoids (never the trace) to
    assign ground truth; `traces.build_preferences`/`build_engagement` read only the trace (never
    the tastes/avoids) to build what the ranker actually sees.
    """

    person_id: str
    display_name: str
    mobility_radius_m: int
    tight_mobility_radius_m: int
    preferred_language: str
    stated_tastes: tuple[tuple[PreferenceDimension, str], ...]
    soft_avoids: tuple[tuple[PreferenceDimension, str], ...]
    hard_avoids: tuple[tuple[PreferenceDimension, str], ...]
    trace: tuple[TraceEvent, ...] = field(default_factory=tuple)
    notes: str = ""


def _d(days_ago: int) -> date:
    return FROZEN_TODAY - timedelta(days=days_ago)


CORE_PERSONAS: tuple[PersonaBrief, ...] = (
    PersonaBrief(
        person_id="eval-mdm-tan",
        display_name="Mdm Tan (synthetic)",
        mobility_radius_m=1500,
        tight_mobility_radius_m=800,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Gardening"),),
        soft_avoids=((PreferenceDimension.ENVIRONMENT, "indoor"),),
        hard_avoids=(),
        trace=(
            # Noisy proxy: her true taste is the CATEGORY "Gardening", but the only recorded
            # signal is an ENJOYED report on a gardening listing with "the location" named as
            # what she liked -- which teaches DISTANCE, not CATEGORY (see
            # `LIKED_ASPECT_DIMENSIONS`).
            EnjoymentEvent("gardening-1", Enjoyment.ENJOYED, (LikedAspect.LOCATION,), _d(10)),
            DeclineEvent("karaoke-1", DeclineReason.TOO_TIRING, _d(20)),
            InterestEvent("walking-1", _d(4)),
        ),
        notes="Likes gardening; finds indoor sessions stuffy. Trace under-teaches the taste.",
    ),
    PersonaBrief(
        person_id="eval-mr-goh",
        display_name="Mr Goh (synthetic)",
        mobility_radius_m=5000,
        tight_mobility_radius_m=1000,
        preferred_language="Mandarin",
        stated_tastes=((PreferenceDimension.SOCIAL, "social"),),
        soft_avoids=((PreferenceDimension.INTENSITY, "moderate"),),
        hard_avoids=((PreferenceDimension.CATEGORY, "Aqua Aerobics"),),
        trace=(
            StatedPreferenceEvent(
                PreferenceDimension.SOCIAL, "social", 1.0, "I'd rather do things with company."
            ),
            DeclineEvent("aqua-1", DeclineReason.NOT_FOR_ME, _d(8)),
        ),
        notes="Explicitly stated a taste for company; a hard, no-exceptions avoid of Aqua "
        "Aerobics.",
    ),
    PersonaBrief(
        person_id="eval-mdm-lee",
        display_name="Mdm Lee (synthetic)",
        mobility_radius_m=1200,
        tight_mobility_radius_m=600,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.TIMING, "morning"),),
        soft_avoids=(),
        hard_avoids=(),
        trace=(
            EnjoymentEvent("walking-1", Enjoyment.ENJOYED, (LikedAspect.TIMING,), _d(6)),
            EnjoymentEvent("tai-chi-1", Enjoyment.OKAY, (LikedAspect.TIMING,), _d(15)),
        ),
        notes="A clean case: taste and trace agree, so preferences should actually be learned.",
    ),
    PersonaBrief(
        person_id="eval-mr-ong",
        display_name="Mr Ong (synthetic)",
        mobility_radius_m=4000,
        tight_mobility_radius_m=1500,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Chess Club"),),
        soft_avoids=((PreferenceDimension.CATEGORY, "Line Dancing"),),
        hard_avoids=(),
        trace=(
            EnjoymentEvent("chess-2", Enjoyment.ENJOYED, (LikedAspect.ACTIVITY,), _d(12)),
            DeclineEvent("linedance-1", DeclineReason.NOT_FOR_ME, _d(3)),
        ),
        notes="Recent decline on linedance-1 is inside the 14-day cooldown as of FROZEN_TODAY.",
    ),
    PersonaBrief(
        person_id="eval-mdm-siti",
        display_name="Mdm Siti (synthetic)",
        mobility_radius_m=3000,
        tight_mobility_radius_m=900,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.DISTANCE, "near"),),
        soft_avoids=((PreferenceDimension.CATEGORY, "Aqua Aerobics"),),
        hard_avoids=(),
        trace=(
            DeclineEvent("aqua-2", DeclineReason.TOO_FAR, _d(9)),
            InterestEvent("gardening-1", _d(2)),
        ),
        notes="Prefers near; only distance evidence recorded, category avoid never taught.",
    ),
    PersonaBrief(
        person_id="eval-mr-koh",
        display_name="Mr Koh (synthetic)",
        mobility_radius_m=6000,
        tight_mobility_radius_m=2000,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Qigong"),),
        soft_avoids=(),
        hard_avoids=((PreferenceDimension.SOCIAL, "social"),),
        trace=(
            StatedPreferenceEvent(
                PreferenceDimension.SOCIAL, "solo", 1.0, "I'd rather do my own thing."
            ),
            EnjoymentEvent("qigong-1", Enjoyment.ENJOYED, (LikedAspect.ACTIVITY,), _d(5)),
        ),
        notes="Hard avoid of company; also a clean, well-taught taste for Qigong.",
    ),
    PersonaBrief(
        person_id="eval-mdm-fatimah",
        display_name="Mdm Fatimah (synthetic)",
        mobility_radius_m=2000,
        tight_mobility_radius_m=700,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Community Choir"),),
        soft_avoids=((PreferenceDimension.TIMING, "evening"),),
        hard_avoids=(),
        trace=(
            EnjoymentEvent("choir-1", Enjoyment.ENJOYED, (LikedAspect.ACTIVITY,), _d(14)),
            DeclineEvent("qigong-1", DeclineReason.BAD_TIMING, _d(11)),
        ),
        notes="Choir taste well-taught; evening avoid taught indirectly via a different listing.",
    ),
    PersonaBrief(
        person_id="eval-mr-tan-wc",
        display_name="Mr Tan WC (synthetic)",
        mobility_radius_m=1000,
        tight_mobility_radius_m=500,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Watercolour"),),
        soft_avoids=(),
        hard_avoids=(),
        trace=(),
        notes="A pure cold-start persona: a stated taste with an entirely empty observation trace.",
    ),
    PersonaBrief(
        person_id="eval-mdm-nora",
        display_name="Mdm Nora (synthetic)",
        mobility_radius_m=3500,
        tight_mobility_radius_m=1200,
        preferred_language="Mandarin",
        stated_tastes=((PreferenceDimension.CATEGORY, "Mahjong"),),
        soft_avoids=((PreferenceDimension.ENVIRONMENT, "outdoor"),),
        hard_avoids=(),
        trace=(
            EnjoymentEvent("mahjong-1", Enjoyment.ENJOYED, (LikedAspect.ACTIVITY,), _d(7)),
            DeclineEvent("tai-chi-1", DeclineReason.BAD_DAY, _d(2)),
        ),
        notes="Decline reasoned BAD_DAY teaches nothing (see DECLINE_REASON_DIMENSIONS) -- noise.",
    ),
    PersonaBrief(
        person_id="eval-mr-yusof",
        display_name="Mr Yusof (synthetic)",
        mobility_radius_m=7000,
        tight_mobility_radius_m=2500,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.SOCIAL, "solo"),),
        soft_avoids=((PreferenceDimension.CATEGORY, "Karaoke"),),
        hard_avoids=(),
        trace=(
            StatedPreferenceEvent(PreferenceDimension.SOCIAL, "solo", 1.0, "I don't like crowds."),
            DeclineEvent("karaoke-1", DeclineReason.NOT_FOR_ME, _d(30)),
        ),
        notes="Karaoke decline is outside the 14-day cooldown; must not be graded 0 for that "
        "reason.",
    ),
)

HOLDOUT_PERSONAS: tuple[PersonaBrief, ...] = (
    PersonaBrief(
        person_id="eval-mdm-poh",
        display_name="Mdm Poh (synthetic, holdout)",
        mobility_radius_m=2500,
        tight_mobility_radius_m=900,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Walking Group"),),
        soft_avoids=((PreferenceDimension.INTENSITY, "moderate"),),
        hard_avoids=(),
        trace=(
            EnjoymentEvent("walking-1", Enjoyment.ENJOYED, (LikedAspect.ACTIVITY,), _d(9)),
            DeclineEvent("aqua-1", DeclineReason.TOO_TIRING, _d(5)),
        ),
        notes="Holdout. Never used while any ranking factor was designed or tuned.",
    ),
    PersonaBrief(
        person_id="eval-mr-lim-kw",
        display_name="Mr Lim KW (synthetic, holdout)",
        mobility_radius_m=1800,
        tight_mobility_radius_m=700,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Board Games"),),
        soft_avoids=(),
        hard_avoids=((PreferenceDimension.CATEGORY, "Karaoke"),),
        trace=(
            StatedPreferenceEvent(
                PreferenceDimension.CATEGORY, "Karaoke", -1.0, "Please, never karaoke."
            ),
            EnjoymentEvent("boardgames-1", Enjoyment.ENJOYED, (LikedAspect.ACTIVITY,), _d(4)),
        ),
        notes="Holdout. Hard avoid stated directly, at full negative strength.",
    ),
    PersonaBrief(
        person_id="eval-mdm-suriati",
        display_name="Mdm Suriati (synthetic, holdout)",
        mobility_radius_m=4500,
        tight_mobility_radius_m=1600,
        preferred_language="Mandarin",
        stated_tastes=((PreferenceDimension.CATEGORY, "Choir"),),
        soft_avoids=((PreferenceDimension.CATEGORY, "Chess Club"),),
        hard_avoids=(),
        trace=(
            EnjoymentEvent("choir-1", Enjoyment.OKAY, (LikedAspect.ACTIVITY,), _d(16)),
            InterestEvent("chess-1", _d(1)),
        ),
        notes="Holdout. Category name in stated taste ('Choir') deliberately does not exactly "
        "match any candidate's own category string ('Community Choir') -- the taste is real, but "
        "the ground truth reader must not accidentally substring-match; it will not fire.",
    ),
    PersonaBrief(
        person_id="eval-mr-hassan",
        display_name="Mr Hassan (synthetic, holdout)",
        mobility_radius_m=6000,
        tight_mobility_radius_m=2200,
        preferred_language="English",
        stated_tastes=((PreferenceDimension.CATEGORY, "Qigong"),),
        soft_avoids=((PreferenceDimension.SOCIAL, "social"),),
        hard_avoids=(),
        trace=(
            EnjoymentEvent("qigong-3", Enjoyment.ENJOYED, (LikedAspect.ACTIVITY,), _d(13)),
            DeclineEvent("choir-1", DeclineReason.PREFER_SOMETHING_ELSE, _d(6)),
        ),
        notes="Holdout. PREFER_SOMETHING_ELSE teaches only a barely-there neutral, never a taste.",
    ),
)

ALL_PERSONAS: tuple[PersonaBrief, ...] = CORE_PERSONAS + HOLDOUT_PERSONAS

assert {p.person_id for p in CORE_PERSONAS}.isdisjoint({p.person_id for p in HOLDOUT_PERSONAS})
# 10 core / 4 holdout: matches the spec's requested holdout split (roughly 70/30) for a persona
# count in the requested 12-20 range.
assert len(CORE_PERSONAS) == 10
assert len(HOLDOUT_PERSONAS) == 4


# ── Query templates ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryTemplate:
    name: str
    description: str
    rain_forecast: bool
    build_intent: Callable[[PersonaBrief], ActivityIntent]


def _unconstrained(_: PersonaBrief) -> ActivityIntent:
    return ActivityIntent()


def _tuesday_morning_indoors_gentle(_: PersonaBrief) -> ActivityIntent:
    return ActivityIntent(
        on_date=FROZEN_TODAY,
        time_window=TimeWindow.MORNING,
        environment=ActivityEnvironment.INDOOR,
        intensity=ActivityIntensity.LIGHT,
    )


def _meet_people_nearby(persona: PersonaBrief) -> ActivityIntent:
    return ActivityIntent(
        social_preference=SocialPreference.SOCIAL,
        max_distance_m=persona.mobility_radius_m,
        # A persona's mobility radius is a *limit*, not a turn of phrase, and the grading assumes
        # `filter_candidates` removes anything beyond it (`constraint_satisfaction@3` is 1.0 by
        # construction). `distance_is_explicit` is what says so now that a vague "near me" no
        # longer filters; without it these templates would silently become soft.
        distance_is_explicit=True,
    )


def _language_constrained(persona: PersonaBrief) -> ActivityIntent:
    return ActivityIntent(language=persona.preferred_language)


def _distance_constrained(persona: PersonaBrief) -> ActivityIntent:
    return ActivityIntent(max_distance_m=persona.tight_mobility_radius_m, distance_is_explicit=True)


def _evening_solitary(_: PersonaBrief) -> ActivityIntent:
    return ActivityIntent(time_window=TimeWindow.EVENING, social_preference=SocialPreference.SOLO)


# All six use `rain_forecast=True`: the context factor only ever nudges anything when the person
# left the environment left open (`ActivityEnvironment.EITHER`), which is true for four of the six
# templates and false for the other two (`tuesday_morning_indoors_gentle` asks INDOOR outright).
# Fixing it True everywhere -- rather than varying it -- means the `no_context` ablation's null
# result on the other two templates is a fact about those templates' own constraints, not about an
# arbitrarily-chosen forecast.
QUERY_TEMPLATES: tuple[QueryTemplate, ...] = (
    QueryTemplate("unconstrained", "Something to do", True, _unconstrained),
    QueryTemplate(
        "tuesday_morning_indoors_gentle",
        "Tuesday morning indoors gentle",
        True,
        _tuesday_morning_indoors_gentle,
    ),
    QueryTemplate("meet_people_nearby", "Meet people nearby", True, _meet_people_nearby),
    QueryTemplate("language_constrained", "In my own language", True, _language_constrained),
    QueryTemplate("distance_constrained", "Close to home", True, _distance_constrained),
    QueryTemplate(
        "evening_solitary", "Something quiet in the evening, on my own", True, _evening_solitary
    ),
)


# ── Dataset digest ───────────────────────────────────────────────────────────────────────────


def _event_document(event: TraceEvent) -> dict[str, object]:
    if isinstance(event, DeclineEvent):
        return {
            "kind": "decline",
            "activity_id": event.activity_id,
            "reason": event.reason.value,
            "day": event.day.isoformat(),
        }
    if isinstance(event, EnjoymentEvent):
        return {
            "kind": "enjoyment",
            "activity_id": event.activity_id,
            "enjoyment": event.enjoyment.value,
            "liked": [aspect.value for aspect in event.liked],
            "day": event.day.isoformat(),
        }
    if isinstance(event, InterestEvent):
        return {"kind": "interest", "activity_id": event.activity_id, "day": event.day.isoformat()}
    return {
        "kind": "stated_preference",
        "dimension": event.dimension.value,
        "value": event.value,
        "strength": event.strength,
        "stated_text": event.stated_text,
    }


def _persona_document(persona: PersonaBrief) -> dict[str, object]:
    return {
        "person_id": persona.person_id,
        "mobility_radius_m": persona.mobility_radius_m,
        "tight_mobility_radius_m": persona.tight_mobility_radius_m,
        "preferred_language": persona.preferred_language,
        "stated_tastes": [[dim.value, val] for dim, val in persona.stated_tastes],
        "soft_avoids": [[dim.value, val] for dim, val in persona.soft_avoids],
        "hard_avoids": [[dim.value, val] for dim, val in persona.hard_avoids],
        "trace": [_event_document(event) for event in persona.trace],
    }


def holdout_digest() -> str:
    """A sha256 over the holdout personas alone -- the ranking benchmark's own holdout freeze.

    The policy harness freezes a directory of YAML (`scenarios/holdout/FROZEN_DIGEST`); this
    benchmark's holdout is four persona briefs in code, so the same process needs its own digest.
    `HOLDOUT_FROZEN_DIGEST` below is what it was frozen at, and the artifact prints
    `holdout_frozen` on every run. Editing a holdout persona is not forbidden -- it is visible, and
    a genuine change belongs in a new set rather than under the old numbers.
    """
    encoded = json.dumps(
        [_persona_document(persona) for persona in HOLDOUT_PERSONAS], sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


HOLDOUT_FROZEN_DIGEST = "30b55f64a79f6af4eb7187a609ccaa0f1aee37e67b254798995fbcb41c4b765a"
"""The digest `HOLDOUT_PERSONAS` was frozen at. Changing a holdout persona without changing this
line makes the artifact print `holdout_frozen: false` and fails
`test_ranking_holdout_personas_match_their_frozen_digest`."""


def holdout_frozen() -> bool:
    return holdout_digest() == HOLDOUT_FROZEN_DIGEST


def dataset_digest() -> str:
    """A sha256 over every input that can change what this benchmark measures: the catalogue, the
    persona briefs (including their traces) and the query templates' constraints. Deliberately
    excludes docstrings/comments/notes -- those can change without the dataset itself changing.
    """

    document = {
        "catalogue": [candidate.model_dump(mode="json") for candidate in CATALOGUE],
        "core_personas": [_persona_document(p) for p in CORE_PERSONAS],
        "holdout_personas": [_persona_document(p) for p in HOLDOUT_PERSONAS],
        "query_templates": [
            {
                "name": template.name,
                "rain_forecast": template.rain_forecast,
                # Serialise the intent each template produces for every persona, so a template
                # whose logic changed (even if its name did not) moves the digest.
                "intents": [
                    template.build_intent(persona).model_dump(mode="json")
                    for persona in ALL_PERSONAS
                ],
            }
            for template in QUERY_TEMPLATES
        ],
    }
    encoded = json.dumps(document, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
