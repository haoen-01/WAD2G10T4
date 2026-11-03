"""The dimensional preference learner (F29/F30) -- what is known about a *kind* of activity.

`learning.py` holds a Beta-Bernoulli posterior *per candidate*. That can only ever say "not this
one" -- it has nothing to say about an activity that has never been offered. The product
requirement this module exists to satisfy, verbatim: **"too far" must teach something different
from "just not today".**

HARD INVARIANT -- this module ranks, it never gates. A dimension may reorder what the
deterministic policy ladder (`policy.py`) already permitted. It can never permit, escalate,
unblock, or flip a consent / data-quality / confidence / contact-cap / stale-programme / review
gate, and it never sees or touches any of those gates. Nothing here returns a `Decision` and
nothing here imports from `policy.py` -- that asymmetry is deliberate and must stay true.

No double-counting. A decline already moves the per-candidate posterior in `learning.py`: that is
one unit of evidence about "should this exact listing be offered again". `apply_decline` below is
a *second, different* statement -- "should things shaped like this be offered again".

## Three shapes of belief, and why

**Nominal** (SOCIAL, ENVIRONMENT, TIMING, ACTIVITY_TYPE): a value from a closed list. A candidate
either carries that value, carries a different one, or does not say.

**Ordinal** (DISTANCE, INTENSITY): a `pivot` and a `direction`. "1.2 km was too far" is a
statement about a ceiling; storing it as the nominal bucket the listing happened to fall in
(`near`) taught the system to avoid activities *near home* -- the exact opposite of what was said,
and to a person who had simply named a distance. An ordinal belief is a line, not a label.

**Item-level**: an answer that is about the one thing in front of the person and nothing more.
One "bad timing" is not a statement about mornings, and one "not for me" is not a statement about
every walk; the 14-day cooldown already holds that listing back, and generalising either needs a
clarification chip or a second agreeing answer about a different programme. The ordinal answers
are the exception: "too far" and "too tiring" are about the listing's own distance or intensity, a
line drawn at a number the listing carries, so they record a ceiling that applies at once -- and a
ceiling only ever narrows.

## Sentiment, confidence and evidence are three facts, not one number

`strength = (positive - negative) / (positive + negative + 2)` says which way a belief leans.
`confidence = (positive + negative) / (positive + negative + 2)` says how much sits behind it.
They used to be one signed scalar, which meant `0.0` could not be told apart from "nothing
known", a like on one axis exactly cancelled an avoid on another, and folding "it was fine" into
"I loved it" made what was learned depend on the order the two arrived in. Counting both sides
makes all three problems go away by construction.

## The tier wins the axis; it never averages into it

`SourceTier` orders how a belief came to be held. Within one resolution group only the highest
active tier contributes -- a guess never dilutes something a person said in plain words. A group is
the whole axis where values exclude one another (TIMING, ENVIRONMENT, SOCIAL) or sit on one scale
(DISTANCE, INTENSITY), and one value on ACTIVITY_TYPE, where "no walks this week" says nothing
about arts and crafts (`_resolution_group`). Across groups, contributions sum with
`Sigma |strength|` as the denominator, so matching one of three stated likes is no longer
indistinguishable from matching all three.

## Nothing is written that nobody said

Every write-side fallback is gone. A "too tiring" on a listing with no intensity records nothing
(it used to invent `moderate`); a "too far" on a listing with no distance records nothing (it used
to record `far`); "the people" is only evidence about company when the listing actually says what
its company is (it used to assert `social` regardless). `UNKNOWN` stays unknown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Final, Literal

from silverloop.local_time import local_date, local_hour
from silverloop.models import (
    ActivityCandidate,
    ActivityEnvironment,
    ActivityGoal,
    ActivityIntensity,
    ActivityPreferences,
    ClarificationScope,
    DeclineReason,
    DimensionPreference,
    Enjoyment,
    FactConfidence,
    GoalKind,
    IndoorOutdoor,
    LikedAspect,
    PreferenceDimension,
    ResolvedPreference,
    SocialPreference,
    SourceTier,
)
from silverloop.ontology import ACTIVITY_TYPE_LABEL, ActivityType

# ── Three-valued comparison ───────────────────────────────────────────────────────────────────


class Tri(Enum):
    """MATCH / MISMATCH / UNKNOWN, and the reason the third member exists.

    `None` on either side is UNKNOWN, never MISMATCH. An unlisted language is not a language the
    person cannot speak; an unlabelled session is not a solitary one. UNKNOWN is excluded from
    both the numerator and the denominator of every fit here -- so it is never a penalty -- and
    the count of MATCH axes breaks ties, so it is never free either.
    """

    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


def compare(feature_value: object | None, asked_value: object | None) -> Tri:
    """The one definition of "does this candidate satisfy that ask".

    Total over its inputs and deliberately dull: `None` on either side is UNKNOWN. Every fit in
    the ranker is built from this, so no caller can accidentally reinvent "missing means no".
    """
    if feature_value is None or asked_value is None:
        return Tri.UNKNOWN
    return Tri.MATCH if feature_value == asked_value else Tri.MISMATCH


# ── Environment, in one place ─────────────────────────────────────────────────────────────────

# What an environment *ask* accepts. `SHELTERED` is its own answer, not a synonym for either
# extreme: someone who explicitly wants sheltered has usually said so because plain indoor or
# plain outdoor both miss the point ("somewhere covered, but not stuck inside").
_ENVIRONMENT_COMPATIBLE: Final[dict[ActivityEnvironment, frozenset[IndoorOutdoor]]] = {
    ActivityEnvironment.INDOOR: frozenset({IndoorOutdoor.INDOOR, IndoorOutdoor.SHELTERED}),
    ActivityEnvironment.OUTDOOR: frozenset({IndoorOutdoor.OUTDOOR, IndoorOutdoor.SHELTERED}),
    ActivityEnvironment.SHELTERED: frozenset({IndoorOutdoor.SHELTERED}),
}


def environment_compatibility(ask: ActivityEnvironment, listing: IndoorOutdoor) -> Tri:
    """Whether a listing's surroundings satisfy an environment ask.

    The single definition, shared by the hard filter, the preference reader, the rain nudge and
    the evaluation harness's grounding check. Three separate copies of this question used to
    coexist and disagree about whether "sheltered" counted as indoors -- so a listing could be
    filtered in on one reading and scored out on another, which is unanswerable from the audit
    trail because both are "the environment rule".

    `EITHER` asks nothing, so it can neither match nor mismatch; `UNKNOWN` says nothing, so it
    cannot either. Both are UNKNOWN, never MISMATCH.
    """
    if ask is ActivityEnvironment.EITHER or listing is IndoorOutdoor.UNKNOWN:
        return Tri.UNKNOWN
    return Tri.MATCH if listing in _ENVIRONMENT_COMPATIBLE[ask] else Tri.MISMATCH


def covered(listing: IndoorOutdoor) -> bool:
    """Whether rain is beside the point for this listing. `indoor | sheltered`, once."""
    return environment_compatibility(ActivityEnvironment.INDOOR, listing) is Tri.MATCH


# ── Ordinal ladders ───────────────────────────────────────────────────────────────────────────

# The intensity rungs, gentlest first. `EITHER` is an *ask*, never a listing, so it has no rung.
# An ordinal belief is an index into this tuple, which is what lets "that was too tiring" mean
# "something below this" rather than "not this label".
INTENSITY_LADDER: Final[tuple[ActivityIntensity, ...]] = (
    ActivityIntensity.LIGHT,
    ActivityIntensity.MODERATE,
)


def intensity_index(intensity: ActivityIntensity | None) -> int | None:
    """The rung `intensity` sits on, or `None` when the listing does not say.

    Never guesses. The write side used to substitute `MODERATE` for an unlabelled listing, which
    meant every outreach "too tiring" stored a fact the resolver's own contract promised it could
    not store -- and one that contradicted the catalogue row it was derived from.
    """
    if intensity is None or intensity not in INTENSITY_LADDER:
        return None
    return INTENSITY_LADDER.index(intensity)


# Distances at or under this cost nothing on `travel_utility`, until the person's own answers say
# otherwise. 500 m is a short walk for most people. Not a claim about anyone's mobility: a
# person's own "too far" is what moves this, and it moves it for them alone.
DEFAULT_TRAVEL_TOLERANCE_M: Final[int] = 500

# What "near" means when nobody gave a number: the radius a "somewhere near me" request asks for
# (`intent.parse_intent`), and the ceiling a stated "I prefer things nearby" -- or the
# `less_travel` goal -- puts on the comfortable distance (`travel_tolerance_m`). One constant, so
# "near" in a request and "near" in a statement can never mean two different distances.
NEARBY_RADIUS_M: Final[int] = 1000

# The direction token an ordinal row is keyed by, since `value` is half the table's unique key and
# the number itself lives in `pivot`. Never rendered: the screen reads `pivot` and says
# "closer than about 1.2 km".
_LOWER: Final[str] = "lower"
_HIGHER: Final[str] = "higher"

ORDINAL_DIMENSIONS: Final[frozenset[PreferenceDimension]] = frozenset(
    {PreferenceDimension.DISTANCE, PreferenceDimension.INTENSITY}
)


# ── Reason -> dimension ──────────────────────────────────────────────────────────────────────
#
# `BAD_DAY` and `ALREADY_ACTIVE` map to `None` on purpose:
#   * `BAD_DAY` ("just not today") is not evidence about the suggestion at all -- it is
#     evidence about the day.
#   * `ALREADY_ACTIVE` is a data-quality signal (the sensor undercounted real activity).
DECLINE_REASON_DIMENSIONS: dict[DeclineReason, PreferenceDimension | None] = {
    # "Not interested in this sort of thing" is about what the activity *is*. It used to write
    # `CATEGORY`, which holds a format label ("Group class"), so one "not for me" on a morning
    # walk taught a dislike of nine unrelated programmes -- tai chi and gardening among them.
    DeclineReason.NOT_FOR_ME: PreferenceDimension.ACTIVITY_TYPE,
    DeclineReason.BAD_DAY: None,
    DeclineReason.ALREADY_ACTIVE: None,
    DeclineReason.TOO_FAR: PreferenceDimension.DISTANCE,
    DeclineReason.TOO_TIRING: PreferenceDimension.INTENSITY,
    DeclineReason.BAD_TIMING: PreferenceDimension.TIMING,
    # A request to be shown alternatives, not a statement about this kind of activity.
    DeclineReason.PREFER_SOMETHING_ELSE: None,
    # SOCIAL is reached from a senior's own words ("I don't like walking alone") or from a liked
    # aspect, never inferred from a decline.
}

# `LikedAspect` names four axes a person can call out after the fact:
#   PEOPLE    -> SOCIAL        (only when the listing actually says what its company is)
#   LOCATION  -> DISTANCE      (ordinal: this far was fine)
#   TIMING    -> TIMING
#   ACTIVITY  -> ACTIVITY_TYPE (what the thing is, not how it is run)
LIKED_ASPECT_DIMENSIONS: dict[LikedAspect, PreferenceDimension] = {
    LikedAspect.PEOPLE: PreferenceDimension.SOCIAL,
    LikedAspect.LOCATION: PreferenceDimension.DISTANCE,
    LikedAspect.TIMING: PreferenceDimension.TIMING,
    LikedAspect.ACTIVITY: PreferenceDimension.ACTIVITY_TYPE,
}

# An `ActivityGoal` is a closed-vocabulary thing the person chose, so it belongs above anything
# learned and below anything they said in their own words (`SourceTier.STATED_GOAL`). Only the
# goals that name a preference axis are folded in:
#
#   MEET_PEOPLE      -> SOCIAL = social         ("I want to meet people" is about company)
#   MORNING_ACTIVITY -> TIMING = morning        (it names the slot outright)
#   LESS_TRAVEL      -> DISTANCE = near         (a stated "near" with no number: no pivot is
#                                                invented; it caps the comfortable distance at
#                                                `NEARBY_RADIUS_M`, exactly as a stated "near"
#                                                does -- see `travel_beliefs`)
#
# `GET_OUT_MORE` names a frequency, not a kind, and is left out rather than mapped approximately.
GOAL_DIMENSION_VALUES: dict[GoalKind, tuple[PreferenceDimension, str]] = {
    GoalKind.MEET_PEOPLE: (PreferenceDimension.SOCIAL, SocialPreference.SOCIAL.value),
    GoalKind.MORNING_ACTIVITY: (PreferenceDimension.TIMING, "morning"),
    GoalKind.LESS_TRAVEL: (PreferenceDimension.DISTANCE, "near"),
}

# How much one answer is worth as evidence. "It was fine" is not an endorsement and must never
# compound into one however often it repeats; a decline and an enjoyed activity are each one
# whole observation on their own side of the ledger.
_ENJOYED_EVIDENCE: Final[float] = 1.0
_OKAY_EVIDENCE: Final[float] = 0.15
_DECLINE_EVIDENCE: Final[float] = 1.0

# What the pre-split code capped a "barely a preference" *magnitude* at
# (`_NEUTRAL_EVIDENCE_CAP`, the same 0.15): it stored `strength = 0.15 * n/(n+2)` for
# `Enjoyment.OKAY` and for `PREFER_SOMETHING_ELSE`, against `n/(n+2)` for everything else. Kept
# here because a row written before the split still has to be read: `_legacy_evidence` and the
# `e1c9a5d70b42` backfill both use it to tell one band from the other, which they can do exactly
# rather than approximately because the two bands do not overlap.
_LEGACY_MAGNITUDE_CAP: Final[float] = 0.15

# One decline is weak evidence and must read that way: `strength` grows with the count but never
# reaches +/-1, so a single answer nudges a dimension a third of the way and a long run of them
# approaches, but never reaches, certainty.
_EVIDENCE_SMOOTHING: Final[float] = 2.0

# Three or more agreeing origins is where a learned belief stops being a hint.
_STRONG_LEARNED_ORIGINS: Final[int] = 3
# ... and how far a hint may ever move the order, whatever it is built on.
_WEAK_LEARNED_WEIGHT_CAP: Final[float] = 0.35

# An item-level belief generalises only once a second answer agrees with it. One "bad timing" is
# about the session in front of the person; two on the same slot, about two different programmes,
# are about the slot. Two about the same programme are still about that programme (`_fold`).
_GENERALISE_AFTER_OBSERVATIONS: Final[int] = 2

SENIOR_STATEMENT_SOURCE = "senior_statement"
DECLINE_SOURCE = "decline_reason"
# Enjoyment (and goals) keep their own tier rather than sharing the decline's, because the same
# (dimension, value) pair can be reached from opposite directions -- an activity once declined as
# too far, later enjoyed -- and one must never reset the other's accumulated evidence.
_ENJOYMENT_SOURCE = "inferred"

# Which scopes mean "this one thing only". A row carrying one of these is held back from the
# resolved set until a second answer about a different programme agrees with it.
_ITEM_LEVEL_SCOPES: Final[frozenset[ClarificationScope]] = frozenset(
    {
        ClarificationScope.THIS_ONE,
        ClarificationScope.THIS_SLOT,
        ClarificationScope.THIS_VENUE,
        ClarificationScope.THIS_FORMAT,
    }
)

_DIMENSION_LABELS: dict[PreferenceDimension, str] = {
    PreferenceDimension.DISTANCE: "distance",
    PreferenceDimension.INTENSITY: "intensity",
    PreferenceDimension.TIMING: "timing",
    PreferenceDimension.SOCIAL: "social setting",
    PreferenceDimension.ENVIRONMENT: "indoors or outdoors",
    PreferenceDimension.CATEGORY: "kind of activity",
    PreferenceDimension.ACTIVITY_TYPE: "kind of activity",
}


def _timing_bucket(start_at: datetime | None) -> str | None:
    if start_at is None:
        return None
    hour = local_hour(start_at)
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


# The values each dimension can take, for a preference the person states directly. A stated
# value outside these can never match a candidate, so accepting it would store a confirmed belief
# that means nothing and reads as something else once phrased.
#
# `EITHER` is excluded from INTENSITY and SOCIAL for exactly that reason: a candidate is light or
# moderate, never "either". `CATEGORY` is **closed to nothing at all** -- it is deprecated, never
# written, and a route that accepted a stated value on it would be writing to a dead axis.
STATED_VALUE_VOCABULARY: dict[PreferenceDimension, frozenset[str]] = {
    PreferenceDimension.DISTANCE: frozenset({"near", "far"}),
    PreferenceDimension.INTENSITY: frozenset(member.value for member in INTENSITY_LADDER),
    PreferenceDimension.TIMING: frozenset({"morning", "afternoon", "evening"}),
    PreferenceDimension.ENVIRONMENT: frozenset(
        member.value for member in IndoorOutdoor if member is not IndoorOutdoor.UNKNOWN
    ),
    PreferenceDimension.SOCIAL: frozenset(
        member.value for member in SocialPreference if member is not SocialPreference.EITHER
    ),
    # Closed to the enum. The route used to accept any 160-character string here (as `category`),
    # so a stated "Walking" was storable and could never match anything ever again.
    PreferenceDimension.ACTIVITY_TYPE: frozenset(
        member.value for member in ActivityType if member is not ActivityType.OTHER
    ),
    PreferenceDimension.CATEGORY: frozenset(),
}

# Axes nothing may state a *new* preference on. The rows already in the table stay readable and
# forgettable -- a person must be able to delete a belief this product once held about them --
# but no route may add another.
DEPRECATED_DIMENSIONS: Final[frozenset[PreferenceDimension]] = frozenset(
    {PreferenceDimension.CATEGORY}
)


def _candidate_dimension_value(
    dimension: PreferenceDimension, candidate: ActivityCandidate
) -> str | None:
    """What `candidate` says about `dimension`, for the nominal axes -- or `None` when it does not
    say. The single source of truth for that question, so a candidate can never match an axis for
    one purpose (an explanation) and not for another (the score built from that explanation).

    `ActivityType.OTHER` reads as `None` on purpose. "Labelled, and none of the above" is not a
    kind of thing anyone can like or dislike, and letting it match would make every unclassifiable
    listing evidence about every other one.
    """
    if dimension is PreferenceDimension.DISTANCE:
        # Ordinal. `travel_utility` is the only thing that scores distance, from a tolerance in
        # metres -- there is no nominal value here to compare against any more.
        return None
    if dimension is PreferenceDimension.INTENSITY:
        return candidate.intensity.value if candidate.intensity is not None else None
    if dimension is PreferenceDimension.TIMING:
        return _timing_bucket(candidate.start_at)
    if dimension is PreferenceDimension.ENVIRONMENT:
        if candidate.indoor_outdoor is IndoorOutdoor.UNKNOWN:
            return None
        return candidate.indoor_outdoor.value
    if dimension is PreferenceDimension.ACTIVITY_TYPE:
        if candidate.activity_type is None or candidate.activity_type is ActivityType.OTHER:
            return None
        return candidate.activity_type.value
    if dimension is PreferenceDimension.CATEGORY:
        # Deprecated and never written. Still read so a row from before the split renders and can
        # be forgotten; it contributes nothing to any score (see `UTILITY_DIMENSIONS`).
        return candidate.category
    if dimension is PreferenceDimension.SOCIAL:
        return candidate.social_shape.value if candidate.social_shape is not None else None
    return None


# ── Observations ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PreferenceObservation:
    """One thing that happened, read as evidence about a kind of activity.

    **Derived, never a table.** Every observation is reconstructible from rows that already
    exist -- the stored belief, the offer responses behind it, the enjoyment reports, the
    statements, the goals -- and a second write path for the same fact is a second thing that can
    be wrong. `origin_id` is what makes one origin one observation: a tap folded twice is still
    one thing the person did.
    """

    origin: Literal["offer_response", "intervention", "plan", "senior_statement", "goal"]
    origin_id: str
    kind: Literal["decline", "enjoyment", "statement", "goal", "retraction"]
    dimension: PreferenceDimension
    sentiment: Literal["like", "avoid", "neutral", "retract"]
    value: str | None = None
    pivot: float | None = None
    direction: Literal["lower", "higher"] | None = None
    scope: ClarificationScope | None = None
    source_tier: SourceTier = SourceTier.WEAK_LEARNED
    source: Literal["senior_statement", "decline_reason", "inferred"] = "inferred"
    positive_evidence: float = 0.0
    negative_evidence: float = 0.0
    observed_on_day: date | None = None
    run_id: str | None = None
    expires_on_day: date | None = None
    stated_text: str | None = None
    superseded_by: str | None = None
    origin_activity_id: str | None = None
    supporting: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        """`dimension:value:source` -- how a belief is named wherever one is shown beside
        another: the Privacy screen's React key, the world model's fact key, and the
        `contradicted_by` list here. Never `dimension` alone: the table stores a separate row per
        source tier, and collapsing them makes one card's controls act on another card's row.

        A goal is `goal:dimension:value` (`goal_key`). It resolves with the source
        `senior_statement`, so the row-shaped key would name a goal and a statement on the same
        value identically -- and a stated "avoid" beside a goal for that value would then be
        reported contradicting *itself*."""
        if self.origin == "goal":
            return goal_key(self.dimension, self.value)
        return f"{self.dimension.value}:{self.value}:{self.source}"


GOAL_KEY_PREFIX: Final[str] = "goal:"


def goal_key(dimension: PreferenceDimension, value: str | None) -> str:
    """How a goal-derived belief is named in `supporting` and `contradicted_by`. No stored row's
    key can collide with it: a row's key starts with a `PreferenceDimension` value, and none of
    those is `goal`."""
    return f"{GOAL_KEY_PREFIX}{dimension.value}:{value}"


def is_goal_key(key: str) -> bool:
    """Whether a `supporting`/`contradicted_by` key names a goal rather than a stored row."""
    return key.startswith(GOAL_KEY_PREFIX)


def evidence_split(preference: DimensionPreference) -> tuple[float, float]:
    """A belief's evidence for and against, reconstructed when the row does not carry it.

    Every row written since the evidence split carries both sides. A row written before it -- and
    every `DimensionPreference` a test, a scenario or the evaluation harness's trace replay builds
    by hand from `strength` alone -- carries neither, so the split is read back out of the row's
    own numbers by `_legacy_evidence`: exactly the rule the Alembic backfill applies, so a belief
    means the same thing however it reached this function.

    A belief with a lean but no count is one observation. A belief with no lean at all is evidence
    for neither side; "no lean" is not half a lean.
    """
    if preference.positive_evidence or preference.negative_evidence:
        return preference.positive_evidence, preference.negative_evidence
    if preference.strength == 0:
        return 0.0, 0.0
    folded = _legacy_evidence(preference)
    return (folded, 0.0) if preference.strength > 0 else (0.0, folded)


def _legacy_evidence(preference: DimensionPreference) -> float:
    """How much evidence a pre-split row stands for, read from `strength`, `observations` and
    `source` -- the three things such a row has.

    Pre-split, `strength` was always `cap * n / (n + 2)`: `cap = 1.0` for a decline or an enjoyed
    outing, and `cap = _LEGACY_MAGNITUDE_CAP` for the two "barely a preference" bands ("it was
    fine", "I'd prefer something else"). Reading `observations` whole treats the second as the
    first -- three "it was fine"s become three enjoyed outings, `0.090 -> 0.600`, a 6.7x
    amplification of a belief the person expressed as "fine" (red team P1-3). Scaling by the cap
    the row was written under gives `0.15 * 3` and resolves to `0.184`: exactly what a database
    this code writes from the same three reports holds. The number moves because the split
    changed what "it was fine" *is* -- a fraction of an observation rather than a capped
    magnitude -- not because the reconstruction re-weighted it, and it stays in the same
    barely-there band either way.

    Which cap a row was written under is decidable from the row: the two bands are disjoint,
    because with even one observation the uncapped shape is already `1/3` while the capped one
    can never reach `_LEGACY_MAGNITUDE_CAP`.

    A statement is one origin however many times it was made. `strength` on those rows is
    `+/-1.0` (there is nothing to invert), pre-split `observations` counted repeats rather than
    evidence, and `_confirm_dimension_preference` writes exactly this today.
    """
    if preference.source == SENIOR_STATEMENT_SOURCE:
        return 1.0
    observations = float(max(preference.observations, 1))
    if abs(preference.strength) <= _LEGACY_MAGNITUDE_CAP:
        return _OKAY_EVIDENCE * observations
    return observations


def observation_for(
    preference: DimensionPreference, *, today: date | None = None
) -> PreferenceObservation:
    """Read one stored belief back as the observation it stands for.

    The row *is* the accumulated observation: `positive_evidence`/`negative_evidence` are how many
    agreeing and disagreeing things have been folded into it, `origin_id` is the most recent of
    them, and `superseded_by` is set when the person retracted it or a statement consumed it.
    """
    expires_on_day = (
        local_date(preference.expires_at) if preference.expires_at is not None else None
    )
    positive, negative = evidence_split(preference)
    return PreferenceObservation(
        origin="senior_statement" if preference.source == SENIOR_STATEMENT_SOURCE else "plan",
        origin_id=preference.origin_id or preference.value,
        kind="statement" if preference.source == SENIOR_STATEMENT_SOURCE else "decline",
        dimension=preference.dimension,
        sentiment="like" if preference.strength >= 0 else "avoid",
        value=preference.value,
        pivot=preference.pivot,
        direction=preference.direction,
        scope=preference.scope,
        source_tier=_tier_for(preference, today=today),
        source=preference.source,
        positive_evidence=positive,
        negative_evidence=negative,
        observed_on_day=local_date(preference.updated_at),
        expires_on_day=expires_on_day,
        stated_text=preference.stated_text,
        superseded_by=preference.superseded_by,
    )


def goal_observation(goal: ActivityGoal) -> PreferenceObservation | None:
    """One `ActivityGoal`, read as the preference it literally is -- or `None` when it names no
    axis. `meet_people` and `morning_activity` are SOCIAL and TIMING statements held in a table
    the ranker could not see; this is the whole of A-F7's fix."""
    mapping = GOAL_DIMENSION_VALUES.get(goal.kind)
    if mapping is None or not goal.active:
        return None
    dimension, value = mapping
    return PreferenceObservation(
        origin="goal",
        origin_id=goal.goal_id,
        kind="goal",
        dimension=dimension,
        sentiment="like",
        value=value,
        source_tier=SourceTier.STATED_GOAL,
        source=SENIOR_STATEMENT_SOURCE,
        positive_evidence=1.0,
        observed_on_day=local_date(goal.created_at),
        stated_text=goal.text,
    )


def _tier_for(preference: DimensionPreference, *, today: date | None) -> SourceTier:
    """Which tier a stored belief sits in.

    A statement with a live `expires_at` is `TEMPORARY_STATED` ("no walks this week" outranks a
    standing preference for as long as it lasts). A statement that consumed an inferred row --
    "That's right" -- is `RATIFIED`, and `origin_id` holds the id of the row it consumed, which
    is what makes a ratified belief *one* row rather than two that contradict each other.
    Anything learned is `WEAK_LEARNED` until three distinct origins agree.
    """
    if preference.source == SENIOR_STATEMENT_SOURCE:
        if preference.expires_at is not None and (
            today is None or local_date(preference.expires_at) >= today
        ):
            return SourceTier.TEMPORARY_STATED
        if preference.origin_id is not None:
            return SourceTier.RATIFIED
        return SourceTier.STATED
    origins = _evidence_count(*evidence_split(preference))
    return (
        SourceTier.STRONG_LEARNED if origins >= _STRONG_LEARNED_ORIGINS else SourceTier.WEAK_LEARNED
    )


def _evidence_count(positive: float, negative: float) -> int:
    """Distinct origins behind a belief. A statement repeated three times is one piece of
    evidence, which is why a repeat never increments anything on a statement row
    (`_confirm_dimension_preference`) -- and why the world model's count and the ranker's
    confidence finally mean the same thing."""
    return int(round(positive + negative))


def derived_strength(positive: float, negative: float) -> float:
    """`(pos - neg) / (pos + neg + 2)`. Order-independent by construction, which is the whole of
    D-§7's fix: "it was fine" then "I loved it" and the reverse now resolve identically."""
    total = positive + negative
    if total <= 0:
        return 0.0
    return round((positive - negative) / (total + _EVIDENCE_SMOOTHING), 3)


def derived_confidence(positive: float, negative: float) -> float:
    """`(pos + neg) / (pos + neg + 2)`. The same curve as `strength`'s denominator, reported
    separately so "nothing known" and "two things that disagree" stop being the same number."""
    total = positive + negative
    if total <= 0:
        return 0.0
    return round(total / (total + _EVIDENCE_SMOOTHING), 3)


# What each tier's belief may weigh at full confidence. A hint stays a hint; a person's own words
# are allowed to be decisive. `CURRENT_REQUEST` has no entry because it never enters preference
# utility at all -- an axis constrained today is the filter's or request fit's, never history's.
_TIER_BASE_WEIGHT: Final[dict[SourceTier, float]] = {
    SourceTier.DEFAULT: 0.0,
    SourceTier.WEAK_LEARNED: _WEAK_LEARNED_WEIGHT_CAP,
    SourceTier.STRONG_LEARNED: 0.7,
    SourceTier.STATED_GOAL: 0.8,
    SourceTier.STATED: 1.0,
    SourceTier.RATIFIED: 1.0,
    SourceTier.TEMPORARY_STATED: 1.0,
}

# Anything learned is capped at MEDIUM however much of it there is. Three taps are not a person
# telling you something, and a screen that says "high confidence" about an inference is claiming
# a certainty the evidence cannot carry.
_STATED_TIERS: Final[frozenset[SourceTier]] = frozenset(
    {
        SourceTier.STATED_GOAL,
        SourceTier.STATED,
        SourceTier.RATIFIED,
        SourceTier.TEMPORARY_STATED,
    }
)


def is_stated_tier(tier: SourceTier) -> bool:
    """Whether a tier is the person's own word (a goal, a statement, a ratification, a statement for
    now) rather than something learned from their answers. The one definition every reader uses."""
    return tier in _STATED_TIERS


def _fact_confidence(numeric: float, *, tier: SourceTier) -> FactConfidence:
    if tier in _STATED_TIERS:
        return FactConfidence.HIGH if numeric >= 0.3 else FactConfidence.MEDIUM
    if numeric >= 0.6:
        return FactConfidence.MEDIUM
    return FactConfidence.LOW


def _effective_scope(
    row: DimensionPreference | PreferenceObservation,
) -> ClarificationScope | None:
    """The scope a stored belief is read with.

    A legacy row -- an ACTIVITY_TYPE `decline_reason` written with `scope=None` before unclarified
    "not for me"s were recorded as `THIS_ONE` -- is read as `THIS_ONE`, so the resolver
    (`_is_held_back`) holds one old tap back exactly like a new one.
    """
    if (
        row.scope is None
        and row.dimension is PreferenceDimension.ACTIVITY_TYPE
        and row.source == DECLINE_SOURCE
    ):
        return ClarificationScope.THIS_ONE
    return row.scope


def _is_held_back(observation: PreferenceObservation) -> bool:
    """Whether an item-level belief has yet to earn the right to generalise.

    Unclarified, one "bad timing" is about the session in front of the person: the cooldown
    already holds that listing back, and reading it as a statement about mornings is how someone
    who could not make one Tuesday class stopped being shown mornings at all. One unclarified "not
    for me" is the same (`THIS_ONE`): one walk turned down is not every walk. A second agreeing
    answer about a different programme (`_fold` refuses one about the same programme) -- or a chip
    widening it outright (`time_of_day`, `weekday`, `this_activity_type`) -- is what widens it.
    "Too far" and "too tiring" carry no item-level scope and are never held back: they are
    ceilings on the listing's own distance or intensity.

    A legacy row -- an ACTIVITY_TYPE `decline_reason` written with `scope=None` before unclarified
    "not for me"s were recorded as `THIS_ONE` -- is read as `THIS_ONE`, so one old tap is held back
    exactly like a new one. A widened row always carries `this_activity_type`, never `None`, and a
    legacy row with two agreeing observations generalises as before.
    """
    scope = _effective_scope(observation)
    if scope is None or scope not in _ITEM_LEVEL_SCOPES:
        return False
    folded = observation.positive_evidence + observation.negative_evidence
    return folded < _GENERALISE_AFTER_OBSERVATIONS


# What one tier wins: a whole axis, or one value on it. See `_resolution_group`.
ResolutionGroup = tuple[PreferenceDimension, str | None]

# The resolution groups of DISTANCE beliefs that carry no pivot, by which way they lean. Not
# stored values. See `_resolution_group`.
_UNPIVOTED_NEAR: Final[str] = "unpivoted_near"
_UNPIVOTED_FAR: Final[str] = "unpivoted_far"


def _leans_near(value: str | None, *, likes: bool) -> bool:
    """Whether a DISTANCE belief with no number asks for less travel: "near" liked, or "far"
    avoided. The other two readings -- "far" liked, "near" avoided -- ask for more."""
    return (value == "near" and likes) or (value == "far" and not likes)


def _resolution_group(observation: PreferenceObservation) -> ResolutionGroup:
    """The set of beliefs within which only the highest active tier counts.

    **A whole axis** where the values are genuinely exclusive -- TIMING, ENVIRONMENT and SOCIAL
    (`_MISMATCH_IS_EVIDENCE`: morning is not afternoon, so "no mornings this week" really is an
    answer about the afternoon too) -- and on the ordinal axes, DISTANCE and INTENSITY, where every
    belief is a line on the same scale and the tightest line that wins has to bind the others.

    **One value** on ACTIVITY_TYPE (and the deprecated CATEGORY). There are seventeen kinds of
    thing and saying something about one of them says nothing about another -- the same reason a
    different type is UNKNOWN rather than a mismatch. Resolved per axis, "no walks this week"
    silenced a standing "I like arts and crafts" and every learned "not for me" on anything else,
    for no better reason than that both were about some kind of activity.

    Two beliefs on the *same* value still settle by tier: the higher wins and the lower is shown
    through `contradicted_by`; at equal tiers both win and, leaning opposite ways, cancel.

    **A DISTANCE belief with no pivot** -- a stated "near"/"far", the `less_travel` goal, or a
    legacy learned bucket -- is not a line on the scale, so it must neither silence a learned "too
    far" by outranking it nor be silenced by one: "I prefer somewhere near" and "1.2 km was too
    far" are both true at once, and the tighter of the two binds (`travel_tolerance_m`). It
    resolves in one of two groups by which way it leans. The near-leaning ones ("near" liked,
    "far" avoided, the goal) settle among themselves. The far-leaning ones ("far" liked, "near"
    avoided) sit apart, because they are never read (a statement with no number never widens how
    far is comfortable) -- and a belief that is never read must not silence one that is: a
    temporary "I don't mind going further" would otherwise outrank a standing "somewhere near" and
    lift the cap it sets, which is widening by the back door.
    """
    dimension = observation.dimension
    if dimension is PreferenceDimension.DISTANCE and observation.pivot is None:
        near = _leans_near(observation.value, likes=observation.sentiment != "avoid")
        return (dimension, _UNPIVOTED_NEAR if near else _UNPIVOTED_FAR)
    if dimension in _MISMATCH_IS_EVIDENCE or dimension in ORDINAL_DIMENSIONS:
        return (dimension, None)
    return (dimension, observation.value)


def resolve(
    rows: Sequence[DimensionPreference],
    today: date | None = None,
    run_id: str | None = None,
    *,
    goals: Sequence[ActivityGoal] = (),
) -> list[ResolvedPreference]:
    """Every belief this person actively holds, with its tier applied -- the only thing the ranker
    reads.

    Pure and derived. `rows` are the stored beliefs the repository has already filtered for run
    scope and calendar expiry (`_dimension_rows`); this adds what only a whole-person view can
    decide: which tier wins each axis, which rows have been superseded or retracted, which
    item-level answers have not yet earned the right to generalise, and which lower-tier beliefs
    disagree with the winner and should therefore be *shown* rather than scored.

    One `ResolvedPreference` per active belief, not per axis, so the Privacy screen and the world
    model can still render each row on its own terms. Only a belief whose `tier` equals the
    `winning_tier` of its resolution group (`_resolution_group`: the axis, or one value on
    ACTIVITY_TYPE) contributes to `preference_utility` -- the supersedes-rather-than-averages rule,
    written as data instead of hidden in a scoring loop.
    """
    observations = [observation_for(row, today=today) for row in rows]
    observations.extend(
        observation for goal in goals if (observation := goal_observation(goal)) is not None
    )
    active = [
        observation
        for observation in observations
        if observation.superseded_by is None
        and not (
            observation.expires_on_day is not None
            and today is not None
            and observation.expires_on_day < today
        )
        and not _is_held_back(observation)
        and (observation.positive_evidence + observation.negative_evidence) > 0
    ]
    winning: dict[ResolutionGroup, SourceTier] = {}
    for observation in active:
        group = _resolution_group(observation)
        current = winning.get(group)
        if current is None or observation.source_tier > current:
            winning[group] = observation.source_tier

    resolved: list[ResolvedPreference] = []
    for observation in active:
        strength = derived_strength(observation.positive_evidence, observation.negative_evidence)
        numeric_confidence = derived_confidence(
            observation.positive_evidence, observation.negative_evidence
        )
        tier = observation.source_tier
        # A stated belief's magnitude is not earned one observation at a time: the person said so.
        # Its *confidence* still reads from the evidence, which is why the two are separate.
        if tier in _STATED_TIERS:
            strength = 1.0 if observation.sentiment == "like" else -1.0
        resolved.append(
            ResolvedPreference(
                dimension=observation.dimension,
                value=observation.value,
                pivot=observation.pivot,
                direction=observation.direction,
                sentiment="like" if strength >= 0 else "avoid",
                strength=strength,
                confidence=_fact_confidence(numeric_confidence, tier=tier),
                positive_evidence=observation.positive_evidence,
                negative_evidence=observation.negative_evidence,
                evidence_count=(
                    1
                    if tier in _STATED_TIERS
                    else _evidence_count(
                        observation.positive_evidence, observation.negative_evidence
                    )
                ),
                tier=tier,
                winning_tier=winning[_resolution_group(observation)],
                weight=round(
                    min(1.0, _TIER_BASE_WEIGHT.get(tier, 0.0) * max(numeric_confidence, 0.0)), 3
                ),
                scope=observation.scope,
                expires_on_day=observation.expires_on_day,
                source=observation.source,
                run_id=observation.run_id if observation.run_id is not None else run_id,
                stated_text=observation.stated_text,
                supporting=list(observation.supporting) or [observation.key],
                contradicted_by=_contradicted_by(observation, active, strength),
            )
        )
    return resolved


def _contradicted_by(
    observation: PreferenceObservation,
    active: Sequence[PreferenceObservation],
    strength: float,
) -> list[str]:
    """The other active beliefs on the same `(dimension, value)` that lean the opposite way.

    Shown, never scored: precedence has already settled which one the ranker uses, and the world
    model's job is to make the disagreement visible so the person can settle it themselves. A
    belief that a statement has *consumed* never appears here -- it is superseded, so it is not in
    `active` at all, which is what stops "That's right" manufacturing a contradiction with the
    very row it agreed with.
    """
    if strength == 0:
        return []
    return [
        other.key
        for other in active
        if other is not observation
        and other.dimension is observation.dimension
        and other.value == observation.value
        and (other.sentiment == "like") != (strength > 0)
    ]


# ── Scoring ───────────────────────────────────────────────────────────────────────────────────

# The axes a resolved preference may contribute to `preference_utility`.
#
# DISTANCE is absent because `activity_search.travel_utility` is the only thing that scores
# distance -- the learned ceiling is folded into its tolerance, so scoring it here as well is the
# double count B-F10 found. CATEGORY is absent because it is deprecated: its values are format
# labels, and it is kept only so a belief recorded before the split can still be read and
# forgotten.
UTILITY_DIMENSIONS: Final[frozenset[PreferenceDimension]] = frozenset(
    {
        PreferenceDimension.INTENSITY,
        PreferenceDimension.TIMING,
        PreferenceDimension.SOCIAL,
        PreferenceDimension.ENVIRONMENT,
        PreferenceDimension.ACTIVITY_TYPE,
    }
)

# Axes where a *different* value is real evidence against, because the vocabulary is small enough
# that the alternatives are genuinely exclusive: morning is not afternoon, indoor is not outdoor,
# with people is not on your own.
#
# ACTIVITY_TYPE is deliberately not one of them. There are seventeen kinds of thing, so "not for
# me" on a walk says nothing whatever about tai chi -- counting it as evidence *for* tai chi would
# turn one decline into sixteen endorsements. A non-matching type is UNKNOWN: out of the
# numerator, out of the denominator, and out of the matched-axis count.
_MISMATCH_IS_EVIDENCE: Final[frozenset[PreferenceDimension]] = frozenset(
    {
        PreferenceDimension.INTENSITY,
        PreferenceDimension.TIMING,
        PreferenceDimension.SOCIAL,
        PreferenceDimension.ENVIRONMENT,
    }
)


# Why a comparison came out UNKNOWN. `listing_silent`: the listing does not say what the axis
# needs (no start time, no intensity, surroundings not listed, ...). `mismatch_not_counted`: the
# listing does say, it is not what was believed or asked for, and the rule deliberately counts
# that as neither a match nor a mismatch -- a different kind of activity is no evidence against a
# liked kind (see `_MISMATCH_IS_EVIDENCE`), and "labelled, none of the above" (`OTHER`) is not a
# kind anyone can like or ask for.
UnknownReason = Literal["listing_silent", "mismatch_not_counted"]


def candidate_match_detail(
    preference: ResolvedPreference, candidate: ActivityCandidate
) -> tuple[Tri, UnknownReason | None]:
    """`candidate_matches`, with the reason for an UNKNOWN (`None` for MATCH and MISMATCH).

    The one implementation: `candidate_matches` returns this function's outcome.

    The ordinal axes compare against the `pivot` rather than a label: a belief with
    `direction="lower"` is satisfied by anything strictly below the line the person's own answer
    drew, and contradicted by anything at or above it. "That was too tiring" is not a dislike of
    the word *moderate*; it is a statement about where the line is.
    """
    if preference.dimension is PreferenceDimension.ENVIRONMENT:
        if preference.value is None:
            # Unreachable from stored rows (a row always carries a value); nothing to compare.
            return Tri.UNKNOWN, "listing_silent"
        outcome = environment_compatibility(
            ActivityEnvironment(preference.value), candidate.indoor_outdoor
        )
        return outcome, ("listing_silent" if outcome is Tri.UNKNOWN else None)
    if preference.dimension is PreferenceDimension.INTENSITY and preference.pivot is not None:
        index = intensity_index(candidate.intensity)
        if index is None:
            return Tri.UNKNOWN, "listing_silent"
        if preference.direction == _LOWER:
            return (Tri.MATCH if index < preference.pivot else Tri.MISMATCH), None
        return (Tri.MATCH if index > preference.pivot else Tri.MISMATCH), None
    observed = _candidate_dimension_value(preference.dimension, candidate)
    outcome = compare(observed, preference.value)
    if outcome is Tri.MISMATCH and preference.dimension not in _MISMATCH_IS_EVIDENCE:
        return Tri.UNKNOWN, "mismatch_not_counted"
    if outcome is Tri.UNKNOWN:
        # `OTHER` reads as "not said" to the comparison, but the listing did label itself.
        labelled_other = (
            preference.dimension is PreferenceDimension.ACTIVITY_TYPE
            and candidate.activity_type is ActivityType.OTHER
        )
        return outcome, ("mismatch_not_counted" if labelled_other else "listing_silent")
    return outcome, None


def candidate_matches(preference: ResolvedPreference, candidate: ActivityCandidate) -> Tri:
    """Whether `candidate` satisfies one resolved belief -- MATCH, MISMATCH or UNKNOWN.

    See `candidate_match_detail`, which this reads.
    """
    outcome, _ = candidate_match_detail(preference, candidate)
    return outcome


@dataclass(frozen=True)
class BeliefOutcome:
    """One belief `preference_utility` walked, and what it made of this candidate.

    `contribution` is display-only: the belief's signed share of the utility,
    `strength * m / Sigma |s|`, so an evaluator can see which belief moved the factor. The utility
    itself is still summed in the walk's own order from the raw strengths (never from these
    rounded shares), so reading this detail can never change a score.
    """

    preference: ResolvedPreference
    outcome: Tri
    contribution: float
    unknown_reason: UnknownReason | None = None


@dataclass(frozen=True)
class PreferenceUtilityDetail:
    """`preference_utility`'s result together with the walk that produced it."""

    utility: float
    coverage: float
    matched: int
    # Every belief the walk considered (winning tier, a utility axis, non-zero strength), in the
    # order it was summed. A belief outside that set is not here; see `UTILITY_DIMENSIONS`.
    beliefs: tuple[BeliefOutcome, ...] = ()


def utility_beliefs(resolved: Sequence[ResolvedPreference]) -> list[ResolvedPreference]:
    """The beliefs `preference_utility` walks: winning tier, a utility axis, non-zero strength."""
    return [
        preference
        for preference in resolved
        if preference.tier == preference.winning_tier
        and preference.dimension in UTILITY_DIMENSIONS
        and preference.strength != 0
    ]


def preference_utility_detail(
    candidate: ActivityCandidate,
    resolved: Sequence[ResolvedPreference],
) -> PreferenceUtilityDetail:
    """`preference_utility`, keeping the per-belief outcomes beside the numbers.

    The one implementation: `preference_utility` returns this function's three numbers, so the
    evaluator's per-belief view and the ranker's score are the same walk.
    """
    active = utility_beliefs(resolved)
    if not active:
        return PreferenceUtilityDetail(utility=0.0, coverage=0.0, matched=0)
    numerator = 0.0
    denominator = 0.0
    matched = 0
    judged = 0
    walked: list[tuple[ResolvedPreference, Tri, UnknownReason | None]] = []
    for preference in active:
        outcome, unknown_reason = candidate_match_detail(preference, candidate)
        walked.append((preference, outcome, unknown_reason))
        if outcome is Tri.UNKNOWN:
            continue
        judged += 1
        sign = 1.0 if outcome is Tri.MATCH else -1.0
        if outcome is Tri.MATCH:
            matched += 1
        numerator += preference.strength * sign
        denominator += abs(preference.strength)
    if denominator == 0:
        return PreferenceUtilityDetail(
            utility=0.0,
            coverage=0.0,
            matched=0,
            beliefs=tuple(
                BeliefOutcome(
                    preference=preference,
                    outcome=outcome,
                    contribution=0.0,
                    unknown_reason=unknown_reason,
                )
                for preference, outcome, unknown_reason in walked
            ),
        )
    return PreferenceUtilityDetail(
        utility=round(max(-1.0, min(1.0, numerator / denominator)), 3),
        coverage=round(judged / len(active), 3),
        matched=matched,
        beliefs=tuple(
            BeliefOutcome(
                preference=preference,
                outcome=outcome,
                contribution=(
                    0.0
                    if outcome is Tri.UNKNOWN
                    else preference.strength * (1.0 if outcome is Tri.MATCH else -1.0) / denominator
                ),
                unknown_reason=unknown_reason,
            )
            for preference, outcome, unknown_reason in walked
        ),
    )


def preference_utility(
    candidate: ActivityCandidate,
    resolved: Sequence[ResolvedPreference],
) -> tuple[float, float, int]:
    """`(utility, coverage, matched_axes)` for one candidate against what is known about a person.

    `utility = Sigma s_d * m_d / Sigma |s_d|` over the axes where the winning belief can actually
    be judged, with `m_d` in `{+1 MATCH, -1 MISMATCH, 0 UNKNOWN}`. The denominator is what fixes
    the defect the audits all found from different directions: summing *matched rows only* and
    dividing by their own weights made match-any indistinguishable from match-all, so three of a
    person's own confirmed statements were a constant offset on every listing and changed nothing.

    `coverage` is how much of what is known this listing could be judged on at all, reported
    rather than folded into the score -- a sparsely described listing must not out-score a fully
    described identical one simply by being unanswerable.

    `matched_axes` is the tie-break that keeps UNKNOWN from becoming free. Excluding it from the
    denominator alone would make an unlisted listing score exactly like a confirmed match; at
    equal utility, the candidate that actually matches more of what is known wins.

    The caller is expected to have already removed any axis today's request constrains -- an axis
    the person spoke about today belongs to the filter or to request fit, never to history.

    The walk itself lives in `preference_utility_detail`, which also keeps each belief's outcome
    for the evaluator; this returns its three numbers.
    """
    detail = preference_utility_detail(candidate, resolved)
    return detail.utility, detail.coverage, detail.matched


def travel_beliefs(resolved: Sequence[ResolvedPreference]) -> list[ResolvedPreference]:
    """The DISTANCE beliefs `travel_tolerance_m` reads: winning-tier ordinal lines, and winning
    stated (or goal) beliefs with no number that lean near (`stated_near_beliefs`)."""
    return [
        preference
        for preference in resolved
        if preference.dimension is PreferenceDimension.DISTANCE
        and preference.tier == preference.winning_tier
        and (preference.pivot is not None or _leans_near_as_stated(preference))
    ]


def _leans_near_as_stated(preference: ResolvedPreference) -> bool:
    """A stated, ratified, temporary or goal DISTANCE belief with no pivot that asks for less
    travel: "near" liked, or "far" avoided.

    The other two readings -- "far" liked, "near" avoided -- would *widen* how far is comfortable,
    and a statement with no number never does that: nobody said how much further, and sending
    someone further than their own answers allow on the strength of a word is the one direction
    this axis refuses to move. A learned unpivoted row predates the ordinal axis and has no line
    to read at all.
    """
    if preference.dimension is not PreferenceDimension.DISTANCE or preference.pivot is not None:
        return False
    if preference.tier not in _STATED_TIERS:
        return False
    return _leans_near(preference.value, likes=preference.strength > 0)


def leans_near(preference: ResolvedPreference) -> bool:
    """Whether a DISTANCE belief with no number asks for less travel ("near" liked, "far" avoided),
    whatever its tier. `False` for any other belief."""
    return (
        preference.dimension is PreferenceDimension.DISTANCE
        and preference.pivot is None
        and _leans_near(preference.value, likes=preference.strength > 0)
    )


def stated_near_beliefs(resolved: Sequence[ResolvedPreference]) -> list[ResolvedPreference]:
    """The winning beliefs that cap the comfortable distance at `NEARBY_RADIUS_M`: the one
    definition `travel_tolerance_m` and `travel_tolerance_basis` both read."""
    return [preference for preference in travel_beliefs(resolved) if preference.pivot is None]


def belief_in_effect(preference: ResolvedPreference) -> bool:
    """Whether the ranker actually reads this belief: it wins its resolution group, and -- on
    DISTANCE with no number, where winning is not enough -- it is a stated near-leaning belief
    `travel_tolerance_m` caps the distance with. A far-leaning or learned DISTANCE belief with no
    pivot wins its own group and is still never read, so a screen must not call it in effect."""
    if preference.tier != preference.winning_tier:
        return False
    if preference.dimension is PreferenceDimension.DISTANCE and preference.pivot is None:
        return _leans_near_as_stated(preference)
    return True


def travel_tolerance_m(resolved: Sequence[ResolvedPreference]) -> int:
    """How far this person has said is comfortable, in metres.

    Start from the default; a floor (somewhere further that the person enjoyed getting to) may
    raise it; the tightest active ceiling ("too far" at some distance) then caps it. `min(pivot)`
    over the ceilings, because the tightest thing a person has said is the one that binds -- an
    average or an exponentially-smoothed estimate would be a tuning constant with no evaluation
    behind it, and would let one convenient outing quietly undo three "too far"s.

    A ceiling always beats a floor, and a ceiling only ever *narrows*. "1.2 km was too far" is a
    complaint about 1.2 km, not a discovery that everything nearer is free: read as the tolerance
    itself it lifted the default from 500 m to 1.2 km and made a 2 km listing cheaper because the
    person had complained. Enjoying somewhere further away says that trip was fine; it is not
    permission to go further still, and it must never raise a limit the person stated.

    Last, a stated "somewhere near" with no number (or the `less_travel` goal) caps it at
    `NEARBY_RADIUS_M` -- the same "near" a request for "somewhere near me" asks for. Like every
    other step after the floor, it only narrows: under a learned 650 m "too far" it changes
    nothing, and over a 2 km floor it brings the line back to 1 km. A stated "far" never raises it.
    """
    active = travel_beliefs(resolved)
    floors = [p.pivot for p in active if p.direction == _HIGHER and p.pivot is not None]
    tolerance = DEFAULT_TRAVEL_TOLERANCE_M
    if floors:
        tolerance = max(tolerance, int(max(floors)))
    ceilings = [p.pivot for p in active if p.direction == _LOWER and p.pivot is not None]
    if ceilings:
        tolerance = min(tolerance, int(min(ceilings)))
    if stated_near_beliefs(resolved):
        tolerance = min(tolerance, NEARBY_RADIUS_M)
    return max(1, tolerance)


TravelToleranceBasis = Literal["default", "learned_ceiling", "learned_floor", "stated_near"]


def travel_tolerance_basis(resolved: Sequence[ResolvedPreference]) -> TravelToleranceBasis:
    """What set `travel_tolerance_m`: the default, a learned floor that raised it, a learned
    ceiling that capped it, or a stated "near" that capped it at `NEARBY_RADIUS_M`. Walks exactly
    the same steps, so it can never name a line that did not bind; a line that only equals the
    value it would replace still counts as binding."""
    active = travel_beliefs(resolved)
    tolerance = DEFAULT_TRAVEL_TOLERANCE_M
    basis: TravelToleranceBasis = "default"
    floors = [p.pivot for p in active if p.direction == _HIGHER and p.pivot is not None]
    if floors and int(max(floors)) >= tolerance:
        tolerance, basis = int(max(floors)), "learned_floor"
    ceilings = [p.pivot for p in active if p.direction == _LOWER and p.pivot is not None]
    if ceilings and int(min(ceilings)) <= tolerance:
        tolerance, basis = int(min(ceilings)), "learned_ceiling"
    if stated_near_beliefs(resolved) and tolerance >= NEARBY_RADIUS_M:
        basis = "stated_near"
    return basis


def resolved_preferences(preferences: ActivityPreferences) -> list[ResolvedPreference]:
    """The resolved view of an `ActivityPreferences`, resolving it here when the caller did not.

    The repository resolves once per read and carries the result on the model, so the Privacy
    screen's raw rows and the ranker's resolved beliefs come from the same query and cannot
    disagree. Every other caller -- a test, the evaluation harness's trace replay, a scenario --
    builds the model by hand from `dimensions` alone, and must get the same answer rather than
    silently ranking on nothing.
    """
    return list(preferences.resolved) if preferences.resolved else resolve(preferences.dimensions)


def dimension_score(candidate: ActivityCandidate, preferences: ActivityPreferences) -> float:
    """`preference_utility`'s scalar, for a caller that holds an `ActivityPreferences` and wants
    one number -- the evaluation harness's comparability check, and every existing test of "does
    anything known apply to this listing".

    A score, never a decision: nothing in this return type can express "block" or "allow".
    """
    resolved = resolved_preferences(preferences)
    utility, _, _ = preference_utility(candidate, resolved)
    return utility


def social_shape_score(
    social_shape: SocialPreference | None, preferences: ActivityPreferences
) -> float:
    """The same contribution as `preference_utility`, restricted to the SOCIAL axis and keyed off
    a known `social_shape` rather than a full `ActivityCandidate`.

    Exists for outreach candidates (`sql_repository.InterventionCandidate`): a gentle nudge is not
    an `ActivityCandidate`, but it does carry a real `social_shape`. This lets the SOCIAL
    preferences the activity surface already taught also reorder which piece of outreach is
    offered first, without duplicating the weighting rules.

    **Bounded to [-1, 1], structurally.** It is `preference_utility`'s own arithmetic restricted
    to one axis -- `s * m / |s|` -- and `s` is `ResolvedPreference.strength`, a Pydantic
    `Field(ge=-1, le=1)`. ADR 0005's argument that a social nudge cannot outvote a single real
    acceptance rests on exactly that, so the bound comes from the type rather than from
    arithmetic nobody re-checks.

    A listing whose company the person has never confirmed one way or the other, or who has no
    SOCIAL belief at all, scores 0.0 and its position is decided entirely by the per-candidate
    posterior, unchanged.
    """
    if social_shape is None or social_shape is SocialPreference.EITHER:
        return 0.0
    for preference in resolved_preferences(preferences):
        if (
            preference.dimension is not PreferenceDimension.SOCIAL
            or preference.tier != preference.winning_tier
            or preference.strength == 0
            or preference.value is None
        ):
            continue
        outcome = compare(social_shape.value, preference.value)
        if outcome is Tri.UNKNOWN:
            continue
        sign = 1.0 if outcome is Tri.MATCH else -1.0
        return round(preference.strength * sign / abs(preference.strength), 3)
    return 0.0


# ── Folding an answer in ──────────────────────────────────────────────────────────────────────


def _fold(
    existing: list[DimensionPreference],
    *,
    dimension: PreferenceDimension,
    value: str,
    source: Literal["senior_statement", "decline_reason", "inferred"],
    positive: float = 0.0,
    negative: float = 0.0,
    pivot: float | None = None,
    direction: Literal["lower", "higher"] | None = None,
    scope: ClarificationScope | None = None,
    origin_id: str | None = None,
    now: datetime,
    series: str | None = None,
    origin_series: Mapping[str, str] | None = None,
) -> list[DimensionPreference]:
    """Add one observation's evidence to the belief it is about, returning a new list.

    Accumulating counts rather than overwriting a magnitude is what makes learning
    order-independent. An ordinal pivot moves to the tighter of the two: the narrowest thing a
    person has said is the one that binds.

    A row the person retracted or a statement consumed (`superseded_by`) is restarted from
    nothing rather than continued -- the belief they erased does not come back with its old count
    attached.

    **A repeat item-level answer about the same programme is not more evidence.** When the new
    answer is item-level (`THIS_ONE`, `THIS_SLOT`) and the row's latest origin was about the same
    programme (`origin_series[row.origin_id] == series`), nothing changes -- whatever the row's
    scope or how much evidence it already holds. Turning the same class down again on another day,
    or at a sibling session, is still one opinion about that class: counted as agreement it would
    widen a held-back row into a standing dislike of every class of that kind or every slot of
    that time, and on a belief that has already generalised it would push it toward
    `STRONG_LEARNED` on repeats of one opinion. The listing's own cooldown already holds the
    programme back. A widening chip is not item-level, so it still widens at once and adds its
    evidence.

    A bounded approximation: a row stores only its *latest* origin, so the comparison is against
    that one programme alone. Alternating programmes -- river walk, park walk, river walk -- still
    count three times, because by the third answer the row remembers only the park walk. Holding
    every origin would need a per-row origin set (a schema change); the common case, the same
    programme answered twice in a row, is the one this closes.

    `series` is the programme of the listing this answer is about (`activity_search.series_key`);
    `origin_series` maps origin ids to the programme each was about. With no `series`, or when the
    row's origin is not in `origin_series` (a legacy row with no `origin_id`, or an origin the
    caller could not trace), the answer folds as it always did -- a guard that cannot tell the two
    apart must not guess that they match.
    """
    updated = list(existing)
    for index, preference in enumerate(updated):
        if (
            preference.dimension is not dimension
            or preference.value != value
            or preference.source != source
        ):
            continue
        # One origin, one observation: a browser retry or a stuck button is still one thing the
        # person did, and the read side (`_activity_engagement`) keeps the same rule.
        if origin_id is not None and preference.origin_id == origin_id:
            return updated
        restarting = preference.superseded_by is not None
        if (
            series is not None
            and scope in _ITEM_LEVEL_SCOPES
            and not restarting
            and preference.origin_id is not None
            and (origin_series or {}).get(preference.origin_id) == series
        ):
            return updated
        positive_total = (0.0 if restarting else preference.positive_evidence) + positive
        negative_total = (0.0 if restarting else preference.negative_evidence) + negative
        merged_pivot = pivot
        if pivot is not None and preference.pivot is not None and not restarting:
            merged_pivot = (
                min(pivot, preference.pivot)
                if direction == _LOWER
                else max(pivot, preference.pivot)
            )
        updated[index] = preference.model_copy(
            update={
                "positive_evidence": positive_total,
                "negative_evidence": negative_total,
                "strength": derived_strength(positive_total, negative_total),
                "observations": _evidence_count(positive_total, negative_total),
                "pivot": merged_pivot if merged_pivot is not None else preference.pivot,
                "direction": direction or preference.direction,
                # A clarified answer widens a belief that was item-level; an unclarified one
                # never narrows a belief a chip already widened.
                "scope": scope if preference.scope in _ITEM_LEVEL_SCOPES else preference.scope,
                "origin_id": origin_id or preference.origin_id,
                "superseded_by": None,
                "updated_at": now,
            }
        )
        return updated

    updated.append(
        DimensionPreference(
            dimension=dimension,
            value=value,
            strength=derived_strength(positive, negative),
            source=source,
            confirmed=False,
            observations=_evidence_count(positive, negative),
            updated_at=now,
            positive_evidence=positive,
            negative_evidence=negative,
            pivot=pivot,
            direction=direction,
            scope=scope,
            origin_id=origin_id,
        )
    )
    return updated


def apply_decline(
    existing: list[DimensionPreference],
    reason: DeclineReason | None,
    candidate: ActivityCandidate | None,
    now: datetime,
    *,
    clarification: ClarificationScope | None = None,
    origin_id: str | None = None,
    series: str | None = None,
    origin_series: Mapping[str, str] | None = None,
) -> list[DimensionPreference]:
    """Fold one decline's reason into `existing`, returning a new list.

    Never mutates `existing` in place, and never touches the per-candidate posterior in
    `learning.py` -- see the module docstring for why that is not double-counting.

    Moves nothing when `reason` is `None` (always skippable, never inferred), when the reason maps
    to no dimension (`BAD_DAY`, `ALREADY_ACTIVE`, `PREFER_SOMETHING_ELSE`), when there is no
    candidate to ground it in, or -- and this is the part that changed -- **when the listing does
    not carry the fact the axis needs**. There are no contextual fallbacks left: a "too far" on a
    listing with no distance and a "too tiring" on a listing with no intensity both record
    nothing, because the alternative is storing a belief about a person that nobody, including
    them, ever asserted.

    What is recorded is not always resolved yet. An unclarified "bad timing" (`THIS_SLOT`) or
    "not for me" (`THIS_ONE`) is item-level and held back until a second agreeing answer about a
    different programme (`_is_held_back`, `_fold`); a `time_of_day`/`weekday` or
    `this_activity_type` chip widens it at once; `this_one`/`this_venue`/`this_format` on a "not
    for me" record nothing at all. "Too far" and "too tiring" write their ceiling immediately.

    `series` is `activity_search.series_key(candidate)` and `origin_series` maps the origin ids
    stored rows name to the programme each was about; see `_fold` for the one rule that reads
    them. Both are optional, and leaving them out folds exactly as before.
    """
    if reason is None or candidate is None:
        return list(existing)

    dimension = DECLINE_REASON_DIMENSIONS.get(reason)
    if dimension is None:
        return list(existing)

    if dimension is PreferenceDimension.DISTANCE:
        if candidate.distance_m is None:
            return list(existing)
        # A ceiling, not a bucket: "this far was too far" is a statement about wanting something
        # closer, which is a *like* of everything under the line and says nothing at all about
        # the listings beyond it.
        return _fold(
            existing,
            dimension=dimension,
            value=_LOWER,
            source=DECLINE_SOURCE,
            positive=_DECLINE_EVIDENCE,
            pivot=float(candidate.distance_m),
            direction=_LOWER,
            origin_id=origin_id,
            now=now,
        )

    if dimension is PreferenceDimension.INTENSITY:
        index = intensity_index(candidate.intensity)
        if index is None:
            return list(existing)
        return _fold(
            existing,
            dimension=dimension,
            value=_LOWER,
            source=DECLINE_SOURCE,
            positive=_DECLINE_EVIDENCE,
            pivot=float(index),
            direction=_LOWER,
            origin_id=origin_id,
            now=now,
        )

    if dimension is PreferenceDimension.TIMING:
        value = _timing_bucket(candidate.start_at)
        if value is None:
            return list(existing)
        # Unclarified, this is about the session in front of them. `THIS_SLOT` and `THIS_ONE` say
        # so outright; `TIME_OF_DAY` and `WEEKDAY` are the person widening it themselves.
        scope = (
            clarification
            if clarification in (ClarificationScope.TIME_OF_DAY, ClarificationScope.WEEKDAY)
            else ClarificationScope.THIS_SLOT
        )
        return _fold(
            existing,
            dimension=dimension,
            value=value,
            source=DECLINE_SOURCE,
            negative=_DECLINE_EVIDENCE,
            scope=scope,
            origin_id=origin_id,
            now=now,
            series=series,
            origin_series=origin_series,
        )

    if dimension is PreferenceDimension.ACTIVITY_TYPE:
        if clarification in _ITEM_LEVEL_SCOPES:
            # "Just this one" is a statement about this listing, and the cooldown already holds
            # it back. Nothing about a kind of activity was said.
            return list(existing)
        value = _candidate_dimension_value(dimension, candidate)
        if value is None:
            # The listing does not say what it is. "Not for me" then asserts nothing that
            # transfers, and a placeholder would collide with every other unlabelled activity.
            return list(existing)
        # Unclarified, one "not for me" is about the listing in front of the person -- the
        # cooldown already holds it back -- so it is recorded `THIS_ONE` and held back from the
        # resolved set until a second agreeing answer, about a different programme, arrives
        # (`_fold`). It used to resolve at once, which
        # made one tap on a walk a standing dislike of every walk: exactly the reading the
        # timing branch above refuses. `THIS_ACTIVITY_TYPE` is the person widening it themselves.
        # A chip from the other question (`time_of_day`, `weekday`) says nothing about kinds of
        # activity, so it widens nothing here either.
        scope = (
            ClarificationScope.THIS_ACTIVITY_TYPE
            if clarification is ClarificationScope.THIS_ACTIVITY_TYPE
            else ClarificationScope.THIS_ONE
        )
        return _fold(
            existing,
            dimension=dimension,
            value=value,
            source=DECLINE_SOURCE,
            negative=_DECLINE_EVIDENCE,
            scope=scope,
            origin_id=origin_id,
            now=now,
            series=series,
            origin_series=origin_series,
        )

    return list(existing)


def apply_enjoyment(
    existing: list[DimensionPreference],
    enjoyment: Enjoyment,
    liked: list[LikedAspect],
    candidate: ActivityCandidate | None,
    now: datetime,
    *,
    origin_id: str | None = None,
) -> list[DimensionPreference]:
    """Fold one enjoyment report's liked aspects into `existing`, returning a new list.

    Never mutates `existing` in place. Moves nothing when `liked` is empty or `candidate` is
    `None`: a verdict with nothing named, or nothing to ground a value in, teaches no dimension.

    `Enjoyment.OKAY` contributes a fraction of an observation rather than a capped magnitude. "It
    was fine" is not an endorsement, and the difference between the two now survives being
    reported in either order -- a capped magnitude that *overwrote* meant "okay" after "enjoyed"
    erased the endorsement while the reverse kept it.

    `NOT_FOR_ME` still folds a named liked aspect at full weight: a person can dislike an activity
    overall and still say plainly what one thing about it worked, and that remains real evidence
    about that one thing. Whether the outing was any good is scored per listing
    (`ActivityEngagement.not_enjoyed`), not here.
    """
    if candidate is None or not liked:
        return list(existing)

    positive = _OKAY_EVIDENCE if enjoyment is Enjoyment.OKAY else _ENJOYED_EVIDENCE
    updated = list(existing)
    for aspect in liked:
        dimension = LIKED_ASPECT_DIMENSIONS[aspect]
        if dimension is PreferenceDimension.DISTANCE:
            if candidate.distance_m is None:
                continue
            # A floor, not a ceiling, and never one that raises a stated limit: enjoying a trip
            # this far says it was fine, not that further would be.
            updated = _fold(
                updated,
                dimension=dimension,
                value=_HIGHER,
                source=_ENJOYMENT_SOURCE,
                positive=positive,
                pivot=float(candidate.distance_m),
                direction=_HIGHER,
                origin_id=origin_id,
                now=now,
            )
            continue
        value = _candidate_dimension_value(dimension, candidate)
        if value is None:
            # No fallback anywhere, including SOCIAL. "The people" is evidence about company only
            # when the listing actually says what its company is; asserting `social` regardless
            # is how someone was told Care+ had learned they prefer activities with other
            # people from a listing that never said whether it had any.
            continue
        updated = _fold(
            updated,
            dimension=dimension,
            value=value,
            source=_ENJOYMENT_SOURCE,
            positive=positive,
            origin_id=origin_id,
            now=now,
        )
    return updated


def describe_preference(preference: DimensionPreference) -> str:
    """One plain sentence for the coordinator-facing description of a learned belief.

    Describes what is known and how confidently; never implies a decision was made because of it.
    An ordinal belief is described as the line it actually is ("prefers closer than about 1.2 km"),
    never as a bucket -- the bucket wording is what made a stated distance read back as its own
    opposite.
    """
    label = _DIMENSION_LABELS.get(preference.dimension, preference.dimension.value)
    if preference.pivot is not None and preference.direction is not None:
        stance = _ordinal_stance(preference.dimension, preference.pivot, preference.direction)
    elif preference.strength > 0.15:
        stance = f'tends to prefer "{preference.value}"'
    elif preference.strength < -0.15:
        stance = f'tends to avoid "{preference.value}"'
    else:
        stance = f'has shown no strong pattern around "{preference.value}"'

    if preference.confirmed:
        confidence = "confirmed"
    elif preference.source == SENIOR_STATEMENT_SOURCE:
        confidence = "in their own words"
    elif preference.observations <= 1:
        confidence = "based on one observation so far"
    else:
        confidence = f"based on {preference.observations} observations"

    return f"For {label}, this person {stance} ({confidence})."


def _ordinal_stance(dimension: PreferenceDimension, pivot: float, direction: str) -> str:
    if dimension is PreferenceDimension.DISTANCE:
        distance = f"{pivot / 1000:g} km" if pivot >= 1000 else f"{pivot:.0f} m"
        return (
            f"tends to prefer something closer than about {distance}"
            if direction == _LOWER
            else f"has been fine with about {distance}"
        )
    if dimension is PreferenceDimension.INTENSITY:
        index = int(pivot)
        if direction == _LOWER:
            if index <= 0:
                return "tends to prefer the gentlest option available"
            return f"tends to prefer something gentler than {INTENSITY_LADDER[index].value}"
        return f"has been fine with {INTENSITY_LADDER[min(index, len(INTENSITY_LADDER) - 1)].value}"
    return f"has a preference around {pivot:g}"


def activity_type_label(value: str) -> str:
    """The reader-facing name for a stored ACTIVITY_TYPE value, or the value itself when it is not
    one the ontology knows -- a row from before the enum closed must still render as *something*
    rather than crashing the screen that exists to let a person delete it."""
    try:
        return ACTIVITY_TYPE_LABEL[ActivityType(value)]
    except ValueError:
        return value
