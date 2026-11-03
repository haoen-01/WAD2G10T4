"""The user-initiated loop's deterministic core: filter, then rank, then explain.

This module never talks to a model, a database or the network. That is the point of it: F27
("retrieve -> deterministic filter -> bounded LLM rank") only has a safety story if the filter
step cannot be skipped, argued around or reached before it runs. Everything here is pure and
total over its inputs, which is also what makes it directly unit-testable and what lets
`agent.planner`'s bounded ranking loop treat this module's output as the allow-list a guardrail
enforces rather than as a suggestion.

Three responsibilities, three functions:

  * `filter_candidates` removes anything the person's own request rules out -- too far, on the
    wrong day, at the wrong time, in the wrong setting, full, or not offered in a language they
    asked for -- and returns a `FilterOutcome` for every removal. That record is the only
    evidence of what a ranker (deterministic or bounded-LLM) never got to see; without it "the
    agent chose well" is unfalsifiable, because the interesting failure mode is always something
    excluded before anyone looked at it.
  * `reasons_for` explains one candidate against one request: at most three lines, each grounded
    in a field that is actually populated. An `UNKNOWN` or unset field never becomes a claim --
    the same discipline the (since removed) keyword parser applied to `unparsed_terms`, applied
    here to catalogue data instead of free text.
  * `rank_candidates` orders what survived the filter, from six named, bounded factors
    (`RANKING_WEIGHTS`). The invariant it keeps with the card: **every positive contribution to
    the order is a shown reason** -- an intent match, a learned like, today's weather, the
    person's own history -- and a demotion (distance, a learned dislike, a recent "not for me")
    is recorded in the breakdown only, because a penalty is not a reason something suits someone.
    The breakdown itself (`ScoreBreakdown`) is returned beside the order for evaluators, never
    inside the senior's own payload.

F35 -- context on the action side -- is threaded through as one optional, defaulted keyword on
`rank_candidates` (`rain_forecast`) rather than a new positional parameter, so the three call
signatures a parallel data-layer change was written against stay exactly as specified. Rain does
not filter anything here (a request for something outdoors is still honoured if that is what was
asked); it only nudges the order, and only when the person left the environment open, and it is
always disclosed as a `CONTEXT`-basis reason rather than folded silently into the score.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal, Protocol

from silverloop.local_time import local_date, local_hour
from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    ActivityOfferResponse,
    ActivityPreferences,
    ActivityReason,
    Enjoyment,
    FilterOutcome,
    IndoorOutdoor,
    PlannedFollowThrough,
    PreferenceDimension,
    RankedActivity,
    ReasonBasis,
    ResolvedPreference,
    ScoreBreakdown,
    ScoreFactor,
    SocialPreference,
    SourceTier,
    TimeWindow,
)
from silverloop.ontology import ACTIVITY_TYPE_LABEL, ActivityType
from silverloop.preferences import (
    INTENSITY_LADDER,
    PreferenceUtilityDetail,
    TravelToleranceBasis,
    Tri,
    UnknownReason,
    activity_type_label,
    candidate_matches,
    covered,
    environment_compatibility,
    preference_utility_detail,
    resolved_preferences,
    travel_tolerance_basis,
    travel_tolerance_m,
)

# At most this many "why this fits you" lines per candidate -- the contract already says so in
# `models.RankedActivity`'s comment; enforced here, once, at the source.
_MAX_REASONS: Final[int] = 3

# What an environment ask accepts lives in `preferences.environment_compatibility`, imported
# above -- one definition shared by this filter, the preference reader, the rain nudge and the
# evaluation harness. Three copies used to coexist and disagree about whether "sheltered" counted
# as indoors, so a listing could be filtered in on one reading and scored out on another.

_ENVIRONMENT_LABEL: Final[dict[IndoorOutdoor, str]] = {
    IndoorOutdoor.INDOOR: "Indoors",
    IndoorOutdoor.OUTDOOR: "Outdoors",
    IndoorOutdoor.SHELTERED: "Sheltered",
}

_INTENSITY_LABEL: Final[dict[ActivityIntensity, str]] = {
    ActivityIntensity.LIGHT: "Gentle",
    ActivityIntensity.MODERATE: "More active",
}

# Sort key for a candidate with no known distance: last among distance ties, never first. An
# unknown distance must never look like the closest option.
_UNKNOWN_DISTANCE_SORT: Final[float] = float("inf")
# ... and a session with no start time sorts after every dated session of equal score.
_UNKNOWN_START_SORT: Final[float] = float("inf")

# The named factors behind the deterministic order, and how much each may move it. Every factor
# is bounded to [-1, 1] before weighting, so a weight is also the most that factor can ever
# contribute -- which is what makes the table readable as a statement of priorities:
#
#   intent      what the person asked for today. Dominant: a full match outweighs preference,
#               engagement, context and friction combined, so nothing learned or inferred can
#               override a stated request. Only `repetition` -- the person's own recent "not for
#               me" on that exact listing -- is allowed to hold a matching option back.
#   preference  what has been learned about the KIND of thing they like or avoid
#               (`preferences.preference_utility`, signed -- a learned dislike demotes). An axis
#               the request constrained today contributes nothing here: it belongs to the filter
#               or to `intent`, and scoring it twice is the double count B-F10 found.
#   engagement  their own recorded responses to this *series*: interested, went, enjoyed count
#               for it; "not for me" and "went and did not enjoy it" count against it.
#   repetition  a "not for me" inside `DECLINE_COOLDOWN_DAYS` -- do not keep offering it.
#   context     today's weather, only when the person left the environment open.
#   friction    `travel_utility`: how far away it is, measured against the distance this person's
#               own answers say is comfortable, narrowed to the radius a "close by" asked for
#               today. The ONLY place distance is scored.
#
# The senior sees at most three positive, grounded reasons; this table is what the evaluator
# sees (`ScoreBreakdown`). The two never disagree about what is a reason -- a card lists why
# something suits someone, and a penalty is not that.
RANKING_WEIGHTS: Final[dict[str, float]] = {
    "intent": 7.0,
    "preference": 2.0,
    "engagement": 1.5,
    "repetition": 2.0,
    "context": 1.5,
    "friction": 1.0,
}

# What each factor measures, in one plain sentence an evaluator can read beside its weight. Keys
# are exactly `RANKING_WEIGHTS`'s, so no second wording of a factor can drift from this one.
RANKING_FACTOR_DESCRIPTIONS: Final[dict[str, str]] = {
    "intent": (
        "How much of what the person asked for today this listing is known to match; never "
        "negative. A listing that says nothing about what was asked earns nothing here, but is "
        "not ranked below one that contradicts the request."
    ),
    "preference": (
        "Whether the kinds of activity the person has said or shown they like or avoid fit this "
        "listing; positive where it fits, negative where it goes against them."
    ),
    "engagement": (
        "The person's own past answers about this programme: interest, going and enjoying it "
        "raise it, and an older not-for-me or a visit they did not enjoy lowers it."
    ),
    "repetition": (
        "Holds a listing back for two weeks after the person said not for me to it; zero or "
        "negative, never positive."
    ),
    "context": (
        "Today's weather, only when the person left indoors or outdoors open: rain lifts covered "
        "listings and lowers outdoor ones."
    ),
    "friction": (
        "How far beyond a comfortable distance this listing is; zero within it and increasingly "
        "negative beyond it, never positive."
    ),
}

# How much each of the person's own recorded answers moves the `engagement` factor, before it is
# clamped to [-1, 1]. `attended` is `went` less the visits they did not enjoy; `durable_not_for_me`
# is a "not for me" whose cooldown has lapsed (inside it, `repetition` carries the cost instead).
ENGAGEMENT_WEIGHTS: Final[dict[str, float]] = {
    "interested": 0.25,
    "attended": 0.35,
    "enjoyed": 0.4,
    "durable_not_for_me": 0.5,
    "not_enjoyed": 0.5,
}

# How fast travel cost grows once a trip passes what this person finds comfortable. 4.5 km is a
# bus each way, so `travel_utility` reaches its floor about that far beyond their own tolerance.
#
# One fixed scale, deliberately. Normalising the slope by the person's own ceiling -- the obvious
# alternative -- punishes someone with a 500 m limit ten times harder per metre than someone with
# a 5 km one, which is a statement about their mobility that no evidence here supports.
_TRAVEL_SCALE_M: Final[int] = 4_500

# After a "not for me", how many days the same listing stays demoted regardless of how well it
# scores otherwise. A person who has just said no should not see the same card again tomorrow
# because it is still, on paper, the best fit. Two weeks, then it may come back -- reversibly,
# and its position still carries the accumulated "not for me" count on the engagement factor.
DECLINE_COOLDOWN_DAYS: Final[int] = 14

# How close (in weighted score) a candidate of a different kind must be to the third-ranked one
# for the diversity pass to swap it in. Half a friction unit -- roughly an extra 2 km on an
# otherwise identical fit. A margin, not a licence: nothing further away than this is ever
# promoted, so variety never overrides a clearly better fit.
DIVERSITY_SCORE_MARGIN: Final[float] = 0.5
_DIVERSITY_TOP_N: Final[int] = 3
# How many top places the series dedupe and the variety swap protect -- the cards shown first.
DIVERSITY_TOP_N: Final[int] = _DIVERSITY_TOP_N


def _time_window_for_hour(hour: int) -> TimeWindow:
    """Bucket a clock hour into a time window: <12 morning, <17 afternoon, else evening -- the
    same boundaries a typed time was bucketed by when requests were still parsed from text.
    """
    if hour < 12:
        return TimeWindow.MORNING
    if hour < 17:
        return TimeWindow.AFTERNOON
    return TimeWindow.EVENING


def _format_distance(distance_m: int) -> str:
    if distance_m >= 1000:
        return f"{distance_m / 1000:g} km"
    return f"{distance_m} m"


# ── Filter ─────────────────────────────────────────────────────────────────────────────────────
#
# Ten rules, checked in a fixed order, first match wins. A candidate is removed for exactly one
# reason even when several would apply, mirroring `policy.py`'s single-pass ladder: the record
# should say the one thing that actually decided it, not everything that happened to be true.
#
# The rule that decides whether something belongs here at all: a hard rule exists only where a
# mismatch is a barrier the person cannot cross -- a distance they gave as a number, a day, a
# time window, an environment, company, capacity, language -- or where they explicitly excluded
# something. Everything else is soft and belongs to the ranker. `activity_types` is the case
# worth naming: asking *for* a walk ranks walks first and hides nothing, while asking *not* to be
# shown walking is an exclusion and does.
#
# Every rule shares one discipline: a field the catalogue has not populated can never be the
# reason something is excluded. Absence of information narrows nothing here, exactly as it
# narrows nothing in the keyword intent parser -- the failure mode of showing too much is always
# preferred to the failure mode of silently hiding the one option a person actually wanted.


def _excluded_activity_type(
    candidate: ActivityCandidate, intent: ActivityIntent, today: date
) -> str | None:
    """Remove a kind of activity the person ruled out.

    The one place `activity_types` has a hard edge, and only in the negative direction. Asking
    *for* a walk never hides anything -- the catalogue is fourteen programmes and a content
    filter would turn most requests into "nothing matched" -- but "no walking, my knee" is a
    statement about a person's body, and showing them a walk anyway is the harmful error.

    `OTHER` never matches: it means "labelled, and none of the above", so it cannot be the thing
    that was ruled out. An unlabelled listing (`None`) is not excluded either -- absence of
    information narrows nothing here, exactly as it narrows nothing anywhere else in this file.
    """
    if not intent.excluded_activity_types or candidate.activity_type is None:
        return None
    if candidate.activity_type is ActivityType.OTHER:
        return None
    if candidate.activity_type not in intent.excluded_activity_types:
        return None
    return f"{ACTIVITY_TYPE_LABEL[candidate.activity_type]}, which you asked not to be shown."


def _excluded_environment(
    candidate: ActivityCandidate, intent: ActivityIntent, today: date
) -> str | None:
    if not intent.excluded_environments or candidate.indoor_outdoor is IndoorOutdoor.UNKNOWN:
        return None
    if candidate.indoor_outdoor not in intent.excluded_environments:
        return None
    return f"{candidate.indoor_outdoor.value.capitalize()}, which you asked not to be shown."


def _excluded_social(
    candidate: ActivityCandidate, intent: ActivityIntent, today: date
) -> str | None:
    """Silent on `None`, like `_wrong_company`: a listing that does not say is not a listing that
    says the wrong thing."""
    if not intent.excluded_social or candidate.social_shape is None:
        return None
    if candidate.social_shape not in intent.excluded_social:
        return None
    if candidate.social_shape is SocialPreference.SOCIAL:
        return "A group activity; you asked not to be shown those."
    return "A self-guided activity; you asked not to be shown those."


def _too_far(candidate: ActivityCandidate, intent: ActivityIntent, today: date) -> str | None:
    """Only a distance the person gave as a *number* is a barrier.

    "Near me" and "close by" mean something, and the ranker uses the figure they imply -- but
    read as a hard 1 km cut-off they removed half the catalogue, the 1.2 km sheltered walk
    included, from someone who never named a limit at all. `distance_is_explicit` is the
    difference between a limit and a preference, and only a limit filters. The preference is not
    free either: `_soft_radius_m` hands the implied figure to `travel_utility`, which charges the
    gap from there instead of from a tolerance today's request never mentioned.
    """
    if not intent.distance_is_explicit:
        return None
    if intent.max_distance_m is None or candidate.distance_m is None:
        return None
    if candidate.distance_m <= intent.max_distance_m:
        return None
    return (
        f"{_format_distance(candidate.distance_m)} away; you asked for "
        f"{_format_distance(intent.max_distance_m)} or less."
    )


def _wrong_day(candidate: ActivityCandidate, intent: ActivityIntent, today: date) -> str | None:
    if candidate.start_at is None:
        return None
    candidate_date = local_date(candidate.start_at)
    if intent.on_date is not None:
        if candidate_date == intent.on_date:
            return None
        return f"Runs {candidate_date:%A %d %B}, not {intent.on_date:%A %d %B} as requested."
    # No specific day was asked for, but a listing that has already happened is not a real
    # option regardless -- the "closed" case, checked against `today` rather than the request.
    if candidate_date < today:
        return f"Already ran on {candidate_date:%A %d %B}."
    return None


def _wrong_time_window(
    candidate: ActivityCandidate, intent: ActivityIntent, today: date
) -> str | None:
    if intent.time_window == TimeWindow.ANY or candidate.start_at is None:
        return None
    window = _time_window_for_hour(local_hour(candidate.start_at))
    if window == intent.time_window:
        return None
    return f"Runs in the {window.value}, not the {intent.time_window.value} as requested."


def _wrong_environment(
    candidate: ActivityCandidate, intent: ActivityIntent, today: date
) -> str | None:
    if environment_compatibility(intent.environment, candidate.indoor_outdoor) is not Tri.MISMATCH:
        return None
    return (
        f"{candidate.indoor_outdoor.value.capitalize()}, not {intent.environment.value} "
        "as requested."
    )


def _wrong_company(candidate: ActivityCandidate, intent: ActivityIntent, today: date) -> str | None:
    """Exclude an activity whose company is the opposite of what was asked for.

    Silent on `None`, which means the listing does not say. Someone asking to meet people should
    still be shown an unlabelled session -- it may well be sociable -- but must not be handed one
    the catalogue explicitly calls self-guided. Absent information is not the same as a mismatch,
    and this is the one axis where confusing the two would defeat the point of asking.
    """
    if intent.social_preference == SocialPreference.EITHER:
        return None
    if candidate.social_shape is None:
        return None
    if candidate.social_shape == intent.social_preference:
        return None
    if intent.social_preference == SocialPreference.SOCIAL:
        return "A self-guided activity; you asked for something with other people."
    return "A group activity; you asked for something on your own."


def _full(candidate: ActivityCandidate, intent: ActivityIntent, today: date) -> str | None:
    if candidate.availability != ActivityAvailability.FULL:
        return None
    return "Fully booked."


def _inaccessible(candidate: ActivityCandidate, intent: ActivityIntent, today: date) -> str | None:
    """A person cannot actually take part in something run only in a language they do not use.

    This is the one filter rule that is not about physical reach: a session offered only in a
    language the person does not understand is inaccessible to them in exactly the sense "too
    far" or "full" are -- a real barrier, not a preference to weigh against others. It fires only
    when both sides of the comparison are populated, so a candidate with no `language_tags` (an
    honest "not listed", per F26) is never excluded for something the catalogue never claimed.
    """
    if intent.language is None or not candidate.language_tags:
        return None
    if intent.language in candidate.language_tags:
        return None
    return f"Only offered in {', '.join(candidate.language_tags)}; you asked for {intent.language}."


_RULES: Final[
    tuple[tuple[str, Callable[[ActivityCandidate, ActivityIntent, date], str | None]], ...]
] = (
    # The exclusions come first because they are the most explicit thing the person said, and a
    # `FilterOutcome` records exactly one reason: "you asked not to be shown walks" is a better
    # account of why a listing is missing than "it runs on Tuesday".
    ("excluded_activity_type", _excluded_activity_type),
    ("excluded_environment", _excluded_environment),
    ("excluded_social", _excluded_social),
    ("too_far", _too_far),
    ("wrong_day", _wrong_day),
    ("wrong_time_window", _wrong_time_window),
    ("wrong_environment", _wrong_environment),
    ("wrong_company", _wrong_company),
    ("full", _full),
    ("inaccessible", _inaccessible),
)


# The filter rules' names, in the order they are checked.
FILTER_RULE_NAMES: Final[tuple[str, ...]] = tuple(name for name, _ in _RULES)


def filter_candidates(
    candidates: list[ActivityCandidate], intent: ActivityIntent, *, today: date
) -> tuple[list[ActivityCandidate], list[FilterOutcome]]:
    """Deterministically remove anything the request rules out, before any ranking runs.

    Runs first and always -- this is called before the deterministic ranker and before the
    bounded planning loop in `agent.planner` ever sees a candidate. Nothing downstream, model or
    ranker, can consider an option this function has already removed.
    """
    kept: list[ActivityCandidate] = []
    removed: list[FilterOutcome] = []
    for candidate in candidates:
        for rule_name, check in _RULES:
            detail = check(candidate, intent, today)
            if detail is not None:
                removed.append(
                    FilterOutcome(
                        activity_id=candidate.activity_id,
                        title=candidate.title,
                        rule=rule_name,
                        detail=detail,
                    )
                )
                break
        else:
            kept.append(candidate)
    return kept, removed


# ── Reasons ────────────────────────────────────────────────────────────────────────────────────


# How a line names where a winning stated belief came from. Only a belief the person put into
# words, a goal they chose, or a "that's right" gets one of these; a learned belief keeps its
# "before" wording (`_learned_preference_reason`), because "before" is exactly what it is.
_STATED_REASON_CLAUSE: Final[dict[SourceTier, str]] = {
    SourceTier.STATED: "which you said you like.",
    SourceTier.RATIFIED: "which you said you like.",
    SourceTier.TEMPORARY_STATED: "as you asked for the time being.",
    SourceTier.STATED_GOAL: "which is one of your goals.",
}


def _preference_subject(preference: ResolvedPreference, candidate: ActivityCandidate) -> str | None:
    """What a PREFERENCE line is about, in the card's words: the listing's own value on the
    belief's axis. `None` when there is nothing to name (an intensity with no label, an axis that
    grounds no line)."""
    if preference.dimension is PreferenceDimension.ENVIRONMENT:
        return _ENVIRONMENT_LABEL.get(candidate.indoor_outdoor)
    if preference.dimension is PreferenceDimension.INTENSITY:
        return _INTENSITY_LABEL.get(candidate.intensity)
    if preference.dimension is PreferenceDimension.TIMING:
        return f"Runs in the {_time_window_for_hour(local_hour(candidate.start_at)).value}"
    if preference.dimension is PreferenceDimension.SOCIAL:
        if preference.value == SocialPreference.SOCIAL.value:
            return "With other people"
        return "Something to do on your own"
    if preference.dimension is PreferenceDimension.ACTIVITY_TYPE and preference.value is not None:
        return activity_type_label(preference.value)
    return None


def _learned_preference_reason(preference: ResolvedPreference, subject: str) -> str:
    """A learned belief's line: something the person's own answers showed before."""
    if preference.dimension is PreferenceDimension.ENVIRONMENT:
        return f"{subject}, which you've liked before."
    if preference.dimension is PreferenceDimension.INTENSITY:
        if preference.pivot is not None and preference.direction == "lower":
            # A learned ceiling is a "too tiring" on something harder, not a liking for this.
            return f"{subject}, easier than an activity you found too tiring."
        return f"{subject}, which has suited you before."
    if preference.dimension is PreferenceDimension.TIMING:
        return f"{subject}, a time that's worked for you before."
    if preference.dimension is PreferenceDimension.SOCIAL:
        if preference.value == SocialPreference.SOCIAL.value:
            return f"{subject}, which you've enjoyed before."
        return f"{subject}, which has suited you before."
    return f"{subject}, which you've enjoyed before."


def _preference_reason(preference: ResolvedPreference, candidate: ActivityCandidate) -> str | None:
    """One PREFERENCE-basis line, or `None` when nothing about this candidate grounds it.

    Whether the belief actually applies is decided by `preferences.candidate_matches` -- the same
    helper `preference_utility` scores from -- so a candidate can never be told it matches a
    belief for one purpose (an explanation) and not for another (the score built from that same
    explanation). Only the wording of each line is this function's own.

    Only a positive belief grounds a line. A demotion is not a reason something suits someone, and
    the card's whole contract is that every positive contribution to the order is a shown reason.

    The wording follows the tier that won (`preference.tier`, which equals `winning_tier` here):
    what the person said, asked for for now, or chose as a goal says so, and never "before" --
    telling someone "you've liked that before" about a thing they told us this morning describes
    a history that does not exist. A learned belief keeps its "before" wording.

    DISTANCE grounds no line at all any more: it is scored solely by `travel_utility`, which is
    never positive, so there is nothing owed. Saying "close to home -- you've preferred that
    before" beside a factor that only ever subtracts was describing a reason that did not exist.
    """
    if preference.strength <= 0 or preference.tier != preference.winning_tier:
        return None
    if candidate_matches(preference, candidate) is not Tri.MATCH:
        return None
    subject = _preference_subject(preference, candidate)
    if subject is None:
        return None
    clause = _STATED_REASON_CLAUSE.get(preference.tier)
    if clause is not None:
        return f"{subject}, {clause}"
    return _learned_preference_reason(preference, subject)


def scorable_preferences(
    preferences: ActivityPreferences, intent: ActivityIntent
) -> list[ResolvedPreference]:
    """The beliefs that may score this search -- `_scorable_preferences`, for an evaluator that
    has no scored candidate to read them from."""
    return _scorable_preferences(preferences, intent)


def _scorable_preferences(
    preferences: ActivityPreferences, intent: ActivityIntent
) -> list[ResolvedPreference]:
    """The beliefs that may score this search: the winner on each axis, minus every axis the
    person has spoken about today.

    An axis the request constrains is owned by the hard filter (a day, a time, an environment,
    company, a language, a distance given as a number) or by `intent` (intensity, a kind of
    activity). Scoring it again from history counts the same fact twice and, worse, lets what was
    learned last month argue with what was asked for this morning.
    """
    constrained = constrained_dimensions(intent)
    return [
        preference
        for preference in resolved_preferences(preferences)
        if preference.tier == preference.winning_tier and preference.dimension not in constrained
    ]


def constrained_dimensions(intent: ActivityIntent) -> frozenset[PreferenceDimension]:
    """The preference axes today's request speaks for, which history may therefore not score."""
    return frozenset(
        axis.dimension
        for axis in _INTENT_AXES
        if axis.dimension is not None and axis.constrained(intent)
    )


