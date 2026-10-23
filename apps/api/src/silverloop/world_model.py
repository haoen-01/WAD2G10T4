"""The personal world model: what Care+ knows about one person, as typed facts.

Assembled, never stored. Every fact here is a re-reading of a row that already exists -- the
rolling baseline, a dimension preference, the person's own mute or goal, an answer they gave,
the persona profile -- so the model cannot drift from its evidence and cannot hold a fact with
nothing behind it. The one thing this module adds is the envelope: where each fact came from
(`FactSourceType`), how much sits behind it (`evidence_count`, `FactConfidence`), when it was
first and last seen, whether it expires, and whether the person confirmed it.

Three rules the envelope enforces:

  * **An inference is never presented as a statement.** `EXPLICIT` is reserved for what the
    person said or deliberately chose; everything learned from taps and days is `INFERRED`;
    the persona biography is `FIXTURE`, because it is synthetic and must say so.
  * **Confidence is qualitative.** One tap and three days are not 73% of anything, and a number
    would imply a precision the evidence cannot support.
  * **A gap is stated, not filled.** `gaps` names what Care+ does not know and will not
    guess -- routines by time of day, weekday patterns, weather sensitivity, where the person
    lives -- so a reader can see the edges of the model rather than infer them from silence.

Pure and total over its inputs: no database, no clock, no network. The repository gathers the
rows; this module only reads them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from silverloop.local_time import at_local, local_date
from silverloop.models import (
    ActivityGoal,
    BaselineSummary,
    CandidatePreference,
    DeclineReason,
    DimensionPreference,
    FactCategory,
    FactConfidence,
    FactSourceType,
    PersonFact,
    PersonWorldModel,
    PreferenceDimension,
    ResolvedPreference,
    WorldModelQuality,
)
from silverloop.preferences import (
    GOAL_DIMENSION_VALUES,
    INTENSITY_LADDER,
    activity_type_label,
    belief_in_effect,
    goal_key,
    is_goal_key,
    resolve,
)

# How much observed evidence earns MEDIUM for an inferred fact. Deliberately low, with an honest
# ceiling: nothing inferred from taps reaches HIGH without the person confirming it, which is
# what `confirmed` is for.
_MEDIUM_EVIDENCE = 3

# An inferred fact nothing has reinforced for this long is labelled stale, measured on the
# person's own simulated calendar (`as_of_day - local_date(updated_at)`) -- the same clock
# `_preference_expired` uses for calendar expiry, never the wall clock. A label on the fact,
# never a change to its strength or its place in ranking.
_STALE_AFTER_DAYS = 90

# Below this share of usable days the rolling baseline is a thin reading of the person's routine.
_THIN_BASELINE_QUALITY = 0.5


@dataclass(frozen=True)
class ConfirmedReferenceFact:
    """The person's own "this is my new normal", when they have given one."""

    steps: float
    confirmation_id: str
    decided_on_day: date
    decided_at: datetime


@dataclass(frozen=True)
class ContextAnswerFact:
    question_id: str
    value: str
    label: str
    answer_id: str
    answered_at: datetime
    # The simulated day the answer was about. An answer to "is everything alright today?" is a
    # fact about that day, and lapses after it; `None` when the day was not recorded.
    answered_on_day: date | None = None


@dataclass(frozen=True)
class OutreachResponseFact:
    """What a person has done with one kind of outreach, as counts the learner already keeps.

    The outcome breakdown is carried in full, and that is the whole point of the type. Read as
    "accepted or not", this fact told the person *"You were offered "X" and passed on it."* for
    every offer that was not a yes -- including the ones they never replied to, and including
    one that was still open and unanswered on their own home page at the time. Silence is
    recorded as silence and not as a refusal everywhere else in this product
    (`sql_repository._resolve_unanswered`, the coordinator queue's "Closed as silence, not a
    refusal", the effectiveness panel's refusal to fold a tap into a rate); the person's own
    memory page was the one surface that told them they had said no when they had not.

    So `declined` (an explicit "not today"/"not for me") is counted apart from `deferred` (an
    explicit "maybe later"), apart from `no_response` (the response window closed on silence),
    and apart from an offer with no outcome row at all -- which is not a fact about the person
    yet and produces no statement. `decline_reason` is the person's own one-tap reason on the
    most recent decline, if they gave one; it is narrated in plain words, never as its enum.
    """

    candidate_key: str
    label: str
    offered: int
    accepted: int
    completed: int
    declined: int = 0
    deferred: int = 0
    no_response: int = 0
    decline_reason: DeclineReason | None = None


