"""The evaluator-only Activity Ranker Inspector: one ranking execution, as a structured trace.

Pure: no database, no network, no clock except the timestamps a caller passes. The repository
reads the person's inputs (`SqlAlchemyRepository._ranking_inputs`) and hands them here; the only
side-effecting step, the optional bounded LLM re-rank, is injected as a callable.

What this module guarantees:

  * **No second ranker.** Every order, score, filter outcome and reason comes from
    `activity_search.rank_with_trace`, the function `search_activities` itself runs. This module
    converts that execution into Pydantic and classifies it; it never scores anything.
  * **Previews use the production learners.** A history preset, a counterfactual or a feedback
    preview edits copies of the inputs through `preferences.apply_decline`,
    `preferences.apply_enjoyment` and `activity_search.count_engagement`, then re-resolves --
    a stale `resolved` would silently ignore every edit.
  * **Nothing a model or a person wrote freely leaves**, with one named exception. No agent
    reasoning, proposal, prompt, read-tool arguments, tool summaries, guardrail rejection text or
    exception text; no `stated_text` or goal text. LLM unparsed terms are kept only when they
    appear in the request (the rest are counted, `unparsed_terms_withheld`). The exception is an
    LLM-parsed `language`: the filter, the reason lines and the "understood" lines all used that
    exact value, so withholding it would make the trace misdescribe what filtered. It is kept,
    and flagged `language_model_supplied_ungrounded` when it does not appear in the request text.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal

from pydantic import ValidationError

from silverloop.activity_rerank import build_ranking_context, merge_planner_order
from silverloop.activity_search import (
    DECLINE_COOLDOWN_DAYS,
    DIVERSITY_SCORE_MARGIN,
    DIVERSITY_TOP_N,
    ENGAGEMENT_WEIGHTS,
    FILTER_RULE_NAMES,
    RANKING_FACTOR_DESCRIPTIONS,
    RANKING_WEIGHTS,
    REASON_BASIS_FACTOR,
    ActivityEngagement,
    RankingExecution,
    ScoredCandidate,
    constrained_dimensions,
    count_engagement,
    engagement_by_series,
    in_decline_cooldown,
    rank_with_trace,
    scorable_preferences,
    series_key,
    series_keys_for,
    travel_cost_start_for,
)
from silverloop.agent.constants import (
    MAX_ACTIVITY_OPTIONS_RETURNED,
    MAX_PROMOTION,
    MIN_SHOWN_AFTER_NARROWING,
)
from silverloop.agent.guardrail_rules import count_violations_by_rule
from silverloop.agent.planner import ActivityPlanRun
from silverloop.agent.tools import PROPOSE_ACTIVITY_ORDER_TOOL_NAME, ActivityRankingContext
from silverloop.evaluator_presets import (
    SCRIPTED_ORIGIN_PREFIX,
    HistoryPreset,
    first_session,
    programme_key,
)
from silverloop.intent import describe_intent
from silverloop.local_time import at_local
from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityGoal,
    ActivityIntensity,
    ActivityIntent,
    ActivityOfferResponse,
    ActivityPreferences,
    ActivityRankingTrace,
    CandidateIntegrity,
    CandidateTrace,
    DeclineReason,
    DimensionPreference,
    FilterOutcome,
    IndoorOutdoor,
    IntegrityFinding,
    IntentParser,
    PlannedFollowThrough,
    PreferenceDimension,
    RankChange,
    RankedActivity,
    RankerCounterfactual,
    RankerFeedbackKind,
    RankerFeedbackPreview,
    ReasonBasis,
    ReasonWithoutPositiveFactor,
    ResolvedPreference,
    SocialPreference,
    SourceTier,
    TimeWindow,
    TraceApplied,
    TraceCatalogueUnknown,
    TraceEngagement,
    TraceEngagementCounts,
    TraceFact,
    TraceFiltering,
    TraceFilterOutcome,
    TraceFinalRecommendations,
    TraceIntegrity,
    TraceIntentAxis,
    TraceIntentPlanner,
    TraceLearningPreview,
    TraceLlmRerank,
    TraceParsedIntent,
    TracePerson,
    TracePersonContext,
    TracePlannerMovement,
    TracePostProcessing,
    TracePreferenceAxis,
    TraceRecommendation,
    TraceRequest,
    TraceRequestAxis,
    TraceRetrieval,
    TraceScoring,
    TraceScriptedEvent,
    TraceScriptedHistory,
    TraceSeriesDedupe,
    TraceSeriesDeferral,
    TraceSort,
    TraceSortKey,
    TraceSortKeyField,
    TraceStagePositions,
    TraceToolCall,
    TraceVariety,
    TraceVarietyConsidered,
    TraceVarietySwap,
    TraceWebCard,
    TraceWorldModelEffect,
    UnknownAxis,
)
from silverloop.ontology import ActivityType
from silverloop.preferences import (
    NEARBY_RADIUS_M,
    STATED_VALUE_VOCABULARY,
    UTILITY_DIMENSIONS,
    Tri,
    apply_decline,
    apply_enjoyment,
    is_stated_tier,
    leans_near,
    observation_for,
    resolve,
    travel_beliefs,
    travel_tolerance_basis,
    travel_tolerance_m,
    utility_beliefs,
)

SHOWN_LIMIT: Final[int] = 3
PREVIEW_ORIGIN: Final[str] = "preview:feedback"
COUNTERFACTUAL_ORIGIN: Final[str] = "counterfactual:"

# The factor a positive contribution must be explained by, and the reason basis that explains it.
# `repetition` and `friction` are never positive (see `activity_search.RANKING_WEIGHTS`).
FACTOR_BASIS: Final[dict[str, ReasonBasis]] = {
    factor: basis for basis, factor in REASON_BASIS_FACTOR.items()
}

# Values tried, one hypothetical stated like at a time, to measure whether an unknown axis could
# change the top three. Bounded on purpose; ACTIVITY_TYPE is bounded to the kinds actually kept.
_MATERIALITY_VALUES: Final[dict[PreferenceDimension, tuple[str, ...]]] = {
    PreferenceDimension.SOCIAL: (SocialPreference.SOCIAL.value, SocialPreference.SOLO.value),
    PreferenceDimension.ENVIRONMENT: ("indoor", "outdoor", "sheltered"),
    PreferenceDimension.TIMING: ("morning", "afternoon", "evening"),
    PreferenceDimension.INTENSITY: (
        ActivityIntensity.LIGHT.value,
        ActivityIntensity.MODERATE.value,
    ),
}

_CLASS_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,80}$")
_KNOWN_ACTIVITY_TOOLS: Final[frozenset[str]] = frozenset(
    {"get_activity_options", PROPOSE_ACTIVITY_ORDER_TOOL_NAME}
)

PlanRanking = Callable[[ActivityRankingContext, list[str]], ActivityPlanRun]


class RankerRequestError(Exception):
    """An inspection request outside the allow-list: an unknown or another person's preset, an
    unknown listing, or a counterfactual the production write path would refuse. 422."""


class RankerPersonNotFound(Exception):
    """The person asked about does not exist. 404."""


class RankerInspectorDefect(Exception):  # noqa: N818 - named for what it reports
    """An unexpected failure inside the inspector. Deliberately neither `KeyError` nor
    `ValueError`, so the app-wide 404/422 handlers cannot relabel it; it surfaces as a 500."""


# ── Inputs ────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InspectionState:
    """Everything one inspected ranking reads. Previews return edited copies; nothing mutates."""

    person_id: str
    display_name: str
    run_id: str
    today: date
    catalogue: list[ActivityCandidate]
    dimensions: list[DimensionPreference]
    goals: list[ActivityGoal]
    offers: list[tuple[str, str, date]]
    follow_through: list[tuple[str, str]]
    verdicts: list[tuple[str, str]]
    rain_forecast: bool
    consent_active: bool
    rain_source: Literal["simulation_context", "counterfactual"] = "simulation_context"
    # `dimension:value:source` keys of the rows the person actually holds (live state), and of the
    # rows a scripted preset or a preview touched. A key in both is live evidence a preset added
    # to; a key only in `scripted_keys` exists because of the preset alone.
    live_keys: frozenset[str] = frozenset()
    scripted_keys: frozenset[str] = frozenset()
    preview_keys: frozenset[str] = frozenset()
    # `origin_id -> series_key` for the origins the stored rows name (read-only, filled by the
    # repository), plus each synthetic origin a preview folds. `preferences.apply_decline` reads
    # it so a second item-level answer about the *same* programme widens nothing in a preview,
    # exactly as it widens nothing in production. Empty means unknown: today's behaviour.
    origin_series: Mapping[str, str] = field(default_factory=dict)

    def preferences(self) -> ActivityPreferences:
        """Re-resolved from the (possibly edited) rows, exactly as the repository resolves them."""
        return ActivityPreferences(
            person_id=self.person_id,
            dimensions=list(self.dimensions),
            resolved=resolve(self.dimensions, self.today, self.run_id, goals=self.goals),
        )

    def engagement(self) -> dict[str, ActivityEngagement]:
        counted = count_engagement(self.offers, self.follow_through, self.verdicts)
        return engagement_by_series(
            counted.counts,
            counted.last_declined,
            counted.answered,
            series_keys_for(self.catalogue),
        )


@dataclass(frozen=True)
class ParsedRequest:
    intent: ActivityIntent
    source: Literal["text", "chips", "none"]
    raw_text: str | None
    intent_mode: str
    intent_planner_ran: bool
    unparsed_terms_withheld: int = 0
    language_model_supplied_ungrounded: bool = False


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool
    provider: str
    model: str | None
    max_iterations: int


def row_key(preference: DimensionPreference) -> str:
    return f"{preference.dimension.value}:{preference.value}:{preference.source}"


def _changed_keys(
    before: Sequence[DimensionPreference], after: Sequence[DimensionPreference]
) -> frozenset[str]:
    previous = {row_key(row): row for row in before}
    return frozenset(row_key(row) for row in after if previous.get(row_key(row)) != row)


@dataclass(frozen=True)
class SanitisedIntent:
    intent: ActivityIntent
    unparsed_terms_withheld: int
    language_model_supplied_ungrounded: bool


def sanitise_intent(parsed: ActivityIntent) -> SanitisedIntent:
    """Check an LLM-parsed intent's free-text fields against the request text itself.

    `unparsed_terms` are shown back to the person and rank nothing, so a term that does not
    appear in the request is withheld and counted. `language` is different: the hard filter, the
    INTENT reason line and the "understood" lines all used that exact value, so it is kept (the
    trace must describe what filtered) and flagged when the request text does not contain it.
    Keyword and chip intents are the person's own and pass through unchanged.
    """
    if parsed.parsed_by is not IntentParser.LLM:
        return SanitisedIntent(parsed, 0, False)
    haystack = (parsed.raw_text or "").casefold()
    kept = [term for term in parsed.unparsed_terms if term.casefold() in haystack]
    return SanitisedIntent(
        intent=parsed.model_copy(update={"unparsed_terms": kept}),
        unparsed_terms_withheld=len(parsed.unparsed_terms) - len(kept),
        language_model_supplied_ungrounded=(
            parsed.language is not None and parsed.language.strip().casefold() not in haystack
        ),
    )


# ── Previews ──────────────────────────────────────────────────────────────────────────────────


def _noon(day: date) -> datetime:
    return datetime.combine(day, time(12, 0), tzinfo=UTC)


def apply_history_preset(
    state: InspectionState, preset: HistoryPreset
) -> tuple[InspectionState, TraceScriptedHistory]:
    """Fold a scripted history through the production learners on top of live state.

    Events are applied oldest first. Their search-card answers are placed before the live ones:
    production counts answers in the order they were recorded, and a scripted "days ago" answer
    stands for something recorded before anything live.
    """
    dimensions = list(state.dimensions)
    offers: list[tuple[str, str, date]] = []
    follow_through = list(state.follow_through)
    verdicts = list(state.verdicts)
    origin_series = dict(state.origin_series)
    events: list[TraceScriptedEvent] = []
    ordered = sorted(enumerate(preset.events), key=lambda item: -item[1].days_ago)
    for index, event in ordered:
        candidate = first_session(state.catalogue, event.programme_key)
        if candidate is None:
            continue
        origin_id = f"{SCRIPTED_ORIGIN_PREFIX}{preset.preset_id}:{index}"
        day = state.today - timedelta(days=event.days_ago)
        now = _noon(day)
        if event.kind == "not_for_me":
            offers.append((candidate.activity_id, ActivityOfferResponse.NOT_FOR_ME.value, day))
            # The synthetic origin names its programme before folding, as a stored one does, so
            # a later same-programme answer -- scripted or previewed -- widens nothing.
            origin_series[origin_id] = series_key(candidate)
            dimensions = apply_decline(
                dimensions,
                event.reason,
                candidate,
                now,
                clarification=event.clarification,
                origin_id=origin_id,
                series=origin_series[origin_id],
                origin_series=origin_series,
            )
        elif event.kind == "interested":
            offers.append((candidate.activity_id, ActivityOfferResponse.INTERESTED.value, day))
        else:
            assert event.enjoyment is not None
            follow_through.append((candidate.activity_id, PlannedFollowThrough.WENT.value))
            verdicts.append((candidate.activity_id, event.enjoyment.value))
            dimensions = apply_enjoyment(
                dimensions, event.enjoyment, list(event.liked), candidate, now, origin_id=origin_id
            )
        events.append(
            TraceScriptedEvent(
                origin_id=origin_id,
                kind=event.kind,
                programme_key=event.programme_key,
                activity_id=candidate.activity_id,
                days_ago=event.days_ago,
                reason=event.reason,
                clarification=event.clarification,
                enjoyment=event.enjoyment,
                liked=list(event.liked),
            )
        )
    scripted = _changed_keys(state.dimensions, dimensions)
    return (
        replace(
            state,
            dimensions=dimensions,
            offers=[*offers, *state.offers],
            follow_through=follow_through,
            verdicts=verdicts,
            scripted_keys=state.scripted_keys | scripted,
            origin_series=origin_series,
        ),
        TraceScriptedHistory(preset_id=preset.preset_id, person_id=preset.person_id, events=events),
    )


def apply_request_counterfactual(
    intent: ActivityIntent, counterfactual: RankerCounterfactual | None
) -> ActivityIntent:
    """A request counterfactual, applied to a copy of the intent and re-validated."""
    if counterfactual is None or counterfactual.request is None:
        return intent
    updates = counterfactual.request.model_dump(exclude_none=True, mode="json")
    if not updates:
        return intent
    try:
        return ActivityIntent.model_validate({**intent.model_dump(mode="json"), **updates})
    except ValidationError as error:
        raise RankerRequestError(
            f"The request counterfactual does not make a valid request "
            f"({error.error_count()} error(s))."
        ) from error


def apply_world_counterfactual(
    state: InspectionState, counterfactual: RankerCounterfactual | None
) -> tuple[InspectionState, list[TraceWorldModelEffect]]:
    """World and world-model counterfactuals. Raises `ValueError` for an unknown listing or a day
    already past."""
    if counterfactual is None:
        return state, []
    effects: list[TraceWorldModelEffect] = []
    catalogue = state.catalogue
    rain_forecast, rain_source = state.rain_forecast, state.rain_source
    if counterfactual.world is not None:
        if counterfactual.world.rain is not None:
            rain_forecast, rain_source = counterfactual.world.rain, "counterfactual"
        known = {candidate.activity_id for candidate in catalogue}
        unknown = [key for key in counterfactual.world.mark_full if key not in known]
        if unknown:
            raise RankerRequestError(f"Unknown activity id(s) in mark_full: {', '.join(unknown)}")
        full = set(counterfactual.world.mark_full)
        catalogue = [
            candidate.model_copy(update={"availability": ActivityAvailability.FULL})
            if candidate.activity_id in full
            else candidate
            for candidate in catalogue
        ]
    dimensions = list(state.dimensions)
    world_model = counterfactual.world_model
    if world_model is not None:
        now = _noon(state.today)
        if world_model.travel_ceiling_m is not None:
            before = travel_tolerance_m(
                resolve(dimensions, state.today, state.run_id, goals=state.goals)
            )
            template = catalogue[0] if catalogue else None
            if template is not None:
                dimensions = apply_decline(
                    dimensions,
                    DeclineReason.TOO_FAR,
                    template.model_copy(update={"distance_m": world_model.travel_ceiling_m}),
                    now,
                    origin_id=f"{COUNTERFACTUAL_ORIGIN}travel_ceiling_m",
                )
            after = travel_tolerance_m(
                resolve(dimensions, state.today, state.run_id, goals=state.goals)
            )
            if after != before:
                effects.append(TraceWorldModelEffect(control="travel_ceiling_m", effect="applied"))
            else:
                effects.append(
                    TraceWorldModelEffect(
                        control="travel_ceiling_m",
                        effect="no_effect",
                        no_effect_reason=(
                            "not_below_tolerance"
                            if world_model.travel_ceiling_m >= before
                            else "outranked_by_higher_tier"
                        ),
                    )
                )
        if world_model.temporary_avoid_activity_type is not None:
            kind = world_model.temporary_avoid_activity_type
            # The same two refusals `state_preference` makes for this statement.
            if kind.value not in STATED_VALUE_VOCABULARY[PreferenceDimension.ACTIVITY_TYPE]:
                raise RankerRequestError(f"activity_type cannot be stated as {kind.value}.")
            until = world_model.temporary_avoid_until or state.today + timedelta(days=6)
            if until < state.today:
                raise RankerRequestError("temporary_avoid_until has already passed.")
            dimensions = confirm_statement_in_memory(
                dimensions,
                PreferenceDimension.ACTIVITY_TYPE,
                kind.value,
                strength=-1.0,
                expires_at=at_local(until, 23, 59),
                now=now,
            )
            effects.append(
                TraceWorldModelEffect(control="temporary_avoid_activity_type", effect="applied")
            )
    changed = _changed_keys(state.dimensions, dimensions)
    return (
        replace(
            state,
            catalogue=catalogue,
            rain_forecast=rain_forecast,
            rain_source=rain_source,
            dimensions=dimensions,
            preview_keys=state.preview_keys | changed,
        ),
        effects,
    )


def confirm_statement_in_memory(
    dimensions: list[DimensionPreference],
    dimension: PreferenceDimension,
    value: str,
    *,
    strength: float,
    expires_at: datetime | None,
    now: datetime,
) -> list[DimensionPreference]:
    """What `SqlAlchemyRepository._confirm_dimension_preference` leaves behind, over copies.

    That method is written against ORM rows (it reads and stamps `preference_id`s, `run_id` and
    rows the ranker never loads), so it is mirrored here rather than shared; parity with the real
    `PUT .../activity-preferences/{dimension}/{value}` is pinned by a test. Mirrored rule by rule:

      * an existing statement on the key is updated in place (strength, `confirmed`, one
        observation, a restarted first-observed stamp and dropped `stated_text` on a reversed
        stance, `superseded_by` cleared), otherwise a new statement is added;
      * `expires_at` and the evidence split are set from the statement itself;
      * every *non-superseded* learned row on the key is consumed (`superseded_by` stamped), and
        only when one was consumed does the statement's `origin_id` name it -- which is what
        makes it `RATIFIED` rather than `STATED` once the time box lapses. Already-superseded rows
        are left untouched.

    Only the rows the ranker holds are visible here: an inactive (expired or other-run) row on the
    key, which the real method would also update or consume, is not, and changes nothing the
    ranker reads today.
    """
    statement_marker = f"{COUNTERFACTUAL_ORIGIN}statement:{dimension.value}:{value}"
    same_key = [
        index
        for index, row in enumerate(dimensions)
        if row.dimension is dimension and row.value == value
    ]
    statement_index = next(
        (index for index in same_key if dimensions[index].source == "senior_statement"), None
    )
    consumed = [
        index
        for index in same_key
        if dimensions[index].source != "senior_statement"
        and dimensions[index].superseded_by is None
    ]
    updated = list(dimensions)
    for index in consumed:
        updated[index] = updated[index].model_copy(
            update={"superseded_by": statement_marker, "updated_at": now}
        )
    evidence = {
        "positive_evidence": 1.0 if strength >= 0 else 0.0,
        "negative_evidence": 0.0 if strength >= 0 else 1.0,
    }
    if statement_index is None:
        statement = DimensionPreference(
            dimension=dimension,
            value=value,
            strength=strength,
            source="senior_statement",
            confirmed=True,
            observations=1,
            updated_at=now,
            first_observed_at=now,
            expires_at=expires_at,
            **evidence,
        )
    else:
        existing = dimensions[statement_index]
        reversed_stance = (existing.strength > 0) != (strength > 0)
        statement = existing.model_copy(
            update={
                "strength": strength,
                "confirmed": True,
                "observations": 1,
                "updated_at": now,
                "first_observed_at": (
                    now
                    if reversed_stance or existing.first_observed_at is None
                    else existing.first_observed_at
                ),
                "stated_text": None if reversed_stance else existing.stated_text,
                "superseded_by": None,
                "expires_at": expires_at,
                **evidence,
            }
        )
    if consumed:
        last = dimensions[consumed[-1]]
        statement = statement.model_copy(
            update={"origin_id": f"{COUNTERFACTUAL_ORIGIN}consumed:{row_key(last)}"}
        )
    if statement_index is None:
        updated.append(statement)
    else:
        updated[statement_index] = statement
    return updated


@dataclass(frozen=True)
class FeedbackOutcome:
    state: InspectionState
    candidate: ActivityCandidate
    teaches_dimension: bool
    engagement_before: ActivityEngagement | None
    engagement_after: ActivityEngagement | None


def apply_feedback(
    state: InspectionState, feedback: RankerFeedbackPreview, *, duplicate_same_day: bool
) -> FeedbackOutcome:
    """Fold one previewed response through the production learners and the engagement counter.

    `not_for_me` records the answer and, unless it repeats today's same answer, folds its reason
    through `apply_decline`. `interested` records the answer and teaches no dimension (true in
    production). `enjoyment` records a `went` report and the verdict (as a plan report would) and
    folds liked aspects through `apply_enjoyment`. Raises `ValueError` for an unknown listing.
    """
    candidate = next(
        (item for item in state.catalogue if item.activity_id == feedback.activity_id), None
    )
    if candidate is None:
        raise RankerRequestError(f"Unknown activity id: {feedback.activity_id}")
    before_engagement = state.engagement().get(candidate.activity_id)
    now = _noon(state.today)
    dimensions = list(state.dimensions)
    offers = list(state.offers)
    follow_through = list(state.follow_through)
    verdicts = list(state.verdicts)
    origin_series = dict(state.origin_series)
    if feedback.response is RankerFeedbackKind.NOT_FOR_ME:
        offers.append((candidate.activity_id, ActivityOfferResponse.NOT_FOR_ME.value, state.today))
        if not duplicate_same_day:
            origin_series[PREVIEW_ORIGIN] = series_key(candidate)
            dimensions = apply_decline(
                dimensions,
                feedback.reason,
                candidate,
                now,
                clarification=feedback.clarification,
                origin_id=PREVIEW_ORIGIN,
                series=origin_series[PREVIEW_ORIGIN],
                origin_series=origin_series,
            )
    elif feedback.response is RankerFeedbackKind.INTERESTED:
        offers.append((candidate.activity_id, ActivityOfferResponse.INTERESTED.value, state.today))
    else:
        assert feedback.enjoyment is not None
        follow_through.append((candidate.activity_id, PlannedFollowThrough.WENT.value))
        verdicts.append((candidate.activity_id, feedback.enjoyment.value))
        dimensions = apply_enjoyment(
            dimensions,
            feedback.enjoyment,
            list(feedback.liked),
            candidate,
            now,
            origin_id=PREVIEW_ORIGIN,
        )
    changed = _changed_keys(state.dimensions, dimensions)
    updated = replace(
        state,
        dimensions=dimensions,
        offers=offers,
        follow_through=follow_through,
        verdicts=verdicts,
        preview_keys=state.preview_keys | changed,
        origin_series=origin_series,
    )
    return FeedbackOutcome(
        state=updated,
        candidate=candidate,
        teaches_dimension=bool(changed),
        engagement_before=before_engagement,
        engagement_after=updated.engagement().get(candidate.activity_id),
    )


# ── Person context ────────────────────────────────────────────────────────────────────────────


def fact_key(preference: ResolvedPreference) -> str:
    """How a resolved belief is named in a trace: the resolver's own first supporting key --
    `dimension:value:source` for a stored row, `goal:dimension:value` for a goal
    (`preferences.goal_key`). `resolve` always sets at least one."""
    return preference.supporting[0]


FactProvenanceValue = Literal["person_said", "learned", "temporary", "goal", "scripted_history"]


def _live_provenance(
    source: str, tier: SourceTier | None
) -> Literal["person_said", "learned", "temporary", "goal"]:
    if tier is SourceTier.STATED_GOAL:
        return "goal"
    if source == "senior_statement":
        return "temporary" if tier is SourceTier.TEMPORARY_STATED else "person_said"
    return "learned"


def _provenance(
    source: str, tier: SourceTier | None, key: str, state: InspectionState
) -> tuple[FactProvenanceValue, bool]:
    """`(provenance, scripted_contribution)`.

    A row the preset alone produced is `scripted_history`. A row the person already held keeps
    its live provenance even when a preset folded more evidence into it, and says so with
    `scripted_contribution` -- labelling the merged belief "scripted" would disown the live
    evidence behind it, and labelling it "learned" alone would hide the scripted part.
    """
    scripted = key in state.scripted_keys
    if tier is SourceTier.STATED_GOAL:
        return "goal", False
    if scripted and key not in state.live_keys:
        return "scripted_history", True
    return _live_provenance(source, tier), scripted


def used_beliefs(
    preferences: ActivityPreferences,
    intent: ActivityIntent,
    execution: RankingExecution | None,
) -> tuple[list[ResolvedPreference], list[ResolvedPreference], list[ResolvedPreference]]:
    """`(scorable, walked, travel)`: the beliefs this search may score, the ones preference
    utility actually walked, and the DISTANCE lines friction read.

    Taken from the executed `ScoreDetail` when anything was scored -- every candidate's detail
    carries the same set -- and otherwise from the very functions scoring calls
    (`activity_search.scorable_preferences`, `preferences.utility_beliefs`), never from a copy.
    """
    if execution is not None and execution.scored:
        detail = execution.scored[0].detail
        scorable = list(detail.scorable)
        walked = [belief.preference for belief in detail.preference.beliefs]
    else:
        scorable = scorable_preferences(preferences, intent)
        walked = utility_beliefs(scorable)
    return scorable, walked, travel_beliefs(preferences.resolved)


def _distance_not_used_reason(
    preference: ResolvedPreference, *, winning: bool
) -> Literal["not_winning_tier", "never_widens", "no_distance_line"]:
    """Why `travel_tolerance_m` did not read a DISTANCE belief. DISTANCE is never a deprecated
    axis: it is scored, by `travel_utility` alone.

    A learned belief with no pivot predates the ordinal axis and has no line to read:
    `no_distance_line`. A stated belief with no number that leans *far* -- "far" liked or "near"
    avoided -- is never read whatever its tier, because a statement with no number only ever
    narrows how far is comfortable: `never_widens`. Anything else left unread -- a line, or a
    near-leaning statement -- was outranked in its group: `not_winning_tier`.
    """
    if preference.pivot is None and not is_stated_tier(preference.tier):
        return "no_distance_line"
    if preference.pivot is None and not leans_near(preference):
        return "never_widens"
    if not winning:
        return "not_winning_tier"
    return "never_widens"


def trace_facts(
    state: InspectionState,
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    execution: RankingExecution | None = None,
) -> list[TraceFact]:
    """Every resolved belief the ranker read, whether and why it was used, then every stored row
    the resolver held back (`recorded_not_applied`).

    `used_in_scoring` comes from what scoring used (`used_beliefs`); `not_used_reason` only names
    which rule left an unused belief out.
    """
    scorable, walked, travel = used_beliefs(preferences, intent, execution)
    facts: list[TraceFact] = []
    applied_keys: set[str] = set()
    for preference in preferences.resolved:
        key = fact_key(preference)
        applied_keys.add(key)
        winning = preference.tier == preference.winning_tier
        used = preference in walked or preference in travel
        reason: str | None = None
        if not used:
            if preference.dimension is PreferenceDimension.DISTANCE:
                reason = _distance_not_used_reason(preference, winning=winning)
            elif preference.dimension not in UTILITY_DIMENSIONS:
                reason = "deprecated_axis"
            elif not winning:
                reason = "not_winning_tier"
            elif preference not in scorable:
                reason = "constrained_by_request"
            else:
                reason = "zero_strength"
        provenance, scripted_contribution = _provenance(
            preference.source, preference.tier, key, state
        )
        facts.append(
            TraceFact(
                fact_key=key,
                dimension=preference.dimension,
                value=preference.value,
                pivot=preference.pivot,
                direction=preference.direction,
                sentiment=preference.sentiment,
                strength=preference.strength,
                confidence=preference.confidence,
                positive_evidence=preference.positive_evidence,
                negative_evidence=preference.negative_evidence,
                evidence_count=preference.evidence_count,
                tier=preference.tier.name.lower(),
                winning=winning,
                provenance=provenance,
                scripted_contribution=scripted_contribution,
                source=preference.source,
                scope=preference.scope,
                expires_on_day=preference.expires_on_day,
                used_in_scoring=used,
                not_used_reason=reason,  # type: ignore[arg-type]
                contradicted_by=list(preference.contradicted_by),
                changed_by_preview=key in state.preview_keys,
            )
        )
    for row in state.dimensions:
        key = row_key(row)
        if key in applied_keys:
            continue
        observation = observation_for(row, today=state.today)
        if observation.superseded_by is not None:
            continue
        if observation.expires_on_day is not None and observation.expires_on_day < state.today:
            not_applied: Literal["held_back_item_level", "expired", "no_evidence"] = "expired"
        elif observation.positive_evidence + observation.negative_evidence <= 0:
            not_applied = "no_evidence"
        else:
            not_applied = "held_back_item_level"
        provenance, scripted_contribution = _provenance(
            row.source, observation.source_tier, key, state
        )
        facts.append(
            TraceFact(
                fact_key=key,
                dimension=row.dimension,
                value=row.value,
                pivot=row.pivot,
                direction=row.direction,
                sentiment="like" if row.strength >= 0 else "avoid",
                strength=row.strength,
                positive_evidence=observation.positive_evidence,
                negative_evidence=observation.negative_evidence,
                evidence_count=int(
                    round(observation.positive_evidence + observation.negative_evidence)
                ),
                provenance=provenance,
                scripted_contribution=scripted_contribution,
                source=row.source,
                scope=row.scope,
                expires_on_day=observation.expires_on_day,
                status="recorded_not_applied",
                not_applied_reason=not_applied,
                used_in_scoring=False,
                not_used_reason="recorded_not_applied",
                changed_by_preview=key in state.preview_keys,
            )
        )
    return facts


def unknown_axes(
    state: InspectionState,
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    execution: RankingExecution,
    engagement: dict[str, ActivityEngagement],
) -> list[UnknownAxis]:
    """Axes nothing is known about that the request left open, each with its materiality.

    Materiality re-runs `rank_with_trace` once per tested value with a single hypothetical stated
    like added to the rows, and reports whether the deterministic top three changed.
    """
    known = {preference.dimension for preference in preferences.resolved}
    constrained = constrained_dimensions(intent)
    baseline_top = execution.order_after_variety[:SHOWN_LIMIT]
    kept_kinds = sorted(
        {
            candidate.activity_type.value
            for candidate in execution.kept
            if candidate.activity_type is not None
            and candidate.activity_type is not ActivityType.OTHER
        }
    )
    values = {**_MATERIALITY_VALUES, PreferenceDimension.ACTIVITY_TYPE: tuple(kept_kinds)}
    now = _noon(state.today)
    axes: list[UnknownAxis] = []
    for dimension in (
        PreferenceDimension.SOCIAL,
        PreferenceDimension.ENVIRONMENT,
        PreferenceDimension.TIMING,
        PreferenceDimension.INTENSITY,
        PreferenceDimension.ACTIVITY_TYPE,
    ):
        if dimension in known or dimension in constrained:
            continue
        tested = list(values[dimension])
        changing: list[str] = []
        for value in tested:
            hypothetical = DimensionPreference(
                dimension=dimension,
                value=value,
                strength=1.0,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=now,
                positive_evidence=1.0,
            )
            rows = [*state.dimensions, hypothetical]
            rerun = rank_with_trace(
                state.catalogue,
                intent,
                ActivityPreferences(
                    person_id=state.person_id,
                    dimensions=rows,
                    resolved=resolve(rows, state.today, state.run_id, goals=state.goals),
                ),
                rain_forecast=state.rain_forecast,
                engagement=engagement,
                today=state.today,
            )
            if rerun.order_after_variety[:SHOWN_LIMIT] != baseline_top:
                changing.append(value)
        axes.append(
            UnknownAxis(
                dimension=dimension,
                tested_values=tested,
                changing_values=changing,
                changes_top_three=bool(changing),
            )
        )
    return axes


# ── Trace pieces ──────────────────────────────────────────────────────────────────────────────


def intent_axes(intent: ActivityIntent) -> list[TraceIntentAxis]:
    def axis(
        name: str, values: list[str], kind: Literal["hard", "soft", "exclusion"]
    ) -> TraceIntentAxis:
        return TraceIntentAxis(axis=name, values=values, kind=kind if values else "open")

    return [
        axis("on_date", [intent.on_date.isoformat()] if intent.on_date else [], "hard"),
        axis(
            "time_window",
            [intent.time_window.value] if intent.time_window is not TimeWindow.ANY else [],
            "hard",
        ),
        axis(
            "max_distance_m",
            [str(intent.max_distance_m)] if intent.max_distance_m is not None else [],
            "hard" if intent.distance_is_explicit else "soft",
        ),
        axis(
            "social_preference",
            [intent.social_preference.value]
            if intent.social_preference is not SocialPreference.EITHER
            else [],
            "hard",
        ),
        axis(
            "environment",
            [intent.environment.value] if intent.environment.value != "either" else [],
            "hard",
        ),
        axis(
            "intensity",
            [intent.intensity.value] if intent.intensity is not ActivityIntensity.EITHER else [],
            "soft",
        ),
        axis("language", [intent.language] if intent.language else [], "hard"),
        axis("activity_types", [kind.value for kind in intent.activity_types], "soft"),
        axis(
            "excluded_activity_types",
            [kind.value for kind in intent.excluded_activity_types],
            "exclusion",
        ),
        axis(
            "excluded_environments",
            [env.value for env in intent.excluded_environments],
            "exclusion",
        ),
        axis("excluded_social", [shape.value for shape in intent.excluded_social], "exclusion"),
    ]


def _engagement_counts(engagement: ActivityEngagement) -> TraceEngagementCounts:
    return TraceEngagementCounts(
        interested=engagement.interested,
        not_for_me=engagement.not_for_me,
        went=engagement.went,
        did_not_go=engagement.did_not_go,
        enjoyed=engagement.enjoyed,
        not_enjoyed=engagement.not_enjoyed,
    )


def trace_engagement(
    engagement: ActivityEngagement | None, *, in_cooldown: bool
) -> TraceEngagement | None:
    """`in_cooldown` is the ranker's own answer: `ScoreDetail.in_cooldown` for a scored
    candidate, `activity_search.in_decline_cooldown` for a previewed response."""
    if engagement is None:
        return None
    return TraceEngagement(
        series=_engagement_counts(engagement),
        own=_engagement_counts(engagement.own or engagement),
        last_not_for_me=engagement.last_not_for_me,
        in_cooldown=in_cooldown,
    )


def _outcome(tri: Tri | None) -> Literal["match", "mismatch", "unknown", "not_applicable"]:
    if tri is None:
        return "not_applicable"
    return tri.value  # type: ignore[return-value]


def classify_integrity(scored: ScoredCandidate, shown: RankedActivity) -> CandidateIntegrity:
    """Classify every positive factor of one shown candidate against the reasons it was shown.

    Reads only what the person can see on the final card: its face (`shown.reasons`) and the lines
    it shows when opened (`shown.more_reasons`). `grounded`: a line of the matching basis on the
    face. `on_expand`: such a line in `more_reasons`. `silent_by_design`: the ranker by
    construction writes no line for this contribution, detected from the recorded axis, belief or
    engagement detail -- never from reason text. Anything else is `unsupported`, a bug: a line
    that existed only before composition and reached neither list is not an explanation anyone
    was given.

    Also reports the inverse, for information: a line on the face or behind it whose factor did
    not contribute positively.
    """
    detail = scored.detail
    activity_id = scored.entry.ranked.candidate.activity_id
    contributions = {factor.name: factor.contribution for factor in detail.breakdown.factors}
    shown_bases = {reason.basis for reason in shown.reasons}
    expand_bases = {reason.basis for reason in shown.more_reasons}
    findings: list[IntegrityFinding] = []
    positive = [name for name, value in contributions.items() if value > 0]
    for name in positive:
        basis = FACTOR_BASIS.get(name)
        contribution = contributions[name]
        if basis is not None and basis in shown_bases:
            findings.append(
                IntegrityFinding(
                    activity_id=activity_id,
                    factor=name,
                    contribution=contribution,
                    classification="grounded",
                )
            )
            continue
        if basis is not None and basis in expand_bases:
            findings.append(
                IntegrityFinding(
                    activity_id=activity_id,
                    factor=name,
                    contribution=contribution,
                    classification="on_expand",
                )
            )
            continue
        silent = _silent_reason(name, scored)
        findings.append(
            IntegrityFinding(
                activity_id=activity_id,
                factor=name,
                contribution=contribution,
                classification="silent_by_design" if silent else "unsupported",
                silent_reason=silent,
            )
        )
    inverse = [
        ReasonWithoutPositiveFactor(
            activity_id=activity_id,
            basis=reason.basis,
            factor=REASON_BASIS_FACTOR[reason.basis],
            contribution=contributions[REASON_BASIS_FACTOR[reason.basis]],
        )
        for reason in [*shown.reasons, *shown.more_reasons]
        if reason.basis in REASON_BASIS_FACTOR
        and contributions[REASON_BASIS_FACTOR[reason.basis]] <= 0
    ]
    return CandidateIntegrity(
        positive_factors=positive, findings=findings, reasons_without_positive_factor=inverse
    )


def _silent_reason(
    factor: str, scored: ScoredCandidate
) -> Literal["contradicted_avoid_belief", "history_silenced_not_enjoyed"] | None:
    detail = scored.detail
    if factor == "preference":
        beliefs = detail.preference.beliefs
        positive_like_match = any(
            belief.outcome is Tri.MATCH and belief.preference.strength > 0 for belief in beliefs
        )
        avoid_contradicted = any(
            belief.outcome is Tri.MISMATCH and belief.preference.strength < 0 for belief in beliefs
        )
        if avoid_contradicted and not positive_like_match:
            return "contradicted_avoid_belief"
        return None
    if factor == "engagement":
        engagement = detail.engagement
        if engagement is not None and engagement.not_enjoyed and not engagement.enjoyed:
            return "history_silenced_not_enjoyed"
        return None
    return None


def _candidate_trace(
    scored: ScoredCandidate,
    execution: RankingExecution,
    final_entry: RankedActivity | None,
    final_order: list[str],
    today: date,
    integrity: CandidateIntegrity | None,
) -> CandidateTrace:
    candidate = scored.entry.ranked.candidate
    detail = scored.detail
    activity_id = candidate.activity_id
    post = next(
        (entry for entry in execution.final if entry.ranked.candidate.activity_id == activity_id),
        scored.entry,
    )
    # The card as the person would get it: the final entry when this candidate reached the final
    # list, so its lines are exactly the ones `classify_integrity` judged. The bounded re-rank
    # only reorders and relabels, so for a candidate it kept this equals the post-processed entry.
    card = final_entry if final_entry is not None else post.ranked
    tier_names = {preference.tier: preference.tier.name.lower() for preference in detail.scorable}
    return CandidateTrace(
        activity_id=activity_id,
        title=candidate.title,
        programme_key=programme_key(activity_id),
        provider=candidate.provider,
        location_name=candidate.location.name,
        activity_type=candidate.activity_type,
        category=candidate.category,
        indoor_outdoor=candidate.indoor_outdoor,
        intensity=candidate.intensity,
        social_shape=candidate.social_shape,
        distance_m=candidate.distance_m,
        start_at=candidate.start_at,
        availability=candidate.availability,
        language_tags=list(candidate.language_tags),
        factors=list(detail.breakdown.factors),
        total=detail.breakdown.total,
        tier=scored.sort_key.tier,
        sort_key=TraceSortKey(
            tier=scored.sort_key.tier,
            total=scored.sort_key.total,
            matched_axes=scored.sort_key.matched_axes,
            distance_m=scored.sort_key.distance_m,
            title=scored.sort_key.title,
            start_at=scored.sort_key.start_at,
            activity_id=scored.sort_key.activity_id,
        ),
        matched_axes=detail.breakdown.matched_axes,
        coverage=detail.breakdown.coverage,
        request_axes=[
            TraceRequestAxis(
                axis=axis.axis,
                dimension=axis.dimension,
                outcome=_outcome(axis.outcome),
                unknown_reason=axis.unknown_reason,
            )
            for axis in detail.request_axes
        ],
        request_constrained=detail.request_constrained,
        request_judged=detail.request_judged,
        request_matched=detail.request_matched,
        preference_axes=[
            TracePreferenceAxis(
                fact_key=fact_key(belief.preference),
                dimension=belief.preference.dimension,
                value=belief.preference.value,
                pivot=belief.preference.pivot,
                direction=belief.preference.direction,
                strength=belief.preference.strength,
                tier=tier_names.get(belief.preference.tier, belief.preference.tier.name.lower()),
                outcome=belief.outcome.value,  # type: ignore[arg-type]
                unknown_reason=belief.unknown_reason,
                contribution=round(belief.contribution, 3),
            )
            for belief in detail.preference.beliefs
        ],
        engagement=trace_engagement(detail.engagement, in_cooldown=detail.in_cooldown),
        travel_tolerance_m=detail.travel_tolerance_m,
        asked_radius_m=detail.asked_radius_m,
        rain_applied=detail.rain_applied,
        reasons_shown=list(card.reasons),
        more_reasons=list(card.more_reasons),
        reasons_before_composition=list(detail.candidate_reasons),
        reasons_suppressed=post.breakdown.reasons_suppressed,
        series_deferred=post.breakdown.series_deferred,
        variety_promoted=post.breakdown.variety_promoted,
        positions=TraceStagePositions(
            after_sort=execution.order_after_sort.index(activity_id) + 1,
            after_series_dedupe=execution.order_after_dedupe.index(activity_id) + 1,
            after_variety=execution.order_after_variety.index(activity_id) + 1,
            final=final_order.index(activity_id) + 1 if activity_id in final_order else None,
        ),
        integrity=integrity if final_entry is not None else None,
    )


@dataclass(frozen=True)
class LlmStage:
    trace: TraceLlmRerank
    final: list[RankedActivity]
    narrowed: list[FilterOutcome]
    plan_run: ActivityPlanRun | None


def run_llm_stage(
    ranked: list[RankedActivity],
    understood: list[str],
    *,
    run_planner: bool,
    config: LlmConfig,
    plan: PlanRanking | None,
    differs_from_live: bool,
    intent_planner: TraceIntentPlanner,
) -> LlmStage:
    """Run (or decline to run) the bounded re-rank exactly as search does, and sanitise it.

    `provider` and `transport` are the run's own (`ActivityPlanRun.provider` / `.transport`, set
    by the planner whenever it requested a client). When no client was requested -- the planner is
    disabled, not asked for, or had nothing to rank -- `transport` is `off` and `provider` names
    what is configured, since nothing was reached through it.
    """
    window = [item.candidate.activity_id for item in ranked[:MAX_ACTIVITY_OPTIONS_RETURNED]]
    base = {
        "planner_enabled": config.enabled,
        "window_size": MAX_ACTIVITY_OPTIONS_RETURNED,
        "max_promotion": MAX_PROMOTION,
        "min_shown_after_narrowing": MIN_SHOWN_AFTER_NARROWING,
        "max_iterations": config.max_iterations,
        "deterministic_window": window,
        "intent_planner": intent_planner,
    }
    if not (run_planner and config.enabled and ranked and plan is not None):
        # Search records `no_candidates` whenever nothing survived to be ranked, planner on or off
        # (`search_activities`' `planner_mode`); the inspector says the same.
        status: Literal["fallback_disabled", "not_run_in_preview", "no_candidates"] = (
            "no_candidates"
            if not ranked
            else "not_run_in_preview"
            if config.enabled
            else "fallback_disabled"
        )
        return LlmStage(
            trace=TraceLlmRerank(
                status=status,
                ran=False,
                transport="off",
                provider=config.provider,
                recording_may_miss=False,
                model=config.model if config.enabled else None,
                final_order=[item.candidate.activity_id for item in ranked],
                **base,  # type: ignore[arg-type]
            ),
            final=ranked,
            narrowed=[],
            plan_run=None,
        )
    context = build_ranking_context(ranked, understood)
    plan_run = plan(context, [item.candidate.activity_id for item in ranked])
    transport: Literal["live", "recorded", "off"] = plan_run.transport or "off"
    merged, narrowed = merge_planner_order(ranked, plan_run)
    permitted = context.permitted_keys
    calls: list[TraceToolCall] = []
    for call in plan_run.tool_calls:
        name = call.tool_name if call.tool_name in _KNOWN_ACTIVITY_TOOLS else "unknown_tool"
        proposed: list[str] = []
        unknown = 0
        if name == PROPOSE_ACTIVITY_ORDER_TOOL_NAME:
            raw = call.arguments.get("ordered_keys")
            keys = [str(key) for key in raw] if isinstance(raw, list) else []
            proposed = [key for key in keys if key in permitted]
            unknown = len(keys) - len(proposed)
        calls.append(
            TraceToolCall(
                iteration=call.iteration,
                tool_name=name,
                ok=call.ok,
                proposed_keys=proposed,
                unknown_key_count=unknown,
            )
        )
    merged_ids = [item.candidate.activity_id for item in merged]
    error_class = (
        plan_run.fallback_reason
        if plan_run.mode == "fallback_error"
        and plan_run.fallback_reason is not None
        and _CLASS_NAME.fullmatch(plan_run.fallback_reason)
        else None
    )
    return LlmStage(
        trace=TraceLlmRerank(
            status=plan_run.mode,
            ran=True,
            transport=transport,
            provider=plan_run.provider if plan_run.provider is not None else config.provider,
            # A recording holds only the requests it captured; a state that is not live changes
            # the request, so a replay will miss it and fall back.
            recording_may_miss=transport == "recorded" and differs_from_live,
            model=plan_run.model,
            iterations=plan_run.iterations,
            tool_calls=calls,
            guardrail_rule_counts=count_violations_by_rule(plan_run.guardrail_rejections),
            rejected_proposal_count=plan_run.rejected_proposal_count,
            fallback_error_class=error_class,
            final_order=merged_ids,
            narrowed=[outcome.activity_id for outcome in narrowed],
            movements=[
                TracePlannerMovement(
                    activity_id=item.candidate.activity_id,
                    deterministic_rank=item.rank,
                    final_rank=(
                        merged_ids.index(item.candidate.activity_id) + 1
                        if item.candidate.activity_id in merged_ids
                        else None
                    ),
                )
                for item in ranked
            ],
            evidence_id=plan_run.evidence_id,
            **base,  # type: ignore[arg-type]
        ),
        final=merged,
        narrowed=narrowed,
        plan_run=plan_run,
    )


def web_cards(final: Sequence[RankedActivity]) -> list[TraceWebCard]:
    """The senior screen's grouping (`apps/web/lib/view-models.ts:groupSearchResults`) for its first
    three cards: sessions fold together by the ranker's own `series_key` (a result without one is
    its own card), groups keep the order of their first member, and each card headlines its first
    member in API order -- the session the ranker placed highest."""
    buckets: list[list[RankedActivity]] = []
    index: dict[str, int] = {}
    for item in final:
        key = item.series_key if item.series_key is not None else item.candidate.activity_id
        if key not in index:
            index[key] = len(buckets)
            buckets.append([item])
        else:
            buckets[index[key]].append(item)
    return [
        TraceWebCard(
            title=bucket[0].candidate.title,
            location_name=bucket[0].candidate.location.name,
            headline_activity_id=bucket[0].candidate.activity_id,
            member_ids=[item.candidate.activity_id for item in bucket],
        )
        for bucket in buckets[:SHOWN_LIMIT]
    ]


def catalogue_unknowns(catalogue: Sequence[ActivityCandidate]) -> list[TraceCatalogueUnknown]:
    checks: list[tuple[str, Callable[[ActivityCandidate], bool]]] = [
        ("start_at", lambda c: c.start_at is None),
        ("distance_m", lambda c: c.distance_m is None),
        ("indoor_outdoor", lambda c: c.indoor_outdoor is IndoorOutdoor.UNKNOWN),
        ("intensity", lambda c: c.intensity is None),
        ("social_shape", lambda c: c.social_shape is None),
        ("activity_type", lambda c: c.activity_type is None),
        ("language_tags", lambda c: not c.language_tags),
        ("availability", lambda c: c.availability is ActivityAvailability.UNKNOWN),
    ]
    unknowns: list[TraceCatalogueUnknown] = []
    for name, missing in checks:
        ids = [candidate.activity_id for candidate in catalogue if missing(candidate)]
        if ids:
            unknowns.append(TraceCatalogueUnknown(field=name, activity_ids=ids))  # type: ignore[arg-type]
    return unknowns


# ── The trace ─────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InspectionResult:
    trace: ActivityRankingTrace
    execution: RankingExecution


def inspect(
    state: InspectionState,
    parsed: ParsedRequest,
    *,
    trace_id: str,
    generated_at: datetime,
    variant: bool,
    preview: bool,
    applied: TraceApplied,
    run_planner: bool,
    llm: LlmConfig,
    plan: PlanRanking | None,
) -> InspectionResult:
    """Rank one state with the production pipeline and describe every stage of it.

    `variant` says which side of a comparison this trace is; `preview` says whether its state
    differs from what the person actually holds (a scripted preset, a counterfactual or a feedback
    preview is applied) -- a baseline with a preset is not a variant, but it is a preview.
    """
    intent = parsed.intent
    preferences = state.preferences()
    engagement = state.engagement()
    execution = rank_with_trace(
        state.catalogue,
        intent,
        preferences,
        rain_forecast=state.rain_forecast,
        engagement=engagement,
        today=state.today,
    )
    understood = describe_intent(intent)
    ranked = [entry.ranked for entry in execution.final]
    llm_stage = run_llm_stage(
        ranked,
        understood,
        run_planner=run_planner,
        config=llm,
        plan=plan,
        differs_from_live=preview,
        intent_planner=TraceIntentPlanner(ran=parsed.intent_planner_ran, mode=parsed.intent_mode),
    )
    final = llm_stage.final
    final_ids = [item.candidate.activity_id for item in final]
    top_ids = final_ids[:SHOWN_LIMIT]

    # Integrity, for what the person would actually see.
    swap = execution.variety.swap
    integrity_by_id: dict[str, CandidateIntegrity] = {}
    for item in final[:SHOWN_LIMIT]:
        scored = next(
            entry
            for entry in execution.scored
            if entry.entry.ranked.candidate.activity_id == item.candidate.activity_id
        )
        integrity_by_id[item.candidate.activity_id] = classify_integrity(scored, item)
    findings = [finding for value in integrity_by_id.values() for finding in value.findings]
    silent: dict[str, int] = {}
    for finding in findings:
        if finding.classification == "silent_by_design" and finding.silent_reason is not None:
            silent[finding.silent_reason] = silent.get(finding.silent_reason, 0) + 1

    kept_ids = {candidate.activity_id for candidate in execution.kept}
    removed_by_id = {outcome.activity_id: outcome for outcome in execution.removed}
    by_rule: dict[str, int] = {}
    for outcome in execution.removed:
        by_rule[outcome.rule] = by_rule.get(outcome.rule, 0) + 1

    resolved = preferences.resolved
    tolerance = travel_tolerance_m(resolved)
    travel_start = travel_cost_start_for(preferences, intent)

    def stage_for(activity_id: str) -> Literal["sort", "series_dedupe", "variety", "planner"]:
        if (
            llm_stage.plan_run is not None
            and llm_stage.plan_run.used_agent
            and activity_id not in execution.order_after_variety[:SHOWN_LIMIT]
        ):
            return "planner"
        if activity_id in execution.order_after_sort[:SHOWN_LIMIT]:
            return "sort"
        if activity_id in execution.order_after_dedupe[:SHOWN_LIMIT]:
            return "series_dedupe"
        if activity_id in execution.order_after_variety[:SHOWN_LIMIT]:
            return "variety"
        return "planner"

    cards = web_cards(final)
    trace = ActivityRankingTrace(
        trace_id=trace_id,
        generated_at=generated_at,
        variant="variant" if variant else "baseline",
        preview=preview,
        person=TracePerson(person_id=state.person_id, display_name=state.display_name),
        today=state.today,
        run_id=state.run_id,
        applied=applied,
        request=TraceRequest(raw_text=parsed.raw_text, source=parsed.source),
        parsed_intent=TraceParsedIntent(
            intent=intent,
            parser=intent.parsed_by,
            intent_mode=parsed.intent_mode,
            axes=intent_axes(intent),
            unparsed_terms=list(intent.unparsed_terms),
            unparsed_terms_withheld=parsed.unparsed_terms_withheld,
            language_model_supplied_ungrounded=parsed.language_model_supplied_ungrounded,
            understood=understood,
        ),
        person_context=TracePersonContext(
            facts=trace_facts(state, intent, preferences, execution),
            unknown_axes=unknown_axes(state, intent, preferences, execution, engagement),
            travel_tolerance_m=tolerance,
            travel_tolerance_basis=travel_tolerance_basis(resolved),
            travel_cost_starts_m=travel_start.starts_m,
            travel_cost_start_basis=travel_start.basis,
            asked_radius_m=travel_start.asked_radius_m,
            nearby_radius_m=NEARBY_RADIUS_M,
            consent_active=state.consent_active,
        ),
        retrieval=TraceRetrieval(
            catalogue_count=len(state.catalogue),
            sources=sorted({candidate.source for candidate in state.catalogue}),
            integration_statuses=sorted(
                {candidate.integration_status for candidate in state.catalogue}
            ),
            rain_forecast=state.rain_forecast,
            rain_source=state.rain_source,
        ),
        filtering=TraceFiltering(
            rules_in_order=list(FILTER_RULE_NAMES),
            kept_count=len(execution.kept),
            removed_count=len(execution.removed),
            by_rule=by_rule,
            outcomes=[
                TraceFilterOutcome(
                    activity_id=candidate.activity_id,
                    title=candidate.title,
                    status="kept" if candidate.activity_id in kept_ids else "removed",
                    rule=(
                        removed_by_id[candidate.activity_id].rule
                        if candidate.activity_id in removed_by_id
                        else None
                    ),
                    detail=(
                        removed_by_id[candidate.activity_id].detail
                        if candidate.activity_id in removed_by_id
                        else None
                    ),
                )
                for candidate in state.catalogue
            ],
        ),
        scoring=TraceScoring(
            weights=dict(RANKING_WEIGHTS),
            factor_order=list(RANKING_WEIGHTS),
            factor_descriptions=dict(RANKING_FACTOR_DESCRIPTIONS),
            engagement_weights=dict(ENGAGEMENT_WEIGHTS),
            top_n=DIVERSITY_TOP_N,
            diversity_score_margin=DIVERSITY_SCORE_MARGIN,
            decline_cooldown_days=DECLINE_COOLDOWN_DAYS,
            candidates=[
                _candidate_trace(
                    scored,
                    execution,
                    next(
                        (
                            item
                            for item in final[:SHOWN_LIMIT]
                            if item.candidate.activity_id
                            == scored.entry.ranked.candidate.activity_id
                        ),
                        None,
                    ),
                    final_ids,
                    state.today,
                    integrity_by_id.get(scored.entry.ranked.candidate.activity_id),
                )
                for scored in execution.scored
            ],
        ),
        sort=TraceSort(
            keys=[
                TraceSortKeyField(name="tier", direction="descending"),
                TraceSortKeyField(name="total", direction="descending"),
                TraceSortKeyField(name="matched_axes", direction="descending"),
                TraceSortKeyField(name="distance_m", direction="ascending"),
                TraceSortKeyField(name="title", direction="ascending"),
                TraceSortKeyField(name="start_at", direction="ascending"),
                TraceSortKeyField(name="activity_id", direction="ascending"),
            ],
            order_before_postprocess=list(execution.order_after_sort),
        ),
        post_processing=TracePostProcessing(
            series_dedupe=TraceSeriesDedupe(
                ran=execution.dedupe.ran,
                changed=execution.dedupe.changed,
                deferred=[
                    TraceSeriesDeferral(
                        activity_id=item.activity_id,
                        series_holder_id=item.series_holder_id,
                        from_position=item.from_position,
                        to_position=item.to_position,
                    )
                    for item in execution.dedupe.deferred
                ],
                refilled=list(execution.dedupe.refilled),
                order_after=list(execution.order_after_dedupe),
            ),
            variety=TraceVariety(
                status=execution.variety.status,
                shared_kind=execution.variety.shared_kind,
                considered=[
                    TraceVarietyConsidered(
                        activity_id=item.activity_id,
                        kind=item.kind,
                        tier=item.tier,
                        total=item.total,
                        outcome=item.outcome,
                    )
                    for item in execution.variety.considered
                ],
                swap=(
                    TraceVarietySwap(
                        promoted_id=swap.promoted_id,
                        displaced_id=swap.displaced_id,
                        from_position=swap.from_position,
                        to_position=swap.to_position,
                        shared_kind=swap.shared_kind,
                        promoted_kind=swap.promoted_kind,
                        tier=swap.tier,
                        third_total=swap.third_total,
                        promoted_total=swap.promoted_total,
                        margin=swap.margin,
                        reasons_before=list(swap.reasons_before),
                        reasons_after=list(swap.reasons_after),
                        more_reasons_after=list(swap.more_reasons_after),
                        reasons_suppressed_recorded=next(
                            entry.breakdown.reasons_suppressed
                            for entry in execution.final
                            if entry.ranked.candidate.activity_id == swap.promoted_id
                        ),
                    )
                    if swap is not None
                    else None
                ),
                order_after=list(execution.order_after_variety),
            ),
        ),
        llm_rerank=llm_stage.trace,
        final_recommendations=TraceFinalRecommendations(
            shown_limit=SHOWN_LIMIT,
            result_count=len(final),
            nothing_matched=not final,
            top=[
                TraceRecommendation(
                    activity_id=item.candidate.activity_id,
                    rank=item.rank,
                    selection_stage=stage_for(item.candidate.activity_id),
                    selected_by=item.selected_by,
                )
                for item in final[:SHOWN_LIMIT]
            ],
            web_cards=cards,
            web_grouping_changes_top_three=[card.headline_activity_id for card in cards] != top_ids,
        ),
        integrity=TraceIntegrity(
            grounded=sum(1 for f in findings if f.classification == "grounded"),
            on_expand=sum(1 for f in findings if f.classification == "on_expand"),
            silent_by_design=silent,
            unsupported=sum(1 for f in findings if f.classification == "unsupported"),
            reason_without_positive_factor=sum(
                len(value.reasons_without_positive_factor) for value in integrity_by_id.values()
            ),
            findings=findings,
        ),
        catalogue_unknowns=catalogue_unknowns(state.catalogue),
        evidence_ids=[
            trace_id,
            *([llm_stage.plan_run.evidence_id] if llm_stage.plan_run is not None else []),
        ],
    )
    return InspectionResult(trace=trace, execution=execution)


def learning_preview(
    before: InspectionState,
    outcome: FeedbackOutcome,
    feedback: RankerFeedbackPreview,
    intent: ActivityIntent,
    *,
    duplicate_same_day: bool,
) -> TraceLearningPreview:
    return TraceLearningPreview(
        feedback=feedback,
        activity_title=outcome.candidate.title,
        consent_active=before.consent_active,
        duplicate_same_day=duplicate_same_day,
        teaches_dimension=outcome.teaches_dimension,
        facts_before=trace_facts(before, intent, before.preferences()),
        engagement_before=trace_engagement(
            outcome.engagement_before,
            in_cooldown=in_decline_cooldown(outcome.engagement_before, before.today),
        ),
        engagement_after=trace_engagement(
            outcome.engagement_after,
            in_cooldown=in_decline_cooldown(outcome.engagement_after, before.today),
        ),
    )


# ── Comparing two traces ──────────────────────────────────────────────────────────────────────


# The fields a `fact_changed` row may name, in this order. `evidence` covers both evidence counts.
FACT_CHANGE_FIELDS: Final[tuple[str, ...]] = (
    "value",
    "pivot",
    "strength",
    "confidence",
    "evidence",
    "tier",
    "status",
    "used_in_scoring",
)


def _changed_fact_fields(old: TraceFact, new: TraceFact) -> list[str]:
    def read(fact: TraceFact, name: str) -> object:
        if name == "evidence":
            return (fact.positive_evidence, fact.negative_evidence, fact.evidence_count)
        return getattr(fact, name)

    return [name for name in FACT_CHANGE_FIELDS if read(old, name) != read(new, name)]


def compare_traces(
    baseline: ActivityRankingTrace, variant: ActivityRankingTrace
) -> list[RankChange]:
    """Structured differences only; the web view-model words them."""
    changes: list[RankChange] = []
    base_order = baseline.llm_rerank.final_order
    var_order = variant.llm_rerank.final_order
    base_rank = {key: index + 1 for index, key in enumerate(base_order)}
    var_rank = {key: index + 1 for index, key in enumerate(var_order)}
    base_top = set(base_order[:SHOWN_LIMIT])
    var_top = set(var_order[:SHOWN_LIMIT])
    window = list(
        dict.fromkeys(
            [
                *base_order[:MAX_ACTIVITY_OPTIONS_RETURNED],
                *var_order[:MAX_ACTIVITY_OPTIONS_RETURNED],
            ]
        )
    )
    for key in window:
        if key in base_top and key not in var_top:
            changes.append(
                RankChange(
                    kind="left_top_three",
                    activity_id=key,
                    baseline_rank=base_rank.get(key),
                    variant_rank=var_rank.get(key),
                )
            )
        elif key in var_top and key not in base_top:
            changes.append(
                RankChange(
                    kind="entered_top_three",
                    activity_id=key,
                    baseline_rank=base_rank.get(key),
                    variant_rank=var_rank.get(key),
                )
            )
        elif base_rank.get(key) != var_rank.get(key):
            changes.append(
                RankChange(
                    kind="rank_moved",
                    activity_id=key,
                    baseline_rank=base_rank.get(key),
                    variant_rank=var_rank.get(key),
                )
            )

    base_filter = {item.activity_id: item.rule for item in baseline.filtering.outcomes}
    var_filter = {item.activity_id: item.rule for item in variant.filtering.outcomes}
    for key in base_filter:
        if key in var_filter and base_filter[key] != var_filter[key]:
            changes.append(
                RankChange(
                    kind="filter_status_changed",
                    activity_id=key,
                    baseline_rule=base_filter[key],
                    variant_rule=var_filter[key],
                )
            )

    base_candidates = {item.activity_id: item for item in baseline.scoring.candidates}
    var_candidates = {item.activity_id: item for item in variant.scoring.candidates}
    for key in dict.fromkeys([*base_order[:SHOWN_LIMIT], *var_order[:SHOWN_LIMIT]]):
        before, after = base_candidates.get(key), var_candidates.get(key)
        if before is None or after is None:
            continue
        after_factors = {factor.name: factor.contribution for factor in after.factors}
        deltas = [
            (factor.name, factor.contribution, after_factors[factor.name])
            for factor in before.factors
            if abs(after_factors[factor.name] - factor.contribution) >= 0.001
        ]
        deltas.sort(key=lambda item: -abs(item[2] - item[1]))
        for name, old, new in deltas:
            changes.append(
                RankChange(
                    kind="factor_delta",
                    activity_id=key,
                    factor=name,
                    baseline_contribution=old,
                    variant_contribution=new,
                    delta=round(new - old, 3),
                )
            )

    base_facts = {fact.fact_key: fact for fact in baseline.person_context.facts}
    var_facts = {fact.fact_key: fact for fact in variant.person_context.facts}
    for key, fact in var_facts.items():
        old = base_facts.get(key)
        if old is None:
            changes.append(
                RankChange(
                    kind="fact_added",
                    fact_key=key,
                    variant_strength=fact.strength,
                    variant_pivot=fact.pivot,
                )
            )
        elif changed := _changed_fact_fields(old, fact):
            changes.append(
                RankChange(
                    kind="fact_changed",
                    fact_key=key,
                    baseline_strength=old.strength,
                    variant_strength=fact.strength,
                    baseline_pivot=old.pivot,
                    variant_pivot=fact.pivot,
                    changed_fields=changed,
                )
            )
    for key, fact in base_facts.items():
        if key not in var_facts:
            changes.append(
                RankChange(
                    kind="fact_removed",
                    fact_key=key,
                    baseline_strength=fact.strength,
                    baseline_pivot=fact.pivot,
                )
            )
    return changes


__all__ = [
    "SHOWN_LIMIT",
    "FeedbackOutcome",
    "InspectionResult",
    "InspectionState",
    "LlmConfig",
    "ParsedRequest",
    "PlanRanking",
    "RankerInspectorDefect",
    "RankerPersonNotFound",
    "RankerRequestError",
    "apply_feedback",
    "apply_history_preset",
    "apply_request_counterfactual",
    "apply_world_counterfactual",
    "classify_integrity",
    "compare_traces",
    "inspect",
    "learning_preview",
    "sanitise_intent",
    "trace_facts",
    "unknown_axes",
]