def _preference_reasons(
    candidate: ActivityCandidate, preferences: ActivityPreferences, intent: ActivityIntent
) -> list[ActivityReason]:
    """One line per learned like this listing confirms, from the belief that actually wins its
    axis -- so a card can never cite something the person's own words have overruled, and never
    cites an axis they constrained today (`_scorable_preferences`)."""
    return [
        ActivityReason(text=text, basis=ReasonBasis.PREFERENCE)
        for preference in _scorable_preferences(preferences, intent)
        if (text := _preference_reason(preference, candidate)) is not None
    ]


def _catalogue_filler(candidate: ActivityCandidate) -> list[ActivityReason]:
    """The line a card carries when nothing else grounds anything: what the listing is, and no
    more. It used to add "near you", which nothing had checked -- the distance could be unknown or
    far past the person's comfortable distance, and friction never earns a line.

    The label is shown as the catalogue gives it. Wrapping it in a sentence ("A ... activity.")
    produced "A group activity activity." for a format label that already names itself, and the
    two catalogues in this repository label by format ("Group class") and by kind ("Tai Chi")."""
    if candidate.category is None:
        return []
    return [
        ActivityReason(
            text=f"{candidate.category.strip()}.",
            basis=ReasonBasis.CATALOGUE,
        )
    ]