@dataclass(frozen=True)
class ActivityHistoryFact:
    """One programme the person has actually been to, counted across its own sessions.

    Series-level, never per session, and that is the whole point of the type. A class running on
    Monday, Wednesday and Friday is three listings and one thing to have been to, so *ranking*
    rolls a person's responses up to the series (`activity_search.engagement_by_series`): a
    cooldown that reached only Monday's row left the identical class offered twice more that
    week. A fact shown to the person cannot inherit that roll-up. Read per listing, one Wednesday
    attendance printed three facts -- "You went to Chair Mobility & Balance", once for the
    Wednesday and once each for a Monday and a Friday the person never attended -- each of them
    `EXPLICIT`, `HIGH` and confirmed. That is the product telling someone something about their
    own week that did not happen.

    `went` counts only the sessions that carry an attendance report of their own, and is the
    fact's `evidence_count`; `series_key` identifies the programme by
    `activity_search.series_identity` -- provider and title, trimmed and case-folded, the ranker's
    own definition -- joined with "|", which is only this fact key's encoding
    (`activity:{provider|title}`), so the key is stable across its sessions and across a demo reset
    that re-mints listing ids.
    """

    series_key: str
    title: str
    went: int
    enjoyed: int


@dataclass(frozen=True)
class WorldModelInputs:
    person_id: str
    display_name: str
    as_of_day: date
    as_of: datetime
    preferred_language: str | None
    age: int | None
    background: str | None
    is_synthetic_profile: bool
    consent_active: bool
    consent_evidence_id: str | None
    consent_recorded_at: datetime | None
    # `ConsentEvidenceRow.source`, e.g. `synthetic_fixture` or `user_demo_input`. `None` only for
    # a person with no consent row at all, which the seed step never leaves happen in practice.
    consent_source: str | None
    baseline: BaselineSummary
    baseline_observed_at: datetime | None
    confirmed_reference: ConfirmedReferenceFact | None
    preferences: list[DimensionPreference] = field(default_factory=list)
    # The same beliefs, resolved (`preferences.resolve`): the tier that wins each axis, and the
    # lower-tier beliefs that disagree with it. Read for `contradicted_by` rather than pairing
    # rows here, so a belief a statement has *consumed* cannot be shown contradicting it.
    resolved: list[ResolvedPreference] = field(default_factory=list)
    expired_preferences: int = 0
    mutes: list[CandidatePreference] = field(default_factory=list)
    goals: list[ActivityGoal] = field(default_factory=list)
    context_answers: list[ContextAnswerFact] = field(default_factory=list)
    disputed_days: int = 0
    # Already converted to the person's local hour (`local_time.local_hour`), never a raw UTC one.
    typical_response_hour: int | None = None
    typical_response_hour_sample: int = 0
    # True while the product has no real response timestamps to read (`ADAPTER_MODE=fixture`,
    # true of every build today): a demo can advance a week of simulated days inside a real
    # minute, so a reply's wall-clock hour would measure the operator's clicking, not a routine.
    # The fact is dropped rather than shown with a caveat nobody would read.
    is_simulated_run: bool = False
    outreach_responses: list[OutreachResponseFact] = field(default_factory=list)
    activity_history: list[ActivityHistoryFact] = field(default_factory=list)


# A stated `either` is the absence of a lean, not a lean towards it, and is never narrated as
# one -- the wording branches on this rather than calling `_preference_value_phrase`, which has
# no neutral answer for a value it was never designed to receive.
_EITHER_VALUE = "either"

_DIMENSION_LABELS: dict[PreferenceDimension, str] = {
    PreferenceDimension.DISTANCE: "distance",
    PreferenceDimension.INTENSITY: "how active it is",
    PreferenceDimension.TIMING: "time of day",
    PreferenceDimension.SOCIAL: "company",
    PreferenceDimension.ENVIRONMENT: "indoor or outdoor",
    PreferenceDimension.ACTIVITY_TYPE: "the kind of thing it is",
}


def _dimension_label(dimension: PreferenceDimension) -> str:
    return _DIMENSION_LABELS.get(dimension, dimension.value.lower())