# The order reason lines appear on a card, by what grounds them: what the person just asked for,
# then their own history with this listing, then today's weather, then a variety note, then a
# standing preference. A `CATALOGUE` filler is never composed alongside a real reason.
_BASIS_ORDER: Final[dict[ReasonBasis, int]] = {
    ReasonBasis.INTENT: 0,
    ReasonBasis.HISTORY: 1,
    ReasonBasis.CONTEXT: 2,
    ReasonBasis.VARIETY: 3,
    ReasonBasis.PREFERENCE: 4,
    ReasonBasis.CATALOGUE: 5,
}


# The factor whose positive contribution a line of each basis explains. VARIETY and CATALOGUE lines
# explain no factor: VARIETY describes the swap that placed the card, CATALOGUE is the filler.
REASON_BASIS_FACTOR: Final[dict[ReasonBasis, str]] = {
    ReasonBasis.INTENT: "intent",
    ReasonBasis.PREFERENCE: "preference",
    ReasonBasis.HISTORY: "engagement",
    ReasonBasis.CONTEXT: "context",
}


def eligible_reasons(
    reasons: list[ActivityReason], contributions: Mapping[str, float]
) -> list[ActivityReason]:
    """The lines a card may show, in their given order.

    A line explaining a factor is eligible only when that factor contributed positively: a card
    lists why something suits someone, and "You said you were interested in this before." beside
    an engagement factor that is net negative is not that (D15). VARIETY is always eligible. The
    CATALOGUE filler is eligible only when nothing else is -- it is never composed beside a real
    reason, a variety note included.
    """
    real = [
        reason
        for reason in reasons
        if reason.basis is ReasonBasis.VARIETY
        or (
            (factor := REASON_BASIS_FACTOR.get(reason.basis)) is not None
            and contributions.get(factor, 0.0) > 0
        )
    ]
    if real:
        return real
    return [reason for reason in reasons if reason.basis is ReasonBasis.CATALOGUE]


def _compose_reasons(
    reasons: list[ActivityReason], contributions: Mapping[str, float]
) -> tuple[list[ActivityReason], list[ActivityReason]]:
    """Split eligible reason lines into the card's face (at most three) and the rest.

    1. Only `eligible_reasons` compete: a line whose factor did not contribute positively is not a
       reason, and is neither shown nor counted.
    2. A VARIETY line is always kept.
    3. Then one line for each factor-backed basis, the largest positive contribution first (ties
       in `_BASIS_ORDER`) -- so every positive factor gets a line whenever it fits, and a small
       contributor never crowds out a large one (D12).
    4. Free slots take further lines in `_BASIS_ORDER`.
    5. The card displays its lines in `_BASIS_ORDER`.

    Returns `(kept, more)`. `more` is every eligible line the face had no room for, also in
    `_BASIS_ORDER`: with more positive bases than slots the smallest contributor's line moves
    there, and the card shows it when opened (`RankedActivity.more_reasons`). Nothing eligible is
    ever dropped, so `kept + more` is always the whole eligible set and `reasons_suppressed` is
    always `len(more)`.
    """
    eligible = eligible_reasons(reasons, contributions)
    ordered = sorted(eligible, key=lambda reason: _BASIS_ORDER[reason.basis])
    chosen: list[ActivityReason] = [
        reason for reason in ordered if reason.basis is ReasonBasis.VARIETY
    ][:_MAX_REASONS]
    bases = sorted(
        {reason.basis for reason in ordered if reason.basis in REASON_BASIS_FACTOR},
        key=lambda basis: (-contributions[REASON_BASIS_FACTOR[basis]], _BASIS_ORDER[basis]),
    )
    for basis in bases:
        if len(chosen) >= _MAX_REASONS:
            break
        chosen.append(next(reason for reason in ordered if reason.basis is basis))
    for reason in ordered:
        if len(chosen) >= _MAX_REASONS:
            break
        if not any(reason is picked for picked in chosen):
            chosen.append(reason)
    kept = [reason for reason in ordered if any(reason is picked for picked in chosen)]
    more = [reason for reason in ordered if not any(reason is picked for picked in chosen)]
    return kept, more


def reasons_for(
    candidate: ActivityCandidate, intent: ActivityIntent, preferences: ActivityPreferences
) -> list[ActivityReason]:
    """At most three "why this fits you" lines, each traceable to a field that is set.

    The card `score_candidate_detail` composes for this candidate with no rain and no history --
    one composition, never a second one that could disagree with the ranked card. So only
    `INTENT` and `PREFERENCE` lines can appear, or the `CATALOGUE` filler when neither grounds
    anything; `CONTEXT` and `HISTORY` need the forecast and the person's responses, which
    `rank_candidates` is given.

    Which lines appear is decided by `_compose_reasons`: a line only for a factor that contributed
    positively, one line per such factor in order of how much it contributed (so the smaller
    factor is the one moved off the face of a full card, into `more_reasons`), spare slots filled
    in basis order, and the card shown in basis order (`INTENT`, `HISTORY`, `CONTEXT`, `VARIETY`,
    `PREFERENCE`, `CATALOGUE`).
    """
    return score_candidate_detail(candidate, intent, preferences).reasons


# ── Rank ───────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActivityEngagement:
    """A person's own recorded responses to one listing, as counts.

    Assembled by the repository from `activity_responses` -- the senior's taps on a search result
    ("I'm interested" / "Not for me") and what they reported afterwards. Nothing here is inferred:
    every count is something the person did. `last_not_for_me` is the simulated day of the most
    recent "not for me", used only for the repetition cooldown.
    """

    interested: int = 0
    not_for_me: int = 0
    went: int = 0
    did_not_go: int = 0
    enjoyed: int = 0
    # "I went, and it was not for me." There was no field that could hold this, so the strongest
    # thing a person can say about a listing was counted nowhere -- and `went` alone then pushed
    # the card back up with "You went to this one before." printed on it as a reason it suited
    # them. Counted against the listing here, and it silences that line (`_history_reason`).
    not_enjoyed: int = 0
    last_not_for_me: date | None = None
    # The subset of the counts above that *this* listing carries itself, when they were rolled up
    # from the whole programme (`activity_search.engagement_by_series`: a class running Monday,
    # Wednesday and Friday is three listings and one thing to go to, and a cooldown that reaches
    # only Monday's row is a cooldown that reaches nothing). The roll-up is right for ranking and
    # wrong for wording: "You went to this one before." printed on Friday's card, because the
    # person went on Wednesday, is a claim about a session they never attended. `_history_reason`
    # says "this programme" instead when only a sibling session carries the evidence. `None`
    # means the counts are already this listing's own, which is what a caller assembling one
    # listing's responses by hand is describing.
    own: ActivityEngagement | None = None


@dataclass(frozen=True)
class EngagementCounts:
    """Per-session response counts, before they are rolled up to the programme.

    `counts[activity_id]` maps a response name (`interested`, `not_for_me`, `went`, `did_not_go`,
    `enjoyed`, `not_enjoyed`) to how many times it was scored; `last_declined` is the simulated day
    of the most recent "not for me" still standing on that session; `answered` is every session
    the person answered directly from a search card.
    """

    counts: dict[str, dict[str, int]]
    last_declined: dict[str, date]
    answered: set[str]