# The person's own one-tap decline reason, in the words the chip they tapped used
# (`view-models.SENIOR_NUDGE_DECLINE_REASONS`), tensed for a sentence about something that has
# already happened. A `DeclineReason` this map does not cover -- a value added to the enum and
# not to this page -- narrates as a plain "You said no to ...", because the alternative is
# printing `prefer_something_else` at a 74-year-old. Nothing here is inferred: the reason exists
# only because the person chose to give it, and no reason at all is the common case.
_DECLINE_REASON_CLAUSES: dict[DeclineReason, str] = {
    DeclineReason.NOT_FOR_ME: "it was not for you",
    DeclineReason.TOO_FAR: "it was too far",
    DeclineReason.TOO_TIRING: "it sounded too tiring",
    DeclineReason.BAD_TIMING: "the timing did not suit you",
    DeclineReason.PREFER_SOMETHING_ELSE: "you would prefer something else",
    DeclineReason.BAD_DAY: "it was just a bad day",
    DeclineReason.ALREADY_ACTIVE: "you were already getting about",
}


def _distance_words(metres: float) -> str:
    """Never "1200 m": nobody thinks in metres at that size."""
    return f"{metres / 1000:g} km" if metres >= 1000 else f"{metres:.0f} m"


def ordinal_preference_phrase(preference: DimensionPreference) -> str | None:
    """A line the person's own answer drew, in their own units -- or `None` for a nominal belief.

    DISTANCE and INTENSITY carry a `pivot` and a `direction` rather than a value from a list.
    Reading an ordinal belief back as a label is what produced "you lean away from things close to
    home" for someone who had said a 1.2 km walk was too far: the old storage recorded the bucket
    the listing fell in, and this sentence dutifully read it back as its own opposite.
    """
    if preference.pivot is None or preference.direction is None:
        return None
    if preference.dimension is PreferenceDimension.DISTANCE:
        distance = _distance_words(preference.pivot)
        return (
            f"somewhere closer than about {distance}"
            if preference.direction == "lower"
            else f"somewhere about {distance} away, which has suited you"
        )
    if preference.dimension is PreferenceDimension.INTENSITY:
        index = int(preference.pivot)
        rung = INTENSITY_LADDER[index].value if 0 <= index < len(INTENSITY_LADDER) else None
        if preference.direction == "lower":
            return f"something gentler than {rung}" if rung else "the gentlest option there is"
        return f"something more active than {rung}" if rung else "something more active"
    return None


def _preference_value_phrase(preference: DimensionPreference) -> str:
    value = preference.value
    if preference.dimension is PreferenceDimension.DISTANCE:
        return "things a bit further from home" if value == "far" else "things close to home"
    if preference.dimension is PreferenceDimension.INTENSITY:
        return "gentler activities" if value == "light" else "more active activities"
    if preference.dimension is PreferenceDimension.TIMING:
        return f"activities in the {value}"
    if preference.dimension is PreferenceDimension.SOCIAL:
        return "activities with other people" if value == "social" else "activities on your own"
    if preference.dimension is PreferenceDimension.ENVIRONMENT:
        return f"{value} activities"
    if preference.dimension is PreferenceDimension.ACTIVITY_TYPE:
        return f"{activity_type_label(value).lower()}"
    return f"{value.lower()} activities"


def _inferred_confidence(evidence_count: int, *, confirmed: bool = False) -> FactConfidence:
    """Inferred facts top out at MEDIUM however much evidence accrues; only the person's own
    confirmation earns HIGH. Taps and days are evidence about behaviour, not about intent."""
    if confirmed:
        return FactConfidence.HIGH
    if evidence_count >= _MEDIUM_EVIDENCE:
        return FactConfidence.MEDIUM
    return FactConfidence.LOW


def _hour_phrase(hour: int) -> str:
    suffix = "am" if hour < 12 else "pm"
    twelve = hour % 12 or 12
    return f"{twelve}{suffix}"