def count_engagement(
    offers: Iterable[tuple[str, str, date]],
    follow_through: Iterable[tuple[str, str]],
    verdicts: Iterable[tuple[str, str]],
) -> EngagementCounts:
    """Count one person's responses per session, the way the ranker scores them.

    `offers` is `(activity_id, response, recorded_on_day)` for every search-card answer, in the
    order they were recorded; `follow_through` is `(activity_id, planned follow-through)` for every
    report on a planned activity; `verdicts` is `(activity_id, enjoyment)` for every enjoyment
    report. See `sql_repository._activity_engagement` for why each rule exists:

      * one scored response per `(activity_id, response, day)` -- a repeated tap on the same day
        is recorded but counted once;
      * an "interested" after a "not for me" ends that session's cooldown (the most recent word
        wins);
      * a follow-through counts under its own name (`went`, `did_not_go`, `cancelled`);
      * `enjoyed` and `not_for_me` verdicts count as `enjoyed` / `not_enjoyed`; `okay` counts as
        nothing.
    """
    counts: dict[str, dict[str, int]] = {}
    last_declined: dict[str, date] = {}
    answered: set[str] = set()
    scored: set[tuple[str, str, date]] = set()
    for activity_id, response, day in offers:
        bucket = counts.setdefault(activity_id, {})
        answered.add(activity_id)
        if (activity_id, response, day) not in scored:
            scored.add((activity_id, response, day))
            bucket[response] = bucket.get(response, 0) + 1
        if response == ActivityOfferResponse.NOT_FOR_ME.value and (
            activity_id not in last_declined or day > last_declined[activity_id]
        ):
            last_declined[activity_id] = day
        elif response == ActivityOfferResponse.INTERESTED.value:
            last_declined.pop(activity_id, None)
    for activity_id, report in follow_through:
        bucket = counts.setdefault(activity_id, {})
        bucket[report] = bucket.get(report, 0) + 1
    for activity_id, verdict in verdicts:
        bucket = counts.setdefault(activity_id, {})
        if verdict == Enjoyment.ENJOYED.value:
            bucket["enjoyed"] = bucket.get("enjoyed", 0) + 1
        elif verdict == Enjoyment.NOT_FOR_ME.value:
            bucket["not_enjoyed"] = bucket.get("not_enjoyed", 0) + 1
    return EngagementCounts(counts=counts, last_declined=last_declined, answered=answered)


def engagement_from(
    totals: Mapping[str, int],
    *,
    last_not_for_me: date | None = None,
    own: ActivityEngagement | None = None,
) -> ActivityEngagement:
    """One counts bucket as an `ActivityEngagement`, for a series total or a single session."""
    return ActivityEngagement(
        interested=totals.get(ActivityOfferResponse.INTERESTED.value, 0),
        not_for_me=totals.get(ActivityOfferResponse.NOT_FOR_ME.value, 0),
        went=totals.get(PlannedFollowThrough.WENT.value, 0),
        did_not_go=totals.get(PlannedFollowThrough.DID_NOT_GO.value, 0),
        enjoyed=totals.get("enjoyed", 0),
        not_enjoyed=totals.get("not_enjoyed", 0),
        last_not_for_me=last_not_for_me,
        own=own,
    )


class SeriesIdentified(Protocol):
    """Anything with a provider and a title: a catalogue model or its stored row."""

    @property
    def provider(self) -> str: ...

    @property
    def title(self) -> str: ...


def series_identity(listing: SeriesIdentified) -> tuple[str, str]:
    """The one definition of "the same programme": `(provider, title)`, trimmed and case-folded.

    Every place that needs to know whether two sessions are one programme reads this -- the
    series dedupe, the engagement roll-up, `RankedActivity.series_key` and the world model's
    attended-programme facts -- so none of them can disagree about what counts as a repeat.
    """
    return (listing.provider.strip().casefold(), listing.title.strip().casefold())


# Joins the parts of a series key. A control character, so no provider or title can forge a
# collision, and never equal to an activity id (which `engagement_by_series` falls back to).
_SERIES_KEY_SEPARATOR: Final[str] = "\x1f"


def series_key(candidate: SeriesIdentified) -> str:
    """`series_identity` as one opaque string, for maps and payloads: the ranker's series dedupe,
    the engagement roll-up and `RankedActivity.series_key`. Compare for equality only."""
    return _SERIES_KEY_SEPARATOR.join(series_identity(candidate))


def series_keys_for(candidates: Iterable[ActivityCandidate]) -> dict[str, str]:
    """`activity_id -> series_key` for every listing given."""
    return {candidate.activity_id: series_key(candidate) for candidate in candidates}


def engagement_by_series(
    counts: Mapping[str, Mapping[str, int]],
    last_declined: Mapping[str, date],
    answered: set[str],
    series_keys: Mapping[str, str],
) -> dict[str, ActivityEngagement]:
    """Roll per-session counts up to the programme, then hand *every* session of it the total.

    `series_keys` is `activity_id -> series_key` for the catalogue (`series_keys_for`): opaque
    strings from `series_identity`, the one definition of "the same programme", shared with the
    dedupe pass so ranking and learning cannot disagree about what counts as a repeat. A session
    missing from `series_keys` rolls up under its own activity id, which no series key can equal.

    Every session of a touched series gets an entry, including the ones the person has never
    answered directly -- which is the whole point: keyed per session, "not for me" on Monday's
    chair class left Wednesday's and Friday's untouched and the person was shown the identical
    class twice more that week.

    A session the catalogue has no row for -- there is none in practice -- keeps its own counts
    under its own id rather than being dropped.
    """
    if not counts:
        return {}
    touched = {
        activity_id: series_keys[activity_id]
        for activity_id in counts
        if activity_id in series_keys
    }
    series_counts: dict[str, dict[str, int]] = {}
    series_declined: dict[str, date] = {}
    for activity_id, bucket in counts.items():
        key = touched.get(activity_id, activity_id)
        totals = series_counts.setdefault(key, {})
        for name, value in bucket.items():
            totals[name] = totals.get(name, 0) + value
        declined = last_declined.get(activity_id)
        if declined is not None and (key not in series_declined or declined > series_declined[key]):
            series_declined[key] = declined

    series_of: dict[str, str] = dict(touched)
    for activity_id, key in series_keys.items():
        if key in series_counts:
            series_of.setdefault(activity_id, key)
    for activity_id in counts:
        series_of.setdefault(activity_id, activity_id)

    return {
        activity_id: engagement_from(
            totals,
            # The per-session override: a session the person answered themselves is held back by
            # their own most recent word about *it*, not by a sibling session's. An "interested"
            # on Friday is not overruled by Monday's decline.
            last_not_for_me=(
                last_declined.get(activity_id)
                if activity_id in answered
                else series_declined.get(key)
            ),
            # What this session carries by itself, kept beside the roll-up rather than lost in
            # it: the totals decide the ranking, and `_history_reason` needs these to know whether
            # "You went to this one before." is a true sentence about *this* session or a
            # sibling's attendance wearing its card.
            own=engagement_from(counts.get(activity_id) or {}),
        )
        for activity_id, key in series_of.items()
        if (totals := series_counts.get(key)) is not None
    }


def _listing_silent(candidate: ActivityCandidate, intent: ActivityIntent) -> UnknownReason:
    """Every request axis but `activity_type` is UNKNOWN only when the listing leaves the field
    unset; the request side is always set on a constrained axis."""
    return "listing_silent"


@dataclass(frozen=True)
class _RequestAxis:
    """One thing a person can ask for, and the three questions the ranker has about it.

    `constrained` -- did they ask about this at all? `outcome` -- does this listing satisfy it,
    contradict it, or not say? `reason` -- the line to show when it does satisfy it.

    Written as data rather than as three parallel `if` chains because the three used to disagree:
    the reason list was the score's numerator, `_constrained_axes` was its denominator, and each
    had its own copy of what "matches" meant. `dimension` names the preference axis this ask
    speaks for, so an axis the person constrained today can be removed from preference utility
    without a second table saying which is which.
    """

    name: str
    dimension: PreferenceDimension | None
    constrained: Callable[[ActivityIntent], bool]
    outcome: Callable[[ActivityCandidate, ActivityIntent], Tri]
    reason: Callable[[ActivityCandidate, ActivityIntent], str]
    # Why an UNKNOWN `outcome` is unknown. Read only for the evaluator's trace, never scored.
    unknown_reason: Callable[[ActivityCandidate, ActivityIntent], UnknownReason] = _listing_silent


def _distance_outcome(candidate: ActivityCandidate, intent: ActivityIntent) -> Tri:
    if intent.max_distance_m is None or candidate.distance_m is None:
        return Tri.UNKNOWN
    return Tri.MATCH if candidate.distance_m <= intent.max_distance_m else Tri.MISMATCH


def _time_outcome(candidate: ActivityCandidate, intent: ActivityIntent) -> Tri:
    if candidate.start_at is None:
        return Tri.UNKNOWN
    return (
        Tri.MATCH
        if _time_window_for_hour(local_hour(candidate.start_at)) == intent.time_window
        else Tri.MISMATCH
    )


def _social_outcome(candidate: ActivityCandidate, intent: ActivityIntent) -> Tri:
    if candidate.social_shape is None:
        return Tri.UNKNOWN
    return Tri.MATCH if candidate.social_shape == intent.social_preference else Tri.MISMATCH


def _intensity_outcome(candidate: ActivityCandidate, intent: ActivityIntent) -> Tri:
    if candidate.intensity is None or candidate.intensity not in INTENSITY_LADDER:
        return Tri.UNKNOWN
    return Tri.MATCH if candidate.intensity == intent.intensity else Tri.MISMATCH


def _language_outcome(candidate: ActivityCandidate, intent: ActivityIntent) -> Tri:
    if intent.language is None or not candidate.language_tags:
        return Tri.UNKNOWN
    return Tri.MATCH if intent.language in candidate.language_tags else Tri.MISMATCH


def _activity_type_outcome_detail(
    candidate: ActivityCandidate, intent: ActivityIntent
) -> tuple[Tri, UnknownReason | None]:
    """`_activity_type_outcome` with the reason for an UNKNOWN: an unlabelled listing says
    nothing; an `OTHER` listing says it is none of the kinds anyone can ask for."""
    if candidate.activity_type is None:
        return Tri.UNKNOWN, "listing_silent"
    if candidate.activity_type is ActivityType.OTHER:
        return Tri.UNKNOWN, "mismatch_not_counted"
    return (Tri.MATCH if candidate.activity_type in intent.activity_types else Tri.MISMATCH), None


def _activity_type_outcome(candidate: ActivityCandidate, intent: ActivityIntent) -> Tri:
    """`OTHER` and an unlabelled listing are both UNKNOWN. "Labelled, and none of the above" is
    not a kind of thing anyone can ask for, so it can neither satisfy a request nor contradict
    one -- and an unlabelled listing says nothing at all."""
    outcome, _ = _activity_type_outcome_detail(candidate, intent)
    return outcome


_INTENT_AXES: Final[tuple[_RequestAxis, ...]] = (
    _RequestAxis(
        name="distance",
        # DISTANCE belongs to `travel_utility` alone; naming it here would let the same metres be
        # scored once as a match and again as a cost.
        dimension=None,
        constrained=lambda intent: intent.max_distance_m is not None,
        outcome=_distance_outcome,
        reason=lambda candidate, intent: (
            f"{_format_distance(candidate.distance_m or 0)} away, within the "
            f"{_format_distance(intent.max_distance_m or 0)} you asked for."
        ),
    ),
    _RequestAxis(
        name="time_window",
        dimension=PreferenceDimension.TIMING,
        constrained=lambda intent: intent.time_window != TimeWindow.ANY,
        outcome=_time_outcome,
        reason=lambda candidate, intent: f"Runs in the {intent.time_window.value}, as you asked.",
    ),
    _RequestAxis(
        name="social",
        dimension=PreferenceDimension.SOCIAL,
        constrained=lambda intent: intent.social_preference != SocialPreference.EITHER,
        outcome=_social_outcome,
        reason=lambda candidate, intent: (
            "You will be among other people, as you asked."
            if intent.social_preference == SocialPreference.SOCIAL
            else "Something you can do on your own, as you asked."
        ),
    ),
    _RequestAxis(
        name="environment",
        dimension=PreferenceDimension.ENVIRONMENT,
        constrained=lambda intent: intent.environment != ActivityEnvironment.EITHER,
        outcome=lambda candidate, intent: environment_compatibility(
            intent.environment, candidate.indoor_outdoor
        ),
        reason=lambda candidate, intent: (
            f"{_ENVIRONMENT_LABEL[candidate.indoor_outdoor]}, as you asked."
        ),
    ),
    _RequestAxis(
        name="intensity",
        dimension=PreferenceDimension.INTENSITY,
        constrained=lambda intent: intent.intensity != ActivityIntensity.EITHER,
        outcome=_intensity_outcome,
        reason=lambda candidate, intent: (
            f"{_INTENSITY_LABEL[candidate.intensity]}, as you asked."
            if candidate.intensity in _INTENSITY_LABEL
            else "As active as you asked for."
        ),
    ),
    _RequestAxis(
        name="language",
        dimension=None,
        constrained=lambda intent: intent.language is not None,
        outcome=_language_outcome,
        reason=lambda candidate, intent: f"Offered in {intent.language}.",
    ),
    # The content axis, and a soft one. Asking *for* a walk ranks walks first and hides nothing;
    # the catalogue is fourteen programmes, so a hard content filter would turn most requests into
    # "nothing matched". Asking *not* to be shown walking is an exclusion, and that does filter.
    _RequestAxis(
        name="activity_type",
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        constrained=lambda intent: bool(intent.activity_types),
        outcome=_activity_type_outcome,
        unknown_reason=lambda candidate, intent: (
            _activity_type_outcome_detail(candidate, intent)[1] or "listing_silent"
        ),
        reason=lambda candidate, intent: (
            f"{ACTIVITY_TYPE_LABEL[candidate.activity_type]}, as you asked."
            if candidate.activity_type is not None
            else "The kind of thing you asked for."
        ),
    ),
)


def _constrained_axes(intent: ActivityIntent) -> int:
    return sum(1 for axis in _INTENT_AXES if axis.constrained(intent))


# What a listing scores on the request when the person constrained something and the listing can
# answer none of it. Neither the mismatch's `0.0` -- "not listed" is not "no", which is the whole
# of ADR 0006 §5 -- nor a free pass: `matched_axes` is `0` here and at least `1` for a listing
# that genuinely answers one, and that tie-break is what keeps the confirmed match above it.
_UNJUDGED_FIT: Final[float] = 1.0


@dataclass(frozen=True)
class RequestAxisOutcome:
    """One request axis, as `_request_fit` walked it for one listing.

    `outcome` is `None` when the request did not constrain the axis -- it was never asked about,
    so there is nothing to match. An UNKNOWN is a constrained axis the listing does not answer.
    """

    axis: str
    dimension: PreferenceDimension | None
    constrained: bool
    outcome: Tri | None
    unknown_reason: UnknownReason | None = None


@dataclass(frozen=True)
class _RequestFit:
    """How much of what was asked for this listing satisfies, and what can be said about it."""

    # `fit` is the weighted intent credit -- what the listing is shown to satisfy. `tier_fit` is
    # its place in the primary sort key. They differ in one case only: a listing that answers none
    # of what was asked earns no credit (nothing it says matched) but keeps the unjudged tier
    # (nothing it says contradicted), so "not listed" is neither rewarded nor treated as "no".
    fit: float
    tier_fit: float
    matched: int
    judged: int
    constrained: int
    reasons: list[ActivityReason]
    # Every request axis in `_INTENT_AXES` order, recorded by the same walk that scored them.
    axes: tuple[RequestAxisOutcome, ...] = ()

    @property
    def note(self) -> str:
        if not self.constrained:
            return "No constraint was asked for, so every option fits the request equally."
        if not self.judged:
            return (
                f"This listing does not say anything about the {self.constrained} thing(s) "
                "asked for, so it earns no credit for them but is not ranked below listings "
                "that contradict them."
            )
        unlisted = self.constrained - self.judged
        counted = f"Matched {self.matched} of the {self.judged} thing(s) this listing can answer"
        if unlisted:
            return (
                f"{counted}; {unlisted} of the {self.constrained} asked for "
                "are not listed, and are scored neither way."
            )
        return f"{counted}."


def _request_fit(candidate: ActivityCandidate, intent: ActivityIntent) -> _RequestFit:
    """What the person asked for today, scored once, with UNKNOWN out of both sides.

    An axis the listing does not answer is excluded from the numerator *and* the denominator. It
    used to land in the denominator as a miss, so an unlisted language cost a whole tier -- and
    because the tier is the primary sort key, nothing learned, no history and no context could
    ever lift that listing back. That is the one place the code made "not listed" behave exactly
    like "no".

    Excluding it from the denominator alone would trade that error for its mirror, making an
    unanswerable listing score identically to a confirmed match. `matched` travels out beside the
    fit for exactly that reason: at equal fit, more genuine matches ranks first.

    That rule has to hold at `judged == 0` too, and it did not: the empty ratio fell to `0.0`,
    which is the score a listing that contradicts *every* ask earns, on the primary sort key. A
    listing whose only judgeable axis matched scores `1.0`; one that judges nothing is the limit
    of that as the judged axes run out, not its opposite, so it takes the same `_UNJUDGED_FIT`
    *tier* and is separated from the genuine match by `matched_axes` -- exactly the tie-break the
    paragraph above exists for. A listing that contradicts an ask still sits below both.

    The tier is not the credit, though. Weighting that `1.0` as intent credit paid a listing the
    full intent weight -- more than preference, engagement, context and friction combined -- for
    saying nothing, and no line on its card could name why (D13). So the unjudged listing keeps
    `tier_fit = 1.0` and earns `fit = 0.0`: its place against contradicting listings is kept, and
    within the tier it competes on what it actually offers.

    The reason lines are the same walk as the score, never a second implementation of it, and are
    never truncated here -- which lines go on the card's face and which wait until it is opened
    is presentation, decided once, in `_compose_reasons`.
    """
    matched = 0
    judged = 0
    constrained = 0
    reasons: list[ActivityReason] = []
    axes: list[RequestAxisOutcome] = []
    for axis in _INTENT_AXES:
        if not axis.constrained(intent):
            axes.append(
                RequestAxisOutcome(
                    axis=axis.name, dimension=axis.dimension, constrained=False, outcome=None
                )
            )
            continue
        constrained += 1
        outcome = axis.outcome(candidate, intent)
        axes.append(
            RequestAxisOutcome(
                axis=axis.name,
                dimension=axis.dimension,
                constrained=True,
                outcome=outcome,
                unknown_reason=(
                    axis.unknown_reason(candidate, intent) if outcome is Tri.UNKNOWN else None
                ),
            )
        )
        if outcome is Tri.UNKNOWN:
            continue
        judged += 1
        if outcome is Tri.MATCH:
            matched += 1
            reasons.append(
                ActivityReason(text=axis.reason(candidate, intent), basis=ReasonBasis.INTENT)
            )
    if judged:
        fit = matched / judged
        tier_fit = fit
    elif constrained:
        # Nothing the listing says answers the request: no credit -- nothing matched, so no
        # contribution to the weighted total and no INTENT line owed -- but the unjudged tier, so
        # an unlisted field never sorts it below a listing that contradicts the ask.
        fit = 0.0
        tier_fit = _UNJUDGED_FIT
    else:
        # Nobody constrained anything, so every listing takes the same value and the request
        # factor cannot order them either way.
        fit = 0.0
        tier_fit = 0.0
    return _RequestFit(
        fit=round(fit, 3),
        tier_fit=round(tier_fit, 3),
        matched=matched,
        judged=judged,
        constrained=constrained,
        reasons=reasons,
        axes=tuple(axes),
    )


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _soft_radius_m(intent: ActivityIntent) -> int | None:
    """The radius a distance *phrase* implied, or `None` when the person named a number.

    The two halves of ADR 0006 §10, kept apart on purpose. A number is a barrier and is spent in
    `_too_far`, which removes everything beyond it; a phrase is a preference and is spent in
    `travel_utility`, which charges for the gap. Neither is ever spent twice, and a request that
    named neither leaves the learned tolerance exactly where it was.
    """
    if intent.max_distance_m is None or intent.distance_is_explicit:
        return None
    return intent.max_distance_m


def travel_cost_start(tolerance_m: int, asked_radius_m: int | None) -> tuple[int, bool]:
    """`(metres where travel starts to cost, whether today's asked radius set it)`.

    The person's tolerance, narrowed -- never widened -- to a positive radius a distance phrase
    asked for. `travel_utility` charges from exactly this point; see its docstring for why.
    """
    if asked_radius_m is not None and 0 < asked_radius_m < tolerance_m:
        return asked_radius_m, True
    return tolerance_m, False


TravelCostStartBasis = Literal[
    "default", "learned_ceiling", "learned_floor", "stated_near", "asked_radius"
]


@dataclass(frozen=True)
class TravelCostStart:
    """Where this search starts charging for distance, and what set that point."""

    starts_m: int
    basis: TravelCostStartBasis
    tolerance_m: int
    asked_radius_m: int | None


def travel_cost_start_for(
    preferences: ActivityPreferences, intent: ActivityIntent
) -> TravelCostStart:
    """`travel_cost_start` for one person and one request, from the same inputs scoring passes
    `travel_utility`: the learned tolerance and the soft radius a distance phrase implied."""
    resolved = resolved_preferences(preferences)
    tolerance_m = travel_tolerance_m(resolved)
    asked_radius_m = _soft_radius_m(intent)
    starts_m, asked_binds = travel_cost_start(tolerance_m, asked_radius_m)
    return TravelCostStart(
        starts_m=starts_m,
        basis="asked_radius" if asked_binds else travel_tolerance_basis(resolved),
        tolerance_m=tolerance_m,
        asked_radius_m=asked_radius_m,
    )