def _identity_facts(inputs: WorldModelInputs) -> list[PersonFact]:
    source_type = FactSourceType.FIXTURE if inputs.is_synthetic_profile else FactSourceType.EXPLICIT
    source = "persona_profile" if inputs.is_synthetic_profile else "registration"
    facts: list[PersonFact] = []
    if inputs.preferred_language:
        facts.append(
            PersonFact(
                key="preferred_language",
                category=FactCategory.IDENTITY,
                statement=f"You prefer {inputs.preferred_language}.",
                value=inputs.preferred_language,
                source_type=source_type,
                source=source,
                confidence=FactConfidence.HIGH,
                evidence_count=1,
            )
        )
    if inputs.age is not None:
        facts.append(
            PersonFact(
                key="age",
                category=FactCategory.IDENTITY,
                statement=f"You are {inputs.age} years old.",
                value=str(inputs.age),
                source_type=source_type,
                source=source,
                confidence=FactConfidence.HIGH,
                evidence_count=1,
            )
        )
    if inputs.background:
        # A fixture biography is written about the persona in the third person (e.g. "has
        # disclosed knee discomfort"); framing it as a quoted profile note rather than rewriting
        # it into first person keeps it honestly labelled as someone else's description of them,
        # never as something the person said themselves. A real registration bio has no such
        # framing to add: it is already the person's own.
        statement = (
            f"Your profile note (from the demo persona this run uses): {inputs.background}"
            if inputs.is_synthetic_profile
            else inputs.background
        )
        facts.append(
            PersonFact(
                key="background",
                category=FactCategory.IDENTITY,
                statement=statement,
                value=inputs.background,
                source_type=source_type,
                source=source,
                confidence=FactConfidence.MEDIUM,
                evidence_count=1,
            )
        )
    return facts


def _routine_facts(inputs: WorldModelInputs) -> list[PersonFact]:
    baseline = inputs.baseline
    facts: list[PersonFact] = []
    if baseline.median_steps > 0:
        usable = round(baseline.data_quality * max(baseline.window_days, 1))
        confidence = (
            FactConfidence.LOW
            if baseline.data_quality < _THIN_BASELINE_QUALITY
            else FactConfidence.MEDIUM
            if baseline.window_days < 28
            else FactConfidence.HIGH
        )
        statement = (
            "Care+ is still learning what a usual day looks like for you."
            if confidence is FactConfidence.LOW
            else "Your usual amount of daily activity has settled into a steady pattern."
        )
        facts.append(
            PersonFact(
                key="typical_day_steps",
                category=FactCategory.ROUTINE,
                statement=statement,
                value=f"{baseline.median_steps:.0f}",
                source_type=FactSourceType.INFERRED,
                source="rolling_baseline",
                confidence=confidence,
                evidence_count=int(usable),
                last_observed_at=inputs.baseline_observed_at,
            )
        )
    if inputs.confirmed_reference is not None:
        confirmed = inputs.confirmed_reference
        facts.append(
            PersonFact(
                key="reference_steps",
                category=FactCategory.ROUTINE,
                statement="You told Care+ what counts as a normal day for you now.",
                value=f"{confirmed.steps:.0f}",
                source_type=FactSourceType.EXPLICIT,
                source="baseline_confirmation",
                confidence=FactConfidence.HIGH,
                evidence_count=1,
                first_observed_at=confirmed.decided_at,
                last_observed_at=confirmed.decided_at,
                confirmed=True,
                evidence_ids=[confirmed.confirmation_id],
            )
        )
    elif baseline.reference_steps > 0:
        facts.append(
            PersonFact(
                key="reference_steps",
                category=FactCategory.ROUTINE,
                statement=(
                    "Care+ still compares your days with how things were when it started, "
                    "until you say that has changed."
                ),
                value=f"{baseline.reference_steps:.0f}",
                source_type=FactSourceType.INFERRED,
                source="anchored_reference",
                confidence=(
                    FactConfidence.HIGH
                    if baseline.reference_window_days >= 14
                    else FactConfidence.LOW
                ),
                evidence_count=baseline.reference_window_days,
            )
        )
    if inputs.disputed_days:
        facts.append(
            PersonFact(
                key="disputed_days",
                category=FactCategory.ROUTINE,
                statement=(
                    "You told Care+ the tracker got some days wrong; those days are marked "
                    "as contested, not corrected."
                ),
                value=str(inputs.disputed_days),
                source_type=FactSourceType.EXPLICIT,
                source="day_disputes",
                confidence=FactConfidence.HIGH,
                evidence_count=inputs.disputed_days,
                confirmed=True,
            )
        )
    return facts