def travel_utility(
    distance_m: int | None,
    tolerance_m: int,
    *,
    asked_radius_m: int | None = None,
    tolerance_basis: TravelToleranceBasis | None = None,
) -> tuple[float, str]:
    """What getting there costs, in [-1, 0] -- **the only place distance is scored**.

    `u(d) = -clip((d - tolerance) / SCALE, 0, 1)`: nothing under what this person finds
    comfortable costs anything, and the cost grows at one fixed rate beyond it. `tolerance_m`
    comes from their own answers (`preferences.travel_tolerance_m`), which is how the learned
    DISTANCE ceiling is absorbed: it moves where the cost *starts*, not how fast it grows.

    Distance used to be scored in four separate places -- a friction factor, a learned near/far
    bucket on the preference factor, a hard 1 km default in the parser and an intent reason line --
    with no two of them agreeing on where "far" was. One monotone function, one owner.

    `asked_radius_m` is the radius a *phrase* implied today ("close by", "near home"), and only
    ever narrows where the cost starts: the tolerance for this one request is
    `min(tolerance_m, asked_radius_m)`. A number filters (`_too_far`) and a phrase costs (here),
    which is the asymmetry ADR 0006 §10 asks for -- but a phrase that costs nothing is a phrase
    that was not heard at all. Someone whose own answers have widened their tolerance to 5 km, or
    who has never said anything and sits on the default, would otherwise pay the same nothing for
    a 3.4 km listing as for a 650 m one on a request they opened with "somewhere close by".

    It never *widens*: a person whose own "too far" sits at 650 m keeps that ceiling on a request
    that said "within a kilometre", because today's ask is not permission to send them further
    than they have said they will go. Passing it for a radius the person gave as a number is a
    no-op -- everything beyond it has already been filtered out -- so the caller passes it only
    for the soft case, and a non-positive radius is ignored rather than read as "nowhere".

    An unknown distance costs nothing here. It sorts last on a tie instead, because an unlisted
    distance must never look like the closest option.

    `tolerance_basis` (`preferences.travel_tolerance_basis`) changes only the wording, never the
    value, so the note names what actually set the line: the default ("nothing learned about
    distance moves it"), a learned "too far" ceiling, a stated "somewhere near" with no number, or
    a learned floor ("has suited you"). A radius the person asked for today is named as such
    whatever the basis. `None` keeps the floor's wording, for a caller that does not know the
    basis.
    """
    if distance_m is None:
        return 0.0, "Distance not listed; costs nothing here and sorts last on a tie."
    effective_m, asked_binds = travel_cost_start(tolerance_m, asked_radius_m)
    line_basis = None if asked_binds else tolerance_basis
    if distance_m <= effective_m:
        if line_basis == "default":
            return 0.0, (
                f"{_format_distance(distance_m)} away -- within the "
                f"{_format_distance(effective_m)} default comfortable distance."
            )
        if line_basis == "learned_ceiling":
            return 0.0, (
                f"{_format_distance(distance_m)} away -- inside the "
                f"{_format_distance(effective_m)} line set by a learned \u201ctoo far\u201d."
            )
        if line_basis == "stated_near":
            return 0.0, (
                f"{_format_distance(distance_m)} away -- inside the "
                f"{_format_distance(effective_m)} a stated preference for somewhere near allows."
            )
        return 0.0, f"{_format_distance(distance_m)} away -- within your usual range."
    value = -min(1.0, (distance_m - effective_m) / _TRAVEL_SCALE_M)
    if asked_binds:
        limit = f"{_format_distance(effective_m)} you asked for."
    elif line_basis == "default":
        limit = (
            f"{_format_distance(effective_m)} default comfortable distance "
            "(nothing learned about distance moves it)."
        )
    elif line_basis == "learned_ceiling":
        limit = f"{_format_distance(effective_m)} line set by a learned \u201ctoo far\u201d."
    elif line_basis == "stated_near":
        limit = f"{_format_distance(effective_m)} a stated preference for somewhere near allows."
    else:
        limit = f"{_format_distance(effective_m)} that has suited you."
    return round(value, 3), f"{_format_distance(distance_m)} away, past the {limit}"


def in_decline_cooldown(engagement: ActivityEngagement | None, today: date | None) -> bool:
    """Whether a "not for me" on this engagement still holds the listing back on `today`."""
    return _in_cooldown(engagement, today)


def _in_cooldown(engagement: ActivityEngagement | None, today: date | None) -> bool:
    return (
        engagement is not None
        and engagement.last_not_for_me is not None
        and today is not None
        and today - engagement.last_not_for_me < timedelta(days=DECLINE_COOLDOWN_DAYS)
    )


def _engagement(
    engagement: ActivityEngagement | None, today: date | None = None
) -> tuple[float, str]:
    """The person's own responses to this listing, as one bounded value.

    One tap, one penalty: a "not for me" still inside `DECLINE_COOLDOWN_DAYS` is charged to the
    `repetition` factor and is not counted here as well, so a single decline never costs a
    listing twice at once. Once the cooldown lapses the decline moves to this durable count.
    `did_not_go` is carried for the record and deliberately not scored -- a missed plan is not
    evidence about the listing.
    """
    if engagement is None:
        return 0.0, "No recorded response to this listing yet."
    # Going somewhere and disliking it cancels the credit for going and costs more besides. A
    # verdict after attending is the best-grounded thing anyone says about a listing, and it used
    # to be worth nothing at all.
    attended = max(0, engagement.went - engagement.not_enjoyed)
    positive = (
        ENGAGEMENT_WEIGHTS["interested"] * engagement.interested
        + ENGAGEMENT_WEIGHTS["attended"] * attended
        + ENGAGEMENT_WEIGHTS["enjoyed"] * engagement.enjoyed
    )
    durable_declines = engagement.not_for_me - (1 if _in_cooldown(engagement, today) else 0)
    negative = (
        ENGAGEMENT_WEIGHTS["durable_not_for_me"] * max(0, durable_declines)
        + ENGAGEMENT_WEIGHTS["not_enjoyed"] * engagement.not_enjoyed
    )
    value = _clamp(positive - negative)
    parts = [
        f"{count} {label}"
        for count, label in (
            (engagement.interested, "interested"),
            (engagement.went, "went"),
            (engagement.enjoyed, "enjoyed"),
            (engagement.not_enjoyed, "went and did not enjoy"),
            (engagement.not_for_me, "not for me"),
        )
        if count
    ]
    return round(value, 3), (
        "Their own responses: " + ", ".join(parts) + "."
    ) if parts else "No recorded response to this listing yet."


def _repetition(engagement: ActivityEngagement | None, today: date | None) -> tuple[float, str]:
    if engagement is None or engagement.last_not_for_me is None or today is None:
        return 0.0, "Not recently declined."
    if _in_cooldown(engagement, today):
        assert engagement.last_not_for_me is not None
        return -1.0, (
            f"Declined on {engagement.last_not_for_me:%d %b}; held back for "
            f'{DECLINE_COOLDOWN_DAYS} days after a "not for me".'
        )
    return 0.0, "Declined once, but long enough ago to be worth showing again."


def _history_reason(engagement: ActivityEngagement | None) -> ActivityReason | None:
    """One grounded line from the person's own responses to this listing, or `None`.

    Only the positive responses ground a "why this fits" line -- a decline is not a reason
    something suits someone, and is scored (never explained) on the `engagement` and
    `repetition` factors instead.

    The wording follows the evidence down to the session. Counts arrive rolled up to the
    programme, so a card for Friday's class carries Wednesday's attendance; saying "You went to
    this one before." there claims the person attended a session they did not. A count this
    listing carries itself (`ActivityEngagement.own`) is "this one"; one inherited from a sibling
    session is "this programme".
    """
    if engagement is None:
        return None
    if engagement.not_enjoyed and not engagement.enjoyed:
        # They went, and said it was not for them. There is no honest positive line to draw from
        # that, and "You went to this one before." was being printed as one.
        return None
    own = engagement.own or engagement
    if engagement.enjoyed:
        return ActivityReason(
            text=(
                "You enjoyed this one before."
                if own.enjoyed
                else "You enjoyed this programme before."
            ),
            basis=ReasonBasis.HISTORY,
        )
    if engagement.went:
        return ActivityReason(
            text=(
                "You went to this one before." if own.went else "You went to this programme before."
            ),
            basis=ReasonBasis.HISTORY,
        )
    if engagement.interested:
        return ActivityReason(
            text=(
                "You said you were interested in this before."
                if own.interested
                else "You said you were interested in this programme before."
            ),
            basis=ReasonBasis.HISTORY,
        )
    return None


def _rain_reason(candidate: ActivityCandidate) -> ActivityReason:
    label = _ENVIRONMENT_LABEL.get(candidate.indoor_outdoor, "This option")
    return ActivityReason(
        text=f"{label}, a better fit with rain around today.",
        basis=ReasonBasis.CONTEXT,
    )


def _factor(name: str, value: float, note: str) -> ScoreFactor:
    weight = RANKING_WEIGHTS[name]
    return ScoreFactor(
        name=name,
        value=round(value, 3),
        weight=weight,
        contribution=round(value * weight, 3),
        note=note,
    )


@dataclass(frozen=True)
class ScoreDetail:
    """Everything `score_candidate` worked out for one listing, before any of it was discarded.

    Internal and never serialised as-is: the senior's card is built from `reasons`, the audit
    and the evaluation harness from `breakdown`. Collected by the one scoring walk, so nothing
    reading it can describe a score the ranker did not compute.
    """

    breakdown: ScoreBreakdown
    # The face of the card: at most three lines, chosen by `_compose_reasons`.
    reasons: list[ActivityReason]
    # Every other eligible line, shown when the card is opened. `reasons + more_reasons` is the
    # whole eligible set, and `breakdown.reasons_suppressed == len(more_reasons)`.
    more_reasons: list[ActivityReason]
    # Every grounded line as scoring collected it, before composition -- including the catalogue
    # filler when nothing else grounded anything, and lines `_compose_reasons` then found
    # ineligible (a factor that did not contribute positively). For the inspector's display
    # only; what the card shows, on its face or when opened, is `reasons` and `more_reasons`.
    candidate_reasons: list[ActivityReason]
    request_axes: tuple[RequestAxisOutcome, ...]
    request_matched: int
    request_judged: int
    request_constrained: int
    # The winning beliefs this search may score (constrained axes already removed), and what the
    # utility walk made of each.
    scorable: tuple[ResolvedPreference, ...]
    preference: PreferenceUtilityDetail
    engagement: ActivityEngagement | None
    in_cooldown: bool
    # True when the rain nudge applied at all (rain forecast, environment left open).
    rain_applied: bool
    history_reason: ActivityReason | None
    travel_tolerance_m: int
    asked_radius_m: int | None


def score_candidate_detail(
    candidate: ActivityCandidate,
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    *,
    rain_forecast: bool = False,
    engagement: ActivityEngagement | None = None,
    today: date | None = None,
) -> ScoreDetail:
    """`score_candidate`, keeping the walk that produced the score. See `score_candidate`."""
    request = _request_fit(candidate, intent)
    reasons = [*request.reasons, *_preference_reasons(candidate, preferences, intent)]

    scorable = _scorable_preferences(preferences, intent)
    preference = preference_utility_detail(candidate, scorable)
    preference_fit, coverage, preference_matched = (
        preference.utility,
        preference.coverage,
        preference.matched,
    )
    if not scorable:
        preference_note = "Nothing is known yet about the kinds of activity that suit them."
    elif coverage == 0.0:
        preference_note = (
            "This listing does not say enough to judge any of what is known; scored neither way."
        )
    else:
        preference_note = (
            f"Judged on {coverage:.0%} of what is known about the kinds of activity that suit "
            "them; positive where this listing confirms it, negative where it contradicts it."
        )

    context_fit = 0.0
    context_note = "No weather nudge today."
    apply_rain_bias = rain_forecast and intent.environment == ActivityEnvironment.EITHER
    if apply_rain_bias:
        if covered(candidate.indoor_outdoor):
            context_fit = 1.0
            context_note = "Rain around today and this is under cover."
            reasons.append(_rain_reason(candidate))
        elif candidate.indoor_outdoor == IndoorOutdoor.OUTDOOR:
            context_fit = -0.5
            context_note = "Rain around today and this is outdoors."
        else:
            context_note = "Rain around today; the listing does not say whether it is under cover."

    engagement_value, engagement_note = _engagement(engagement, today)
    history = _history_reason(engagement)
    if history is not None:
        reasons.append(history)
    repetition_value, repetition_note = _repetition(engagement, today)
    resolved = resolved_preferences(preferences)
    tolerance_m = travel_tolerance_m(resolved)
    asked_radius_m = _soft_radius_m(intent)
    friction_value, friction_note = travel_utility(
        candidate.distance_m,
        tolerance_m,
        asked_radius_m=asked_radius_m,
        tolerance_basis=travel_tolerance_basis(resolved),
    )

    factors = [
        _factor("intent", request.fit, request.note),
        _factor("preference", preference_fit, preference_note),
        _factor("engagement", engagement_value, engagement_note),
        _factor("repetition", repetition_value, repetition_note),
        _factor("context", context_fit, context_note),
        _factor("friction", friction_value, friction_note),
    ]
    total = round(sum(factor.contribution for factor in factors), 3)
    contributions = {factor.name: factor.contribution for factor in factors}
    # A card never carries a catalogue filler line beside a real reason: the filler is composed
    # only when nothing else a card may show grounds anything.
    if not eligible_reasons(reasons, contributions):
        reasons = [*reasons, *_catalogue_filler(candidate)]
    kept, more = _compose_reasons(reasons, contributions)
    return ScoreDetail(
        breakdown=ScoreBreakdown(
            factors=factors,
            total=total,
            tier=round(request.tier_fit + repetition_value, 3),
            reasons_suppressed=len(more),
            coverage=coverage,
            matched_axes=request.matched + preference_matched,
        ),
        reasons=kept,
        more_reasons=more,
        candidate_reasons=list(reasons),
        request_axes=request.axes,
        request_matched=request.matched,
        request_judged=request.judged,
        request_constrained=request.constrained,
        scorable=tuple(scorable),
        preference=preference,
        engagement=engagement,
        in_cooldown=_in_cooldown(engagement, today),
        rain_applied=apply_rain_bias,
        history_reason=history,
        travel_tolerance_m=tolerance_m,
        asked_radius_m=asked_radius_m,
    )


def score_candidate(
    candidate: ActivityCandidate,
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    *,
    rain_forecast: bool = False,
    engagement: ActivityEngagement | None = None,
    today: date | None = None,
) -> tuple[ScoreBreakdown, list[ActivityReason]]:
    """The deterministic score behind one candidate's position, and the reasons shown with it.

    Pure and total, like everything else in this module. The breakdown is the whole account of
    the order -- every factor named, bounded and weighted -- and the reasons are the subset of it
    a person is shown: the positive, grounded lines. The two are computed together so the card
    and the evaluator can never be describing different evidence.
    """
    detail = score_candidate_detail(
        candidate,
        intent,
        preferences,
        rain_forecast=rain_forecast,
        engagement=engagement,
        today=today,
    )
    return detail.breakdown, detail.reasons


@dataclass(frozen=True)
class RankedScore:
    """One ranked candidate beside the breakdown that put it there -- the evaluator's view."""

    ranked: RankedActivity
    breakdown: ScoreBreakdown


def _renumber(ranked: list[RankedScore]) -> list[RankedScore]:
    return [
        RankedScore(
            ranked=entry.ranked.model_copy(update={"rank": position}), breakdown=entry.breakdown
        )
        for position, entry in enumerate(ranked, start=1)
    ]


@dataclass(frozen=True)
class SeriesDeferral:
    """One session `_dedupe_series` moved below the top three, and the session that kept its
    series' slot. Positions are 1-based: before the pass, then after it."""

    activity_id: str
    series_holder_id: str
    from_position: int
    to_position: int


@dataclass(frozen=True)
class SeriesDedupeRecord:
    """What the series dedupe pass did to one order.

    `deferred` means flagged `series_deferred` after the pass's own refill: a session first set
    aside and then used to fill an otherwise-empty top-three slot is listed in `refilled`
    instead, because it was not in fact moved below the top three.
    """

    ran: bool
    deferred: tuple[SeriesDeferral, ...] = ()
    refilled: tuple[str, ...] = ()
    changed: bool = False


def _dedupe_series_with_record(
    ranked: list[RankedScore],
) -> tuple[list[RankedScore], SeriesDedupeRecord]:
    """`_dedupe_series`, returning what it deferred beside the order. See `_dedupe_series`."""
    if len(ranked) <= _DIVERSITY_TOP_N:
        return ranked, SeriesDedupeRecord(ran=False)
    seen: set[str] = set()
    top: list[RankedScore] = []
    deferred: list[RankedScore] = []
    rest: list[RankedScore] = []
    for entry in ranked:
        key = series_key(entry.ranked.candidate)
        if len(top) < _DIVERSITY_TOP_N:
            if key in seen:
                deferred.append(
                    RankedScore(
                        ranked=entry.ranked,
                        breakdown=entry.breakdown.model_copy(update={"series_deferred": True}),
                    )
                )
            else:
                seen.add(key)
                top.append(entry)
        else:
            rest.append(entry)
    if not deferred:
        return ranked, SeriesDedupeRecord(ran=True)
    # Fewer distinct series than slots: the best deferred sessions fill the top three after all,
    # unflagged, because they were not in fact moved below it.
    refilled: list[str] = []
    while len(top) < _DIVERSITY_TOP_N and deferred:
        refill = deferred.pop(0)
        refilled.append(refill.ranked.candidate.activity_id)
        top.append(
            RankedScore(
                ranked=refill.ranked,
                breakdown=refill.breakdown.model_copy(update={"series_deferred": False}),
            )
        )
    result = _renumber([*top, *deferred, *rest])

    before = [entry.ranked.candidate.activity_id for entry in ranked]
    after = [entry.ranked.candidate.activity_id for entry in result]
    # The best-placed session of each series holds its slot; a refilled sibling never does.
    holders: dict[str, RankedScore] = {}
    for entry in top:
        holders.setdefault(series_key(entry.ranked.candidate), entry)
    return result, SeriesDedupeRecord(
        ran=True,
        deferred=tuple(
            SeriesDeferral(
                activity_id=entry.ranked.candidate.activity_id,
                series_holder_id=holders[
                    series_key(entry.ranked.candidate)
                ].ranked.candidate.activity_id,
                from_position=before.index(entry.ranked.candidate.activity_id) + 1,
                to_position=after.index(entry.ranked.candidate.activity_id) + 1,
            )
            for entry in deferred
        ),
        refilled=tuple(refilled),
        changed=before != after,
    )


def _dedupe_series(ranked: list[RankedScore]) -> list[RankedScore]:
    """Keep the top three from being three sessions of the same programme.

    A programme with sessions on several days scores near-identically for each of them, so
    without this the first card, the second and the third were routinely the same title at
    different times. The best-scoring session of each series keeps its place; the others are
    deferred below the top three (flagged `series_deferred`), in their existing order, so the
    person still sees them if they scroll. Nothing is removed and no hard filter is revisited.
    """
    result, _ = _dedupe_series_with_record(ranked)
    return result


def _variety_key(candidate: ActivityCandidate) -> str | None:
    """What counts as "the same kind of thing" for the variety swap.

    `activity_type` -- what the thing actually is. It used to be `category`, which holds a
    *format* label, so a walk, a tai chi class and a gardening session were all "Group class" and
    counted as identical, while a walk and a karaoke session counted as different. Variety on that
    key was variety in how a session is run, which is not what anyone means by it.

    Format is the fallback only where neither listing is labelled at all -- something is better
    than nothing there, and the prefixes keep a typed listing from ever colliding with an untyped
    one. `None` is never "different": absence is not a kind.
    """
    if candidate.activity_type is not None and candidate.activity_type is not ActivityType.OTHER:
        return f"type:{candidate.activity_type.value}"
    return f"format:{candidate.category}" if candidate.category is not None else None


VarietyStatus = Literal[
    "not_enough_candidates",
    "top_three_mixed",
    "top_three_unkinded",
    "no_candidate_within_margin",
    "swapped",
]


@dataclass(frozen=True)
class VarietyConsidered:
    """A lower candidate of a different kind the variety pass looked at and did not promote."""

    activity_id: str
    kind: str
    tier: float
    total: float
    outcome: Literal["different_tier", "outside_margin"]


@dataclass(frozen=True)
class VarietySwap:
    """The one swap `_diversify` made. Positions are 1-based."""

    promoted_id: str
    displaced_id: str
    from_position: int
    to_position: int
    shared_kind: str
    promoted_kind: str
    tier: float
    third_total: float
    promoted_total: float
    margin: float
    reasons_before: tuple[ActivityReason, ...]
    reasons_after: tuple[ActivityReason, ...]
    # The promoted card's `more_reasons` after the rebuild (`_compose_reasons` over its face, its
    # `more_reasons` and the VARIETY line): whatever the VARIETY line pushed off the face joins
    # what was already there. Its length is the promoted breakdown's `reasons_suppressed`.
    more_reasons_after: tuple[ActivityReason, ...]


@dataclass(frozen=True)
class VarietyRecord:
    status: VarietyStatus
    shared_kind: str | None = None
    considered: tuple[VarietyConsidered, ...] = ()
    swap: VarietySwap | None = None


def _diversify_with_record(
    ranked: list[RankedScore],
) -> tuple[list[RankedScore], VarietyRecord]:
    """`_diversify`, returning what the variety pass did beside the order. See `_diversify`."""
    if len(ranked) <= _DIVERSITY_TOP_N:
        return ranked, VarietyRecord(status="not_enough_candidates")
    top = ranked[:_DIVERSITY_TOP_N]
    kinds = {_variety_key(item.ranked.candidate) for item in top}
    if len(kinds) != 1:
        return ranked, VarietyRecord(status="top_three_mixed")
    if None in kinds:
        return ranked, VarietyRecord(status="top_three_unkinded")
    shared = next(iter(kinds))
    assert shared is not None
    third = top[-1]
    third_total = third.breakdown.total
    third_tier = _tier(third.breakdown)
    considered: list[VarietyConsidered] = []
    for index in range(_DIVERSITY_TOP_N, len(ranked)):
        item = ranked[index]
        kind = _variety_key(item.ranked.candidate)
        if kind is None or kind == shared:
            continue
        # Variety never crosses a tier. The tier is the one mechanism that keeps a stated request
        # ahead of everything learned; a candidate that matched less of what the person asked for
        # (or is inside a decline cooldown) sits in a lower tier and may not be promoted over the
        # third-ranked one however close its weighted total is.
        if _tier(item.breakdown) != third_tier:
            considered.append(
                VarietyConsidered(
                    activity_id=item.ranked.candidate.activity_id,
                    kind=kind,
                    tier=_tier(item.breakdown),
                    total=item.breakdown.total,
                    outcome="different_tier",
                )
            )
            continue
        if third_total - item.breakdown.total > DIVERSITY_SCORE_MARGIN:
            considered.append(
                VarietyConsidered(
                    activity_id=item.ranked.candidate.activity_id,
                    kind=kind,
                    tier=_tier(item.breakdown),
                    total=item.breakdown.total,
                    outcome="outside_margin",
                )
            )
            continue
        variety = ActivityReason(
            text="Something a bit different from the others.", basis=ReasonBasis.VARIETY
        )
        # Composed over every eligible line the card had, face and `more_reasons` alike, so a
        # line the VARIETY note pushes off the face moves into `more_reasons` rather than
        # vanishing. The face is the same as composing over the face alone: within each basis the
        # face already holds the first lines, and it holds a line for every basis that could win
        # one of the two slots left beside the VARIETY line.
        rebuilt = [*item.ranked.reasons, *item.ranked.more_reasons, variety]
        contributions = {factor.name: factor.contribution for factor in item.breakdown.factors}
        kept, more = _compose_reasons(rebuilt, contributions)
        promoted = RankedScore(
            ranked=item.ranked.model_copy(update={"reasons": kept, "more_reasons": more}),
            breakdown=item.breakdown.model_copy(
                update={
                    "variety_promoted": True,
                    # D11: every eligible line the face could not fit, before or after the rebuild.
                    "reasons_suppressed": len(more),
                }
            ),
        )
        # The promoted candidate takes third place; the former third and everything below it
        # shift down one, in their existing order.
        reordered = [*ranked[: _DIVERSITY_TOP_N - 1], promoted] + [
            entry for entry in ranked[_DIVERSITY_TOP_N - 1 :] if entry is not item
        ]
        return _renumber(reordered), VarietyRecord(
            status="swapped",
            shared_kind=shared,
            considered=tuple(considered),
            swap=VarietySwap(
                promoted_id=item.ranked.candidate.activity_id,
                displaced_id=third.ranked.candidate.activity_id,
                from_position=index + 1,
                to_position=_DIVERSITY_TOP_N,
                shared_kind=shared,
                promoted_kind=kind,
                tier=third_tier,
                third_total=third_total,
                promoted_total=item.breakdown.total,
                margin=round(third_total - item.breakdown.total, 3),
                reasons_before=tuple(item.ranked.reasons),
                reasons_after=tuple(kept),
                more_reasons_after=tuple(more),
            ),
        )
    return ranked, VarietyRecord(
        status="no_candidate_within_margin", shared_kind=shared, considered=tuple(considered)
    )