def _preference_facts(inputs: WorldModelInputs) -> list[PersonFact]:
    facts: list[PersonFact] = []
    for preference in inputs.preferences:
        stated = preference.source == "senior_statement"
        if preference.value == _EITHER_VALUE:
            label = _dimension_label(preference.dimension)
            if stated and preference.stated_text:
                statement = (
                    f"You said either is fine for {label} — in your own words, "
                    f'"{preference.stated_text}".'
                )
            elif stated:
                statement = f"You said either is fine for {label} — you told Care+ so."
            else:
                statement = f"You seem fine either way about {label}."
        elif (ordinal := ordinal_preference_phrase(preference)) is not None:
            # A line, not a lean. "You lean away from things close to home" is what this said
            # after someone told Care+ a 1.2 km walk was too far -- the opposite of what they
            # said, in the one place the product exists to show them what it believes.
            if stated and preference.stated_text:
                statement = f'You prefer {ordinal} — in your own words, "{preference.stated_text}".'
            elif stated:
                statement = f"You prefer {ordinal} — you told Care+ so."
            elif preference.source == "decline_reason":
                statement = f"You prefer {ordinal}, picked up from what you said no to."
            else:
                statement = f"You prefer {ordinal}, picked up from what you enjoyed."
        else:
            leaning = "towards" if preference.strength > 0 else "away from"
            phrase = _preference_value_phrase(preference)
            if stated and preference.stated_text:
                statement = (
                    f'You lean {leaning} {phrase} — in your own words, "{preference.stated_text}".'
                )
            elif stated:
                statement = f"You lean {leaning} {phrase} — you told Care+ so."
            elif preference.source == "decline_reason":
                statement = f"You lean {leaning} {phrase}, picked up from what you said no to."
            else:
                statement = f"You lean {leaning} {phrase}, picked up from what you enjoyed."
        facts.append(
            PersonFact(
                # Source is part of the key: a decline-tier and an enjoyment-tier belief about the
                # same value are two facts, not one, exactly as they are two rows.
                key=f"preference:{preference.dimension.value}:{preference.value}:{preference.source}",
                category=FactCategory.ACTIVITY_PREFERENCE,
                statement=statement,
                value=f"{'+' if preference.strength > 0 else '-'}{preference.value}",
                source_type=FactSourceType.EXPLICIT if stated else FactSourceType.INFERRED,
                source=f"dimension_preference:{preference.source}",
                confidence=_inferred_confidence(
                    preference.observations, confirmed=preference.confirmed
                ),
                evidence_count=preference.observations,
                first_observed_at=preference.first_observed_at,
                last_observed_at=preference.updated_at,
                expires_at=preference.expires_at,
                confirmed=preference.confirmed,
                stale=(
                    not stated
                    and preference.updated_at is not None
                    and (inputs.as_of_day - local_date(preference.updated_at)).days
                    > _STALE_AFTER_DAYS
                ),
            )
        )
    for goal in inputs.goals:
        if not goal.active:
            continue
        # `goal.text` may carry a "N times a week" suffix after a comma (`_goal_text` in
        # `sql_repository.py`); that count belongs on the goal's own row, not in a sentence read
        # back to the person, so only the label before it is used here.
        label = goal.text.split(",", 1)[0]
        facts.append(
            PersonFact(
                key=f"goal:{goal.kind.value}",
                category=FactCategory.ACTIVITY_PREFERENCE,
                statement=f"You want to {label[0].lower()}{label[1:]}.",
                value=goal.kind.value,
                source_type=FactSourceType.EXPLICIT,
                source="activity_goals",
                confidence=FactConfidence.HIGH,
                evidence_count=1,
                first_observed_at=goal.created_at,
                last_observed_at=goal.created_at,
                confirmed=True,
                evidence_ids=[goal.goal_id],
            )
        )
    # Resolved here when the caller did not resolve for us, so a hand-built `WorldModelInputs`
    # (a test, a probe) reports the same disagreements the repository's own read does -- goals
    # included, exactly as the repository resolves them. After the goal facts exist, because a
    # goal can be one side of a disagreement too.
    _mark_contradictions(
        facts,
        inputs.preferences,
        inputs.resolved or resolve(inputs.preferences, goals=inputs.goals),
        inputs.goals,
    )
    return facts


ContradictionOutcome = Literal["this_applies", "other_applies", "neither_applies", "undecided"]


def _mark_contradictions(
    facts: list[PersonFact],
    preferences: list[DimensionPreference],
    resolved: list[ResolvedPreference],
    goals: list[ActivityGoal],
) -> None:
    """Link preference facts about the same value that lean opposite ways.

    Shown, not settled here: precedence has already been applied in `preferences.resolve`, and
    this is only about making a live disagreement visible so the person can settle it themselves.

    The disagreements are **read** from `ResolvedPreference.contradicted_by` rather than derived
    a second time by pairing rows. Deriving them here is what made "That's right" produce a
    contradiction nobody held: agreeing with an inferred belief wrote a *second* row beside it,
    nothing consumed the first, and this function dutifully reported the person disagreeing with
    themselves. A consumed belief is superseded, so it is absent from `resolved` and cannot be
    cited by anything.

    `facts[i]` is the fact built from `preferences[i]`, so the lookup is by the row's own
    `(dimension, value, source)` key rather than by parsing a fact key -- a deprecated `category`
    value is free catalogue text and may contain anything, including the key separator.

    A goal is one side of a disagreement in its own right, named `goal:dimension:value` by the
    resolver (`preferences.goal_key`) and shown on its `goal:{kind}` fact. It resolves with the
    source `senior_statement`, so it is skipped when looking a *row* up -- read under the row key
    it overwrote the statement it disagreed with and reported that statement contradicting itself.
    "Your own words say otherwise" is said only of a statement: a goal is a choice from a list,
    not the person's own words.
    """
    resolved_by_key: dict[str, ResolvedPreference] = {
        (
            preference.supporting[0]
            if preference.supporting
            else f"{preference.dimension.value}:{preference.value}:{preference.source}"
        ): preference
        for preference in resolved
    }

    def in_effect(resolver_key: str) -> bool:
        belief = resolved_by_key.get(resolver_key)
        return belief is not None and belief_in_effect(belief)

    def outcome(resolver_key: str, others: list[str]) -> ContradictionOutcome:
        this = in_effect(resolver_key)
        other = any(in_effect(key) for key in others)
        if this and other:
            return "undecided"
        if this:
            return "this_applies"
        if other:
            return "other_applies"
        return "neither_applies"

    goal_fact_keys: dict[str, list[str]] = {}
    for goal in goals:
        mapping = GOAL_DIMENSION_VALUES.get(goal.kind)
        if mapping is None or not goal.active:
            continue
        keys = goal_fact_keys.setdefault(goal_key(*mapping), [])
        if f"goal:{goal.kind.value}" not in keys:
            keys.append(f"goal:{goal.kind.value}")

    def cited(others: list[str]) -> list[str]:
        return [
            fact_key
            for other in others
            for fact_key in (
                goal_fact_keys.get(other, []) if is_goal_key(other) else [f"preference:{other}"]
            )
        ]

    row_disagreements: dict[str, list[str]] = {}
    goal_disagreements: dict[str, list[str]] = {}
    stated_keys: set[str] = set()
    for preference in resolved:
        key = (
            preference.supporting[0]
            if preference.supporting
            else f"{preference.dimension.value}:{preference.value}:{preference.source}"
        )
        if is_goal_key(key):
            goal_disagreements[key] = preference.contradicted_by
            continue
        row_disagreements[key] = preference.contradicted_by
        if preference.source == "senior_statement":
            stated_keys.add(key)

    for index, preference in enumerate(preferences):
        key = f"{preference.dimension.value}:{preference.value}:{preference.source}"
        others = row_disagreements.get(key) or []
        contradicts = cited(others)
        fact = facts[index]
        if not contradicts:
            facts[index] = fact.model_copy(update={"in_effect": in_effect(key)})
            continue
        statement = fact.statement
        fact_outcome = outcome(key, others)
        # "Those win" is said only when it is true: the contradicting statement is the belief in
        # effect. When a higher-tier belief elsewhere on the axis outranks both (`neither_applies`)
        # or the tiers are equal (`undecided`), the person's words do not win, so it is not said.
        if (
            fact.source_type is FactSourceType.INFERRED
            and fact_outcome == "other_applies"
            and any(other in stated_keys and in_effect(other) for other in others)
        ):
            statement += " Your own words say otherwise, and those win."
        facts[index] = fact.model_copy(
            update={
                "contradicts": contradicts,
                "statement": statement,
                "in_effect": in_effect(key),
                "contradiction_outcome": fact_outcome,
            }
        )

    for resolver_key, fact_keys in goal_fact_keys.items():
        others = goal_disagreements.get(resolver_key) or []
        contradicts = cited(others)
        for index in range(len(preferences), len(facts)):
            if facts[index].key not in fact_keys:
                continue
            update: dict[str, object] = {"in_effect": in_effect(resolver_key)}
            if contradicts:
                update["contradicts"] = contradicts
                update["contradiction_outcome"] = outcome(resolver_key, others)
            facts[index] = facts[index].model_copy(update=update)