def _diversify(ranked: list[RankedScore]) -> list[RankedScore]:
    """Keep the top three from being three of the same kind of thing.

    Interpretable on purpose: one rule, one swap. If every candidate in the top `_DIVERSITY_TOP_N`
    is the same `_variety_key` and some lower candidate of a different kind scores within
    `DIVERSITY_SCORE_MARGIN` of the third, that candidate takes the third slot, is flagged
    `variety_promoted`, and gains one plainly worded `VARIETY` reason. Nothing outside the margin
    is ever promoted, no hard filter is revisited, and a candidate with no kind at all is never
    treated as "different" -- absence is not a kind.
    """
    result, _ = _diversify_with_record(ranked)
    return result


@dataclass(frozen=True)
class SortKey:
    """The one sort key the ranker orders by, as named fields rather than a bare tuple.

    `ordering()` is the tuple `score_and_sort` actually sorts on: tier and total descending, then
    more matched axes, then the nearer listing (an unknown distance sorts last), then title, then
    the sooner session (an undated one last), then the activity id so the order never depends on
    the order the catalogue arrived in.
    """

    tier: float
    total: float
    matched_axes: int
    distance_m: int | None
    title: str
    start_at: datetime | None
    activity_id: str

    def ordering(self) -> tuple[float, float, int, float, str, float, str]:
        distance_key = (
            float(self.distance_m) if self.distance_m is not None else _UNKNOWN_DISTANCE_SORT
        )
        start_key = self.start_at.timestamp() if self.start_at is not None else _UNKNOWN_START_SORT
        return (
            -self.tier,
            -self.total,
            # The tie-break that keeps "not listed" from being free. UNKNOWN is out of both sides
            # of every fit, so an unanswerable listing scores exactly like a confirmed match; at
            # equal tier and equal total, the one that actually matches more of what was asked
            # and what is known ranks first.
            -self.matched_axes,
            distance_key,
            self.title,
            # Equal-scoring sessions of one programme: the soonest first, so the session a card
            # headlines is also the next chance to go.
            start_key,
            # Last resort, so the order is a function of the catalogue and never of the order the
            # catalogue happened to arrive in: two sessions of one programme that tie on
            # everything above still fall in a fixed order.
            self.activity_id,
        )


def sort_key_for(candidate: ActivityCandidate, breakdown: ScoreBreakdown) -> SortKey:
    """The sort key the ranker orders `candidate` by, from its scored `breakdown`."""
    return SortKey(
        tier=_tier(breakdown),
        total=breakdown.total,
        matched_axes=breakdown.matched_axes,
        distance_m=candidate.distance_m,
        title=candidate.title,
        start_at=candidate.start_at,
        activity_id=candidate.activity_id,
    )


@dataclass(frozen=True)
class ScoredCandidate:
    """One scored candidate in sort order: the ranked entry, the walk behind it, and its key."""

    entry: RankedScore
    detail: ScoreDetail
    sort_key: SortKey


def score_and_sort_detailed(
    candidates: list[ActivityCandidate],
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    *,
    rain_forecast: bool = False,
    engagement: Mapping[str, ActivityEngagement] | None = None,
    today: date | None = None,
) -> list[ScoredCandidate]:
    """Score every candidate and sort by `SortKey`, keeping each candidate's scoring detail.

    Never filters and never post-processes: that is `filter_candidates` before it and
    `postprocess` after it. `score_and_sort` is this function's ranked entries alone.
    """
    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        detail = score_candidate_detail(
            candidate,
            intent,
            preferences,
            rain_forecast=rain_forecast,
            engagement=(engagement or {}).get(candidate.activity_id),
            today=today,
        )
        scored.append(
            ScoredCandidate(
                entry=RankedScore(
                    ranked=RankedActivity(
                        candidate=candidate,
                        rank=1,
                        reasons=detail.reasons,
                        more_reasons=detail.more_reasons,
                        series_key=series_key(candidate),
                    ),
                    breakdown=detail.breakdown,
                ),
                detail=detail,
                sort_key=sort_key_for(candidate, detail.breakdown),
            )
        )
    scored.sort(key=lambda item: item.sort_key.ordering())
    renumbered = _renumber([item.entry for item in scored])
    return [
        ScoredCandidate(entry=entry, detail=item.detail, sort_key=item.sort_key)
        for entry, item in zip(renumbered, scored, strict=True)
    ]


def score_and_sort(
    candidates: list[ActivityCandidate],
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    *,
    rain_forecast: bool = False,
    engagement: Mapping[str, ActivityEngagement] | None = None,
    today: date | None = None,
) -> list[RankedScore]:
    """Every candidate scored and in `SortKey` order, numbered from 1, before `postprocess`."""
    return [
        item.entry
        for item in score_and_sort_detailed(
            candidates,
            intent,
            preferences,
            rain_forecast=rain_forecast,
            engagement=engagement,
            today=today,
        )
    ]


def rank_candidates_with_breakdown(
    candidates: list[ActivityCandidate],
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    *,
    rain_forecast: bool = False,
    engagement: Mapping[str, ActivityEngagement] | None = None,
    today: date | None = None,
    diversity: bool = True,
) -> list[RankedScore]:
    """`rank_candidates`, keeping each candidate's `ScoreBreakdown` beside it.

    The repository records the breakdowns on the `activity_search` audit event and the ranking
    harness scores them; the senior's own response is built from `.ranked` alone. `diversity`
    exists for the evaluation harness's ablation of the diversity swap alone -- everything
    before it (tier sort, series dedupe) still runs -- and is always on in the product.

    `score_and_sort` then `postprocess`. It never filters: `candidates` is what the caller has
    already let through `filter_candidates` (or chosen not to, in the evaluation harness).
    """
    return postprocess(
        score_and_sort(
            candidates,
            intent,
            preferences,
            rain_forecast=rain_forecast,
            engagement=engagement,
            today=today,
        ),
        diversity=diversity,
    )


def postprocess(ranked: list[RankedScore], *, diversity: bool = True) -> list[RankedScore]:
    """The two order-preserving passes that run after scoring, exposed so an evaluation arm that
    re-sorts breakdowns can run the production passes instead of re-implementing them."""
    ranked = _dedupe_series(ranked)
    return _diversify(ranked) if diversity else ranked


def _tier(breakdown: ScoreBreakdown) -> float:
    """The first sort key: what the person asked for, less what they just said no to.

    The weighted total decides the order only *within* a tier. This is what makes the stated
    request genuinely dominant: a candidate matching more of the ask ranks above one matching
    less, whatever has been learned, and no combination of preference, engagement, context and
    friction can lift a weaker match past a fuller one. The one thing allowed to pull a matching
    listing down a tier is the person's own recent "not for me" on it (`repetition`, -1 inside
    the cooldown) -- their most recent word about that exact listing.

    Read from `ScoreBreakdown.tier`, which scoring sets: the tier is not derivable from the
    weighted factors, because a listing that answers none of the request keeps an unjudged tier
    while earning no intent credit.
    """
    return breakdown.tier


def rank_candidates(
    candidates: list[ActivityCandidate],
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    *,
    rain_forecast: bool = False,
    engagement: Mapping[str, ActivityEngagement] | None = None,
    today: date | None = None,
) -> list[RankedActivity]:
    """Order the candidates the deterministic filter already permitted.

    This is the fallback the bounded ranking loop in `agent.planner` degrades to whenever the
    planner is disabled, unreachable or exhausts its iteration cap without an approved proposal
    -- so it must produce a complete, sensible order entirely on its own, never merely a
    placeholder for the model to improve on.

    The order comes from `score_candidate`: six named, bounded factors (see `RANKING_WEIGHTS`),
    with what the person asked for weighted so that a full match outranks everything learned or
    inferred combined. The sort key (`SortKey`, `sort_key_for`) is the tier
    (`ScoreBreakdown.tier`: how much of the request the listing can satisfy, less a recent "not
    for me") and then the weighted total, both descending; then more matched axes; then the nearer
    listing (an unknown distance last); then title; then the sooner session (an undated one last);
    then activity id -- so the result is fully deterministic for a given catalogue, request,
    preference set and response history. After scoring, `postprocess`
    runs two passes in order: `_dedupe_series` defers later sessions of a programme already in
    the top three, then `_diversify` may swap one candidate of a different kind into third place,
    and says so on the candidate it moved.

    `rain_forecast` is F35: "context on the action side". Rain no longer only excuses a quiet day
    (`policy.py`); the same fact nudges what is offered when someone is choosing for themselves --
    indoor and sheltered options rank above outdoor ones, disclosed as a `CONTEXT` reason. It only
    applies when the person left the environment open (`ActivityEnvironment.EITHER`): an explicit
    ask for outdoor is honoured regardless of the forecast, because this is a better-fit nudge,
    not a safety override.

    `engagement` is the person's own recorded responses per listing (`ActivityEngagement`) and
    `today` the simulated day, used only for the "not for me" cooldown. Both default to nothing,
    so every existing caller and test keeps its meaning.
    """
    return [
        item.ranked
        for item in rank_candidates_with_breakdown(
            candidates,
            intent,
            preferences,
            rain_forecast=rain_forecast,
            engagement=engagement,
            today=today,
        )
    ]