def _interaction_facts(inputs: WorldModelInputs) -> list[PersonFact]:
    # A seeded demo consent (`ConsentEvidenceRow.source == "synthetic_fixture"`) is nobody's own
    # choice -- it is a fixture activated on reset -- and must not read as `explicit`/`confirmed`
    # any more than the persona biography does. Only a person's own recorded consent earns that.
    consent_is_fixture = inputs.consent_source == "synthetic_fixture"
    facts: list[PersonFact] = [
        PersonFact(
            key="suggestions",
            category=FactCategory.INTERACTION,
            statement=(
                "Your suggestions are on."
                if inputs.consent_active
                else "Your suggestions are switched off."
            ),
            value="on" if inputs.consent_active else "off",
            source_type=FactSourceType.FIXTURE if consent_is_fixture else FactSourceType.EXPLICIT,
            source="consent_evidence",
            confidence=FactConfidence.MEDIUM if consent_is_fixture else FactConfidence.HIGH,
            evidence_count=1,
            last_observed_at=inputs.consent_recorded_at,
            confirmed=not consent_is_fixture,
            evidence_ids=[inputs.consent_evidence_id] if inputs.consent_evidence_id else [],
        )
    ]
    for mute in inputs.mutes:
        if not mute.suppressed:
            continue
        facts.append(
            PersonFact(
                key=f"mute:{mute.candidate_key}",
                category=FactCategory.INTERACTION,
                statement=f'You asked not to be offered "{mute.label}".',
                value=mute.candidate_key,
                source_type=FactSourceType.EXPLICIT,
                source="candidate_preferences",
                confidence=FactConfidence.HIGH,
                evidence_count=1,
                confirmed=True,
            )
        )
    # Dropped entirely under a simulated run: a demo can advance a week of simulated days inside
    # a real minute, so a reply's wall-clock hour would measure the operator's clicking, not a
    # routine -- a caveat nobody would read is worse than not showing the fact at all.
    if inputs.typical_response_hour is not None and not inputs.is_simulated_run:
        facts.append(
            PersonFact(
                key="typical_response_hour",
                category=FactCategory.INTERACTION,
                statement=f"You tend to reply around {_hour_phrase(inputs.typical_response_hour)}.",
                value=str(inputs.typical_response_hour),
                source_type=FactSourceType.INFERRED,
                source="outcome_timestamps",
                confidence=_inferred_confidence(inputs.typical_response_hour_sample),
                evidence_count=inputs.typical_response_hour_sample,
            )
        )
    return facts


def _context_facts(inputs: WorldModelInputs) -> list[PersonFact]:
    return [
        PersonFact(
            key=f"context_answer:{answer.question_id}",
            category=FactCategory.CONTEXT,
            statement=f'When Care+ asked about a quiet day, you said "{answer.label}".',
            value=answer.value,
            source_type=FactSourceType.EXPLICIT,
            source="context_question_answers",
            confidence=FactConfidence.HIGH,
            evidence_count=1,
            first_observed_at=answer.answered_at,
            last_observed_at=answer.answered_at,
            # Momentary: an answer about one quiet day lapses at the end of that day.
            expires_at=(
                at_local(answer.answered_on_day + timedelta(days=1), 0, 0)
                if answer.answered_on_day is not None
                else None
            ),
            confirmed=True,
            evidence_ids=[answer.answer_id],
        )
        for answer in inputs.context_answers
    ]


def _outreach_statement(response: OutreachResponseFact) -> str | None:
    """One sentence about what the person did with this kind of outreach, or nothing.

    Ordered strongest-answer-first, and every branch is something the person actually did:

      * they went; they asked to hear more; they said no; they said maybe later -- their own
        recorded answers, narrated as such, with their own one-tap reason when they gave one;
      * the response window closed without a reply -- narrated as the absence of a reply, never
        as a decision;
      * nothing recorded at all -- the offer is still open, possibly on the person's home page
        this very moment, so there is no fact about it yet and `None` is returned. An outcome
        that somebody *else* produced (a coordinator closing the case, activity recovering on
        its own) lands here too: it is not the person's answer and is not narrated as one.
    """
    if response.completed:
        return f'You were offered "{response.label}" and followed it through.'
    if response.accepted:
        return f'You were offered "{response.label}" and asked to hear more.'
    if response.declined:
        reason = (
            _DECLINE_REASON_CLAUSES.get(response.decline_reason)
            if response.decline_reason is not None
            else None
        )
        if reason:
            return f'You said no to "{response.label}", because {reason}.'
        return f'You said no to "{response.label}".'
    if response.deferred:
        return f'You were offered "{response.label}" and said maybe later.'
    if response.no_response:
        return f'You did not reply to "{response.label}".'
    return None


def _learned_response_facts(inputs: WorldModelInputs) -> list[PersonFact]:
    facts: list[PersonFact] = []
    for response in inputs.outreach_responses:
        if response.offered == 0:
            continue
        statement = _outreach_statement(response)
        if statement is None:
            continue
        facts.append(
            PersonFact(
                key=f"outreach:{response.candidate_key}",
                category=FactCategory.LEARNED_RESPONSE,
                statement=statement,
                value=f"{response.accepted}/{response.offered}",
                source_type=FactSourceType.INFERRED,
                source="intervention_outcomes",
                confidence=_inferred_confidence(response.offered),
                evidence_count=response.offered,
            )
        )
    # One fact per programme, never one per session of it: `ActivityHistoryFact` is already
    # series-level, and its docstring says why a per-session reading of the same rows told the
    # person they had been to sessions they had not.
    for history in inputs.activity_history:
        if not history.went:
            continue
        statement = f'You went to "{history.title}" before' + (
            " and enjoyed it." if history.enjoyed else "."
        )
        facts.append(
            PersonFact(
                key=f"activity:{history.series_key}",
                category=FactCategory.LEARNED_RESPONSE,
                statement=statement,
                value=f"{history.went}",
                source_type=FactSourceType.EXPLICIT,
                source="plan_follow_through",
                confidence=FactConfidence.HIGH,
                # The sessions actually attended, and nothing else: `enjoyed` used to be added on
                # top, which counted one outing the person reported on twice.
                evidence_count=history.went,
                confirmed=True,
            )
        )
    return facts


def _gaps(inputs: WorldModelInputs, facts: list[PersonFact]) -> list[str]:
    gaps = [
        "No routine by time of day is learned — every reading is a daily total.",
        "No weekday or weekend pattern is learned.",
        "No idea how weather affects you in particular.",
        "No home area or usual travel distance is recorded; distances are from a fixed listing.",
    ]
    if not any(fact.category is FactCategory.ACTIVITY_PREFERENCE for fact in facts):
        gaps.insert(
            0, "No activity preference is known yet; the first search or answer will start one."
        )
    elif not any(
        fact.category is FactCategory.ACTIVITY_PREFERENCE and fact.confirmed for fact in facts
    ):
        gaps.insert(
            0,
            "No activity preference has been confirmed by you yet; everything known is inferred.",
        )
    return gaps


def build_world_model(inputs: WorldModelInputs) -> PersonWorldModel:
    facts = [
        *_identity_facts(inputs),
        *_routine_facts(inputs),
        *_preference_facts(inputs),
        *_interaction_facts(inputs),
        *_context_facts(inputs),
        *_learned_response_facts(inputs),
    ]
    quality = WorldModelQuality(
        facts=len(facts),
        explicit=sum(1 for f in facts if f.source_type is FactSourceType.EXPLICIT),
        inferred=sum(1 for f in facts if f.source_type is FactSourceType.INFERRED),
        external=sum(1 for f in facts if f.source_type is FactSourceType.EXTERNAL),
        fixture=sum(1 for f in facts if f.source_type is FactSourceType.FIXTURE),
        confirmed=sum(1 for f in facts if f.confirmed),
        single_evidence=sum(
            1 for f in facts if f.evidence_count <= 1 and f.source_type is FactSourceType.INFERRED
        ),
        temporary=sum(1 for f in facts if f.expires_at is not None),
        expired_excluded=inputs.expired_preferences,
        # One disagreement, however many facts sit on each side of it.
        contradictions=len({frozenset({f.key, *f.contradicts}) for f in facts if f.contradicts}),
        stale=sum(1 for f in facts if f.stale),
    )
    return PersonWorldModel(
        person_id=inputs.person_id,
        as_of_day=inputs.as_of_day,
        facts=facts,
        gaps=_gaps(inputs, facts),
        quality=quality,
    )
