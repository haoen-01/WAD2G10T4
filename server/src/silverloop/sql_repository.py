from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import median
from time import monotonic
from typing import Any, Final, Literal, Protocol
from uuid import uuid4

from sqlalchemy import and_, create_engine, func, or_, select, text, update
from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DisconnectionError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.elements import ColumnElement

from silverloop.activity_search import (
    ActivityEngagement,
    count_engagement,
    engagement_by_series,
    series_identity,
    series_key,
    series_keys_for,
)
from silverloop.adapters.models import CanonicalDailyMetric
from silverloop.adapters.synthetic import SyntheticFixtureAdapter
from silverloop.agent import (
    AGENT_VERSION,
    AgentRun,
    AgentUsage,
    CandidateOption,
    HistoryEntry,
    ProgrammeOption,
    ToolContext,
    log_provider_failure,
    plan_outreach,
)
from silverloop.agent.constants import THRESHOLD_CALIBRATOR_VERSION
from silverloop.agent.guardrail_rules import count_violations_by_rule
from silverloop.agent.threshold_guardrails import reasoning_violations, validate_threshold_output
from silverloop.agent.threshold_planner import (
    WRITE_UP_BOUNDARY,
    ThresholdAgentProposal,
    ThresholdPlannerTask,
    ThresholdPlanRun,
    plan_threshold_calibration,
    plan_threshold_tightening,
    run_failure_reason,
    threshold_fallback_run,
    write_up_reversal,
)
from silverloop.agent.threshold_tools import (
    EpisodeDayInput,
    ReversalInput,
    ReviewInput,
    ThresholdEpisodeContext,
    ThresholdHistoryInput,
    build_threshold_episode_context,
)
from silverloop.analytics import (
    ConfirmedReference,
    analyse_signal,
    calculate_reference,
)
from silverloop.analytics import clamp_streak_days as _clamp_streak_days
from silverloop.baseline_confirmation import question_for as baseline_confirmation_question_for
from silverloop.config import Settings, get_settings
from silverloop.consent_scopes import ConsentScope, scope_permitted
from silverloop.context import ContextEvidence, ExternalContext, ExternalContextProvider
from silverloop.context_explanation import StatedExplanation, active_explanation
from silverloop.context_question import _OPTIONS as CONTEXT_ANSWER_OPTIONS
from silverloop.context_question import question_for
from silverloop.db_models import (
    ActivityCandidateRow,
    ActivityDimensionPreferenceRow,
    ActivityGoalRow,
    ActivityOfferResponseRow,
    AuditEventRow,
    AuthUserPersonLinkRow,
    Base,
    BaselineConfirmationRow,
    CandidatePreferenceRow,
    CaseReviewRow,
    ConsentEvidenceRow,
    ContextQuestionAnswerRow,
    DailyMetricRow,
    DayDisputeRow,
    DecisionEvidenceRow,
    InterventionEnjoymentRow,
    InterventionFollowThroughRow,
    InterventionOutcomeRow,
    InterventionRow,
    PersonRow,
    PlanEnjoymentRow,
    PlanFollowThroughRow,
    ProgrammeRow,
    ReplanOfferRow,
    ReviewCaseRow,
    ReviewThresholdDecisionRow,
    ReviewThresholdProposalRow,
    ScenarioRunRow,
    SimulationEventRow,
    WeekPlanEntryRow,
)
from silverloop.fixtures import (
    DEMO_ANCHOR_DAY,
    DEMO_PERSON_ID,
    DEMO_PERSONAS,
    persona_profile,
    persona_seed,
    synthetic_activity_candidates,
    synthetic_programmes,
)
from silverloop.follow_up import observe_effect
from silverloop.learning import MIN_SINGLE_OBSERVATION_DELTA, PreferenceLearner
from silverloop.local_time import local_date, local_hour
from silverloop.logging_config import agent_logger, request_id_var
from silverloop.models import (
    ActivityAvailability,
    ActivityBooking,
    ActivityCandidate,
    ActivityGoal,
    ActivityIntensity,
    ActivityLocation,
    ActivityOfferResponse,
    ActivityPreferences,
    ActivitySource,
    AdvanceResponse,
    AttentionBand,
    AuditEvent,
    BaselineConfirmationDecision,
    CandidatePreference,
    CaseResolution,
    CaseStatus,
    ClarificationScope,
    ConsentResponse,
    ContextGapCategory,
    ContextSignal,
    DailyMetric,
    Decision,
    DecisionTraceStep,
    DeclineReason,
    DemoResetResponse,
    DimensionPreference,
    DistanceBasis,
    Enjoyment,
    FollowThrough,
    GoalKind,
    HumanAction,
    IndoorOutdoor,
    IntegrationStatus,
    Intervention,
    OperationalMetrics,
    OutcomeKind,
    OutcomeResponse,
    OverrideReason,
    PersonState,
    PersonWorldModel,
    PlannedActivity,
    PlannedFollowThrough,
    PolicyGate,
    PreferenceDimension,
    PriorOutreach,
    Programme,
    ReadinessResponse,
    ReplanResolution,
    ReviewAction,
    ReviewCase,
    ReviewThresholdCause,
    ReviewThresholdDecisionKind,
    ReviewThresholdOutputKind,
    ReviewThresholdProposer,
    ReviewThresholdRejectionReason,
    ReviewThresholdReplay,
    ReviewThresholdRevertTrigger,
    SocialPreference,
    StatedContextExplanation,
    TraceStatus,
)
from silverloop.ontology import ActivityFamily, ActivityType, Format
from silverloop.policy import ACCEPTED_OUTREACH_COOLDOWN_DAYS, PolicyResult, decide
from silverloop.preferences import (
    DECLINE_REASON_DIMENSIONS,
    SENIOR_STATEMENT_SOURCE,
    apply_decline,
    resolve,
    social_shape_score,
)
from silverloop.quality import MINIMUM_WEAR_HOURS, assess_data_quality
from silverloop.replanning import notices_for
from silverloop.review_threshold import (
    ABSOLUTE_REVIEW_FLOOR,
    DEFAULT_REVIEW_THRESHOLD,
    REPLAY_WINDOW_DAYS,
    SHADOW_SCAN_DAYS,
    VIOLATION_CITATIONS,
    WEEKLY_PROPOSAL_CAP,
    FalseAlarmRef,
    LiveReviewThreshold,
    RevertSkipped,
    ReviewThreshold,
    ThresholdDecisionFact,
    ThresholdVerdict,
    approval_stack,
    blocked_threshold_values,
    checking_until,
    cooldown_until,
    far_more_severe,
    fixed_rule_output,
    fixed_rule_tightening,
    fixed_write_up_text,
    is_false_alarm,
    never_later,
    pending_revert_fact,
    reached_too_late_revert,
    resolve_live_threshold,
    senior_notice_for,
    validate_threshold_structure,
    within_checking_period,
)
from silverloop.review_threshold_replay import (
    DaySignal,
    day_signals,
    review_fires,
    shadow_review_since,
    variability_summary,
)
from silverloop.schema_revision import expected_database_revision
from silverloop.stored_state import (
    load_stored_advance,
    undecodable_stored_json,
)
from silverloop.world_model import (
    ActivityHistoryFact,
    ConfirmedReferenceFact,
    ContextAnswerFact,
    OutreachResponseFact,
    WorldModelInputs,
    build_world_model,
)

POLICY_VERSION = "silverloop-policy-v1"

# The axes whose declines are item-level and so read the same-programme rule (`preferences._fold`).
_PROGRAMME_RULE_DIMENSIONS: Final[frozenset[PreferenceDimension]] = frozenset(
    {PreferenceDimension.TIMING, PreferenceDimension.ACTIVITY_TYPE}
)
MAX_DAILY_METRICS_DAYS = 90
# Prior outreach rows handed to the planner. Small on purpose: tool payloads stay compact so the
# context window holds the decision, not the archive.
MAX_AGENT_HISTORY_ROWS = 5

# How many declines of one candidate before it stops being offered.
#
# Three, not one: a single "not today" is about the day, and muting on it would make the product
# forgetful of a person's actual preferences in the opposite direction -- silently removing help
# someone still wants. Three is a pattern, and the person can reverse it either way at any time.
DECLINES_BEFORE_SUPPRESSION = 3

# Below this many recorded responses, the hour they usually reply at is noise -- two data points
# describe two afternoons, not a habit. Reported as `None` with its sample size rather than as a
# confident number with nothing behind it.
MINIMUM_RESPONSE_HOUR_SAMPLE = 3

# How many simulated days an offer stays open before silence is recorded as silence.
#
# Before this existed an unanswered nudge stayed `proposed` forever: the loop trace read "Waiting
# for the senior to accept, decline or give no response" indefinitely, `OutcomeKind.NO_RESPONSE`
# and its half-weight learning rule (`learning.py`) were unreachable from any product path, and
# silence spent the weekly contact budget while teaching the learner nothing. Two days gives the
# person the whole of the day the offer landed and the whole of the next to answer; on the morning
# after that, `advance()` closes it as `no_response` -- an audited outcome recorded by `system`,
# weighted as "an unread phone is not a refusal" (half a unit against the candidate, never a full
# decline). Counted in the person's simulated days, like `_RunReads.days_since_last_accepted`,
# because it is a statement about their week, not about the machine's clock. Deliberately never
# shown to the senior: a deadline on an optional suggestion is pressure, which the outreach
# guardrail forbids.
RESPONSE_WINDOW_DAYS = 2

# How many simulated days Care+ lets a review case sit before it says, on the case itself,
# that it is putting it back in front of a human.
#
# Counted in the person's simulated days for exactly the reason `RESPONSE_WINDOW_DAYS` is: nothing
# in this product advances time except a simulation event, so a wall-clock week can pass over a
# case that has seen no new reading. Deliberately not a scheduler and deliberately not a deadline:
# nothing fires on this day, no case auto-escalates, and it is never rendered on a senior surface.
# It is a promise Care+ makes to the care team about its own queue -- "this will not quietly
# disappear" -- which is why it is derived on the way out (`_to_case`) from the stored opening day
# rather than stored beside it, where the two could disagree.
CASE_REVIEW_WINDOW_DAYS = 7

# Read-time gates that outrank a decision recorded earlier the same day on the care-priority board.
# See `_with_recorded_decision`.
_READ_TIME_HOLDS = frozenset(
    {
        PolicyGate.CONSENT,
        PolicyGate.DATA_QUALITY,
        PolicyGate.CONFIDENCE,
        PolicyGate.STATED_EXPLANATION,
        PolicyGate.ACCEPTED_COOLDOWN,
    }
)

# The weekly contact cap is also counted in simulated days: an intervention counts against the cap
# while its outreach day is within this many days of the day being decided (today plus the six
# before it). It used to be `created_at >= utcnow() - 7 days`, which meant a demo advancing ten
# simulated days in a minute suppressed the third contact a simulated week later, and a demo left
# open across a real weekend let last week's contacts expire mid-simulated-week.
CONTACT_CAP_WINDOW_DAYS = 7

# The senior-facing label for each stored context-answer value, derived from the options the
# question actually offered rather than restated, so the two can never disagree.
CONTEXT_ANSWER_LABELS = {option.value: option.label for option in CONTEXT_ANSWER_OPTIONS}

# How much a person's learned SOCIAL dimension preference (`preferences.social_shape_score`) may
# nudge outreach candidate ranking, relative to the per-candidate posterior's `expected_value`.
# Kept small and named so the tradeoff is visible in one place: enough to break a near-tie between
# candidates with an identical or similar acceptance history, never enough to override real
# acceptance/decline evidence for this exact candidate -- that second half is an invariant, not a
# hope, so it is enforced by construction rather than by a hand-picked constant.
#
# `social_shape_score` is bounded to [-1, 1] (`DimensionPreference.strength` is a Pydantic
# `Field(ge=-1, le=1)`), so one candidate's own nudge term is bounded to
# `[-SOCIAL_DIMENSION_RANKING_WEIGHT, +SOCIAL_DIMENSION_RANKING_WEIGHT]`. The realistic worst case
# is two-sided, not one: a person can hold both a `senior_statement` PREFER on one SOCIAL value
# and an AVOID on the other at once (two independent preference rows under the same dimension),
# so within one decision's candidate set (`GENTLE_NUDGE` offers a SOLO pair and a SOCIAL
# `companion_walk` together) one permitted candidate can score +1 while another scores -1
# simultaneously. For the nudge to never flip a candidate with a single real observation against
# one with none, `2 * SOCIAL_DIMENSION_RANKING_WEIGHT` must stay strictly below
# `MIN_SINGLE_OBSERVATION_DELTA` -- the smallest `expected_value` movement any one recorded
# intervention can produce, recomputed from `learning.py`'s own weight tables (ADR 0005) so this
# bound holds even if those weights are retuned later, not just at today's numbers. Halving that
# bound again leaves headroom for `expected_value`'s own 3-decimal rounding.
#
# This is deliberately scoped to a *single* observation against *no* observation -- the case ADR
# 0005 names explicitly and `test_social_nudge_cannot_override_a_single_real_observation` pins.
# Two candidates that have each accumulated a long, nearly-tied history are a genuine near-tie,
# and breaking that is exactly what this nudge exists for; nothing here claims to bound that case.
SOCIAL_DIMENSION_RANKING_WEIGHT = round(MIN_SINGLE_OBSERVATION_DELTA / 4, 4)

# Where a seeded listing's facts came from. Honest about being a fixture rather than naming a
# directory nobody read: `last_verified_at` is deliberately left null alongside it, because
# nobody has checked these against a real centre and a date here would claim they had.
_FIXTURE_METADATA_SOURCE = "aac_fixture:fixtures.py"


@dataclass(frozen=True)
class InterventionCandidate:
    key: str
    title: str
    message: str
    # Real facts about this option, never inferred or fabricated by the planner. `social_shape`
    # is what the grounding guardrail (`guardrails.validate_proposal`) checks a proposed message
    # against: a SOLO option must never be described as involving company, a group or joining
    # anyone. `accessibility_terms` names the handful of words in the canonical copy that carry
    # accessibility meaning (e.g. "seated") and that a rewritten message must not drop or
    # contradict -- see the same guardrail.
    social_shape: SocialPreference = SocialPreference.EITHER
    accessibility_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class _OutreachPlan:
    """Everything the outreach planner needs, gathered while a session is open and carried
    forward after it closes.

    Built once, in the read phase, from a `PersonState` that is itself about to be discarded --
    the write phase always resolves its own, fresh `PersonState` and only reuses this plan's
    `ranked` candidate keys as a fingerprint of "the world the planner saw". Nothing here is
    trusted for persistence on its own; see `SqlAlchemyRepository._finalize_intervention`.
    """

    decision: Decision
    ranked: list[InterventionCandidate]
    deterministic: InterventionCandidate
    tool_context: ToolContext


@dataclass
class _OutreachTally:
    """One candidate's outreach outcomes as they are accumulated by `_outreach_responses`.

    Mutable and private on purpose: the frozen, shared shape is `world_model.OutreachResponseFact`,
    which this becomes. Every outcome the person can produce is its own counter -- an offer with
    no outcome row is `offered` and nothing else, and stays that way, because "still open" is not
    an answer and must never be folded into one.
    """

    offered: int = 0
    accepted: int = 0
    completed: int = 0
    declined: int = 0
    deferred: int = 0
    no_response: int = 0
    decline_reason: DeclineReason | None = None
    decline_reason_at: datetime | None = None


def _awaiting_reply_from(
    intervention: InterventionRow,
    latest_outcome: InterventionOutcomeRow | None,
    outreach_day: Callable[[], date],
) -> date | None:
    """The response clock's one rule: an offer still `proposed` with no outcome row waits for a
    reply until its outreach day plus `RESPONSE_WINDOW_DAYS`; anything else waits for nothing.
    `outreach_day` is only called when the answer needs it."""
    if intervention.status != "proposed":
        return None
    if latest_outcome is not None:
        return None
    return outreach_day() + timedelta(days=RESPONSE_WINDOW_DAYS)


def _confirmed_reference_from(latest: BaselineConfirmationRow | None) -> ConfirmedReference | None:
    """The confirmed reference a run's latest baseline decision carries, if that decision was
    `confirm` -- see `SqlAlchemyRepository._confirmed_reference`."""
    if latest is None or latest.decision != BaselineConfirmationDecision.CONFIRM.value:
        return None
    if latest.new_reference_steps is None:
        return None
    return ConfirmedReference(steps=latest.new_reference_steps, days=latest.streak_days)


# `session.info` key under which person rows read alongside their run are held for the session.
_HELD_PEOPLE_KEY: Final = "silverloop.held_people"

_OUTREACH_DECISIONS: Final[tuple[str, str]] = (
    Decision.GENTLE_NUDGE.value,
    Decision.PROGRAMME_SUGGESTION.value,
)


@dataclass
class _RunReads:
    """Everything `_evaluate` (and the caseload reads built on it) reads about one run.

    Loaded for many runs at once by `SqlAlchemyRepository._load_run_reads` -- one IN query per
    input set rather than a dozen queries per person -- and then read here by pure methods that
    are the single definition of each rule they answer. Nothing here writes, and a read set is
    only valid inside the session that loaded it.

    Every "latest" list is held in the order the database returned it for the same ORDER BY the
    per-run query used, so "the first one" means exactly what `.limit(1)` meant.
    """

    run_id: str
    person_id: str
    person: PersonRow | None = None
    # Day order.
    metric_rows: list[DailyMetricRow] = field(default_factory=list)
    # Latest first: `decided_on_day desc, confirmation_id desc`.
    confirmations: list[BaselineConfirmationRow] = field(default_factory=list)
    # Latest first: `recorded_at desc, evidence_id desc`.
    consents: list[ConsentEvidenceRow] = field(default_factory=list)
    # `answered_at` order.
    answers: list[ContextQuestionAnswerRow] = field(default_factory=list)
    # `decided_at, decision_id` order.
    threshold_rows: list[ReviewThresholdDecisionRow] = field(default_factory=list)
    # `created_at, intervention_id` order.
    interventions: list[InterventionRow] = field(default_factory=list)
    # The decision evidence's `observed_at` per intervention, only where that evidence exists.
    evidence_observed_at: dict[str, datetime] = field(default_factory=dict)
    # The follow-through report per intervention, only where one was made.
    follow_through: dict[str, str] = field(default_factory=dict)
    # Every outcome row of this run's interventions, latest first: `recorded_at desc, outcome_id
    # desc`. Scoped through the intervention's run, not the outcome row's own `run_id`.
    outcomes: list[InterventionOutcomeRow] = field(default_factory=list)
    # This person's day disputes -- person-scoped, not run-scoped -- latest first.
    disputes: list[DayDisputeRow] = field(default_factory=list)

    def outreach_day(self, intervention: InterventionRow) -> date:
        """`SqlAlchemyRepository._outreach_day`, off the evidence already loaded."""
        observed = self.evidence_observed_at.get(intervention.intervention_id)
        if observed is not None:
            return _as_utc(observed).date()
        return _as_utc(intervention.created_at).date()

    @property
    def consent_active(self) -> bool:
        latest = self.consents[0] if self.consents else None
        return bool(latest and latest.active)

    @property
    def latest_confirmation(self) -> BaselineConfirmationRow | None:
        return self.confirmations[0] if self.confirmations else None

    def confirmed_reference(self) -> ConfirmedReference | None:
        return _confirmed_reference_from(self.latest_confirmation)

    def stated_explanation(self, current_day: date) -> StatedExplanation | None:
        """The person's own explanation still in force on `current_day`, if any.

        Scoped to the run, like every other read in the decision path: a reset rewinds the
        simulated calendar, and an answer given in a story that no longer exists must not explain a
        day in the one that does.
        """
        return active_explanation(
            [(row.value, row.answered_on_day) for row in self.answers], day=current_day
        )

    @property
    def has_context_answer(self) -> bool:
        return bool(self.answers)

    def latest_outcome_by_intervention(self) -> dict[str, InterventionOutcomeRow]:
        latest: dict[str, InterventionOutcomeRow] = {}
        for outcome in self.outcomes:
            latest.setdefault(outcome.intervention_id, outcome)
        return latest

    def weekly_contact_count(self, current_day: date) -> int:
        """Contacts in the last `CONTACT_CAP_WINDOW_DAYS` simulated days -- see
        `SqlAlchemyRepository._weekly_contact_count` for why each clause is there."""
        cutoff = datetime.combine(
            current_day - timedelta(days=CONTACT_CAP_WINDOW_DAYS - 1), time.min, tzinfo=UTC
        )
        return sum(
            1
            for intervention in self.interventions
            if (observed := self.evidence_observed_at.get(intervention.intervention_id)) is not None
            and _as_utc(observed) >= cutoff
            and intervention.decision in _OUTREACH_DECISIONS
            and not intervention.status.startswith("withdrawn")
        )

    def days_since_last_accepted(self, current_day: date) -> int | None:
        """Scenario days since this person last took a suggestion up; `None` if they never have.

        Counted in their days, not wall-clock hours -- the same clock the weekly contact count and
        the response clock (`RESPONSE_WINDOW_DAYS`) keep. "Leave them space to get on with it" is
        a statement about the person's week and has to be counted in the days their week is.
        """
        by_id = {row.intervention_id: row for row in self.interventions}
        for outcome in self.outcomes:
            if outcome.outcome != OutcomeKind.ACCEPTED.value:
                continue
            intervention = by_id.get(outcome.intervention_id)
            if intervention is None:
                continue
            return max(0, (current_day - self.outreach_day(intervention)).days)
        return None

    def self_reported_conflict(self, day: date) -> tuple[bool, str | None]:
        """Whether the person has contradicted the sensor about this day, and in their words.

        Two doors, one statement: disputing the day outright, or declining a suggestion because
        they were already active. Neither changes the stored reading -- the device said what it
        said. Both are surfaced so nothing downstream can quietly treat a contested day as an
        uncontested one.
        """
        dispute = next((row for row in self.disputes if row.day == day), None)
        if dispute is not None and not dispute.accurate:
            return True, (
                dispute.note
                or "The person says this day's reading does not match the day they had."
            )
        declined_ids = {
            outcome.intervention_id
            for outcome in self.outcomes
            if outcome.outcome == OutcomeKind.DECLINED.value
            and outcome.reason == DeclineReason.ALREADY_ACTIVE.value
        }
        for intervention in self.interventions:
            if (
                intervention.intervention_id in declined_ids
                and self.outreach_day(intervention) == day
            ):
                return True, (
                    "The person declined this suggestion because they were already active; the "
                    "reading for this day and their own account of it disagree."
                )
        return False, None

    def awaiting_reply_until(
        self,
        intervention: InterventionRow,
        latest_outcomes: dict[str, InterventionOutcomeRow],
    ) -> date | None:
        """`SqlAlchemyRepository._awaiting_reply_until`, off the rows already loaded."""
        return _awaiting_reply_from(
            intervention,
            latest_outcomes.get(intervention.intervention_id),
            lambda: self.outreach_day(intervention),
        )

    def awaiting_reply_count(self) -> int:
        """Offers still inside their response window -- `OperationalMetrics.awaiting_reply`."""
        latest = self.latest_outcome_by_intervention()
        return sum(
            1
            for intervention in self.interventions
            if self.awaiting_reply_until(intervention, latest) is not None
        )

    def no_reply_recorded_count(self) -> int:
        """Offers whose latest outcome is `no_response`: `OperationalMetrics.no_reply_recorded`."""
        latest = self.latest_outcome_by_intervention()
        return sum(
            1
            for intervention in self.interventions
            if (outcome := latest.get(intervention.intervention_id)) is not None
            and outcome.outcome == OutcomeKind.NO_RESPONSE.value
        )


def _decline_reason_or_none(reason: str | None) -> DeclineReason | None:
    """A stored decline reason as its enum, or `None` for a reason nobody gave.

    A value the enum no longer knows -- a reason retired from `DeclineReason` with its rows still
    on disk -- reads as "no reason given" rather than raising or leaking the raw token onto the
    senior's page. The decline itself is unaffected: it is counted from `outcome`, never from
    this column, which has always been optional and skippable.
    """
    if reason is None:
        return None
    try:
        return DeclineReason(reason)
    except ValueError:
        return None


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _activity_decline_metric(day: date, previous_low_days: int) -> DailyMetric:
    """The synthetic `activity_declines` day: lower with each recent low day, floored. A module
    function so a test can feed a deeper synthetic decline through a real advance."""
    return DailyMetric(
        day=day,
        steps=max(2100, 3400 - previous_low_days * 450),
        active_minutes=max(12, 26 - previous_low_days * 4),
        sleep_hours=6.4,
        wear_hours=13.2,
    )


def _readable_candidate_label(key: str) -> str:
    """Fallback label for a candidate key absent from the title catalogue -- e.g. a bare
    decision name used as `candidate_key` when an intervention predates candidate ranking.
    """
    return key.replace(":", " ").replace("_", " ")


# The rung of `policy.decide` a review case can only have come from. `COORDINATOR_REVIEW` is
# returned only by the review block -- the person's review threshold, and behind it the absolute
# floor and the shadow check (ADR 0008), all "far enough below, for long enough" -- so this is a
# statement about the ladder, not a guess about a past decision. A decision class with no entry
# here yields no gate clause rather than a fabricated one, which is what would happen if a future
# rung ever started opening cases and nobody updated this map.
_CASE_GATE_BY_DECISION: dict[Decision, PolicyGate] = {
    Decision.COORDINATOR_REVIEW: PolicyGate.SEVERITY_PERSISTENCE,
}

_GATE_WHY_HUMAN: dict[PolicyGate, str] = {
    PolicyGate.SEVERITY_PERSISTENCE: (
        "Activity has stayed far enough below this person's own usual range, for enough "
        "valid-wear days, that Care+ stopped and asked a person."
    ),
}

_OUTREACH_NOUNS: dict[Decision, str] = {
    Decision.GENTLE_NUDGE: "a check-in",
    Decision.PROGRAMME_SUGGESTION: "a suggestion",
}


def _why_human(gate: PolicyGate | None, prior_outreach: list[PriorOutreach]) -> str:
    """One sentence saying why a case needs a human, from the gate that stopped and what was tried.

    Deliberately a template in code rather than anything generated. This sentence is the first
    thing a coordinator reads on a case, and a reviewer has to be able to be sure they are reading
    the policy's own output and not a model's paraphrase of it -- so every clause below is a fixed
    string selected by a fixed rule, and every number in it is a count of rows.

    Nothing is claimed that the inputs do not support. With no prior outreach it says so, because
    "two lighter steps were tried" would otherwise be a fabricated fact on the steep path where
    the ladder reached the review rung before it ever permitted a nudge. `outcome is None` means
    "nothing recorded" rather than "ignored", which is why the answered branch is phrased as what
    the person did rather than as what they failed to do.
    """
    clauses: list[str] = []
    if gate is not None and gate in _GATE_WHY_HUMAN:
        clauses.append(_GATE_WHY_HUMAN[gate])

    if not prior_outreach:
        clauses.append(
            "Nothing lighter was tried first: the change crossed the review threshold before any "
            "smaller step was permitted."
        )
        return " ".join(clauses)

    described = [
        f"{_OUTREACH_NOUNS.get(step.decision, 'an offer')} on {step.day.isoformat()}"
        for step in prior_outreach
    ]
    tried = f"{len(described)} lighter step{'' if len(described) == 1 else 's'} were tried"
    if len(described) == 1:
        tried = "1 lighter step was tried"
    # `NO_RESPONSE` is silence the response clock recorded once the window closed, not a reply.
    # Counting it as an answer would tell a coordinator that a person engaged with an offer they
    # never touched -- the exact conflation `OutcomeKind` exists to prevent.
    answered = [
        step
        for step in prior_outreach
        if step.outcome is not None and step.outcome != OutcomeKind.NO_RESPONSE.value
    ]
    if not answered:
        ending = "neither was answered" if len(described) == 2 else "none was answered"
    else:
        ending = (
            f"{len(answered)} of them {'was' if len(answered) == 1 else 'were'} answered, "
            "and the change continued"
        )
    clauses.append(f"{tried} ({'; '.join(described)}); {ending}.")
    return " ".join(clauses)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _fixture_checksum(seed: int, scenario_version: str, metrics: list) -> str:
    raw = f"{seed}:{scenario_version}:" + "|".join(
        f"{m.day},{m.steps},{m.wear_hours}" for m in metrics
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _as_utc(value: datetime) -> datetime:
    """Restore UTC when SQLite returns a timezone-naive timestamp."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sync_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url.replace("sqlite+aiosqlite", "sqlite+pysqlite").replace(
        "postgresql+asyncpg", "postgresql+psycopg"
    )


# ── Review setting, person by person (ADR 0008) ───────────────────────────────────────────────

FIXED_RULE_REFUSED: Final = (
    "The fixed rule's one-step proposal was refused by the deterministic safety gate, so the "
    "review setting stays as it is:"
)
# `fallback_reason` codes a threshold run record carries when the calibration agent did not supply
# the stored output for a reason of the repository's own (the loop's own reasons are recorded by
# `agent.threshold_planner`). Codes, not prose, so the Care Team card can label each truthfully.
#
# - after a rejection for any reason but `prefer_other_change`, the round ends with the fixed
#   rule's no-change and the model is not asked again (`fallback_disabled`);
AGENT_NOT_CONSULTED_AFTER_REJECTION: Final = "AGENT_NOT_CONSULTED_AFTER_REJECTION"
# - the false alarm's case opened before the live setting took effect, so it cannot count toward a
#   looser setting and the model is not asked (`fallback_disabled`);
AGENT_NOT_CONSULTED_STALE_TRIGGER: Final = "AGENT_NOT_CONSULTED_STALE_TRIGGER"
# - the agent's read-only context could not be gathered (`fallback_error`);
AGENT_CONTEXT_UNAVAILABLE: Final = "AGENT_CONTEXT_UNAVAILABLE"
# - the agent's approved output was refused by the guardrail re-run on fresh facts in Transaction B;
#   followed by the violations (`fallback_error`).
AGENT_OUTPUT_REFUSED: Final = "AGENT_OUTPUT_REFUSED"
# A revert's write-up is attempted at most this many times before it is abandoned (audited once).
WRITE_UP_MAX_ATTEMPTS: Final = 3
VIOLATION_STALE_TRIGGER: Final = (
    "The false alarm behind this proposal was raised on a case that opened before this person's "
    "current review setting took effect, so it cannot justify a looser setting."
)


# Tie-breaks for review-setting history shown to the calibration agent: after the simulated day and
# the wall clock (so same-day attempts read in the order they happened), and never by id. A
# stateless expiry and the daily checks run first in an advance, calibrator outputs precede the
# coordinator's decisions on them, and reverts and their write-ups close the day. Deterministic,
# so a replayed flow numbers `threshold:N` identically.
_HISTORY_KIND_ORDER: Final[dict[str, int]] = {
    ReviewThresholdDecisionKind.EXPIRED.value: 0,
    ReviewThresholdDecisionKind.CHECK_CONFIRMED.value: 1,
    ReviewThresholdDecisionKind.CHECK_UNRESOLVED.value: 1,
    ReviewThresholdOutputKind.PROPOSAL.value: 2,
    ReviewThresholdOutputKind.NO_CHANGE.value: 2,
    ReviewThresholdDecisionKind.REJECTED.value: 3,
    ReviewThresholdDecisionKind.APPROVED.value: 4,
    ReviewThresholdDecisionKind.RECONFIRMED.value: 5,
    ReviewThresholdDecisionKind.REVERTED.value: 6,
    ReviewThresholdOutputKind.WRITE_UP.value: 7,
}


def _violates_unique(error: IntegrityError, constraint: str, column: str) -> bool:
    """Whether `error` is a uniqueness violation on this one constraint (PostgreSQL names the
    constraint; SQLite names the column), and not some other integrity failure."""
    message = str(error.orig if error.orig is not None else error).lower()
    unique = "unique" in message or "duplicate key" in message
    return unique and (constraint.lower() in message or f".{column.lower()}" in message)


class _ThresholdCandidate(Protocol):
    """What any calibrator hands Transaction B: the fixed rule's `FixedRuleOutput` (calibrate or
    tighten), or the agent's `ThresholdAgentProposal` in the same shape."""

    @property
    def output_kind(self) -> ReviewThresholdOutputKind: ...
    @property
    def proposed(self) -> ReviewThreshold | None: ...
    @property
    def cause(self) -> ReviewThresholdCause | None: ...
    @property
    def reasoning(self) -> str: ...
    @property
    def cited(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class _ThresholdEpisode:
    """What the calibrator reads about one false alarm, gathered in a read session."""

    run_id: str
    person_id: str
    current_day: date
    live: ReviewThreshold
    trigger_reason: OverrideReason | None
    trigger: FalseAlarmRef
    trigger_case_id: str
    trigger_review_ids: tuple[str, ...]
    not_a_concern_alarms: tuple[FalseAlarmRef, ...]
    blocked_values: frozenset[ReviewThreshold]
    reported_by: str | None
    round_id: str
    round_index: int
    snapshot: tuple[str | None, str | None, bool, date]
    # The trigger case opened before the live setting took effect (stage-1 counting rule, trigger
    # included): it can never support a looser setting.
    trigger_predates_live: bool = False


@dataclass(frozen=True)
class _ThresholdFollowUp:
    """Work a review or an advance leaves for after its commit (ADR 0008, stage 3): read in a
    session, think with none open, write in a fresh transaction.

    - `write_up`: a revert of an agent or fixed-rule approval was written (`decision_id`);
    - `calibrate`: a false alarm may lead to a proposal;
    - `tighten`: "this should have reached me sooner" with nothing loosened live.
    """

    kind: Literal["write_up", "calibrate", "tighten"]
    run_id: str
    decision_id: str | None = None
    trigger_case_id: str | None = None
    trigger_review_ids: tuple[str, ...] = ()
    reported_by: str | None = None


class StaleRunConflict(ValueError):
    """The run a write was prepared against is no longer this person's current story: a demo reset
    deactivated it, or the simulated day moved on under an advance, between reading and taking the
    run lock. Nothing is written; re-reading resolves it. The API maps it to 409."""


# libpq drivers: both accept the `keepalives*` connection parameters.
_LIBPQ_DRIVERS: Final = frozenset({"psycopg", "psycopg2"})


def _engine_options(database_url: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """The `create_engine` keyword arguments for `database_url`. Pure: nothing connects.

    SQLite keeps a pre-ping (a local call costs nothing) and a single shared in-memory connection.
    A server database sits behind the Supabase session pooler, where every round trip is the
    expensive part of a request, so no checkout pays for a blanket pre-ping. Instead the pool is
    LIFO, connections are recycled before the pooler's idle timeout is likely to close them, and
    libpq connections get TCP keepalives so an idle socket is neither dropped by a middlebox nor
    left dead unnoticed. See `Settings.database_pool_*`.

    What guards a dropped connection is `_ping_connections_idle_since`, which `_create_engine`
    installs beside these options: a connection that sat in the pool for
    `database_pool_ping_idle_seconds` or longer is pinged on checkout and, if the ping fails,
    replaced by the pool before the checkout returns -- before any statement of that transaction
    runs. That matters most where a method commits one transaction and then opens another that
    writes: `advance()` commits the day's reading in its first transaction and writes the decision
    evidence, audit event and replay record in a second one, after the outreach planner may have
    run for seconds. Were that second checkout handed a dead connection, the day would be committed
    without its decision. LIFO makes the second checkout get the connection the first just
    returned, and the idle ping covers the case where that connection has sat long enough to have
    been dropped.

    What is not guaranteed: a connection returned less than the idle threshold ago is handed out
    unpinged, and a connection that dies mid-transaction fails that transaction (which rolls back
    whole). Neither is retried -- replaying a statement is only safe for one that wrote nothing.
    """
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        options: dict[str, Any] = {
            "pool_pre_ping": True,
            "connect_args": {"check_same_thread": False},
        }
        if url.database == ":memory:":
            options["poolclass"] = StaticPool
        return options

    pool = settings or get_settings()
    options = {
        "pool_pre_ping": pool.database_pool_pre_ping,
        "pool_recycle": pool.database_pool_recycle_seconds,
        "pool_size": pool.database_pool_size,
        "max_overflow": pool.database_max_overflow,
        "pool_use_lifo": pool.database_pool_use_lifo,
    }
    if (
        url.get_backend_name() == "postgresql"
        and url.get_driver_name() in _LIBPQ_DRIVERS
        and pool.database_pool_keepalives
    ):
        keepalives = {
            "keepalives": 1,
            "keepalives_idle": pool.database_pool_keepalives_idle_seconds,
            "keepalives_interval": pool.database_pool_keepalives_interval_seconds,
            "keepalives_count": pool.database_pool_keepalives_count,
        }
        # A value written into the URL is an explicit choice for that database: keep it.
        connect_args = {name: value for name, value in keepalives.items() if name not in url.query}
        if connect_args:
            options["connect_args"] = connect_args
    return options


# `ConnectionPoolEntry.info` key: when the connection was last returned to the pool (monotonic).
_RETURNED_AT: Final = "silverloop_returned_at"


def _ping_connections_idle_since(
    engine: Engine, idle_seconds: float, *, clock: Callable[[], float] = monotonic
) -> None:
    """Ping a pooled connection on checkout when it has been idle for `idle_seconds` or longer.

    The cheap half of a pre-ping: a connection handed straight back out (the common case under a
    LIFO pool) costs no round trip, while one that sat in the pool long enough for the pooler or
    the network to have dropped it is checked before anything uses it. A failed ping raises
    `DisconnectionError` from the pool's `checkout` event, which SQLAlchemy's pool handles by
    invalidating that connection and checking out a fresh one in its place -- the checkout that
    triggered it then succeeds, and no statement ever ran on the dead connection. A brand-new
    connection carries no return time and is never pinged. If the database cannot be reached at
    all, connecting the replacement fails and that error propagates as it would without this.
    """
    dialect = engine.dialect

    def on_checkin(dbapi_connection: Any, connection_record: Any) -> None:
        connection_record.info[_RETURNED_AT] = clock()

    def on_checkout(dbapi_connection: Any, connection_record: Any, connection_proxy: Any) -> None:
        returned_at = connection_record.info.pop(_RETURNED_AT, None)
        if returned_at is None or clock() - returned_at < idle_seconds:
            return
        try:
            dialect.do_ping(dbapi_connection)
        except dialect.loaded_dbapi.Error as error:
            raise DisconnectionError(
                f"Pooled connection failed its ping after {idle_seconds:g}s idle"
            ) from error

    sa_event.listen(engine, "checkin", on_checkin)
    sa_event.listen(engine, "checkout", on_checkout)


class SqlAlchemyRepository:
    """Durable SQLAlchemy repository; deterministic policy remains a pure dependency."""

    def __init__(
        self,
        database_url: str,
        *,
        seed: int = 2026,
        scenario_version: str = "v1",
        context_provider: ExternalContextProvider | None = None,
        settings: Settings | None = None,
        threshold_client_factory: Callable[[], tuple[Any, str | None]] | None = None,
        authored_metric: Callable[[str, date], DailyMetric | None] | None = None,
    ) -> None:
        # Resolved lazily via the `settings` property so a repository constructed without one
        # (every existing test does) keeps working and simply reads the process defaults, where
        # `llm_enabled` is false and the planner never runs.
        self._settings = settings
        # Whether resets follow today is decided by the settings passed here, never by the
        # process defaults the property above may resolve later: a repository built without
        # settings (the YAML scenarios, the Supabase smoke) keeps the fixture's anchor day on
        # every reset, however many it makes.
        self._demo_dates_follow_today = settings is not None and settings.demo_dates_follow_today
        self.seed = seed
        self.scenario_version = scenario_version
        self.database_url = _sync_database_url(database_url)
        self.engine = self._create_engine(self.database_url, settings=settings)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        # Optional live weather/holiday context (silverloop.context), default None: the five
        # scripted simulation events (including `rain_explains_decline`) always determine
        # `ContextSignal` on their own; live context only ORs in additional true signals on top,
        # it never overrides or races the simulator.
        self._context_provider = context_provider
        # The review-threshold calibration agent's transport (ADR 0008, stage 2). `None` builds the
        # configured provider's client; a test or the replay recorder substitutes a fake or a
        # recording. Read only when `llm_enabled` is true.
        self._threshold_client_factory = threshold_client_factory
        # The calibration evaluation's seam (docs/calibration-trust-spec.md, section D): given the
        # person and the day being advanced to, an authored metric replaces the one the event
        # would generate. Every other effect of the event (context, consent, plans) is unchanged,
        # and `consent_revoked` is never overridden. In-process only: not on the Protocol, not
        # over HTTP. `None` (the default) leaves every event exactly as it was.
        self._authored_metric = authored_metric

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @staticmethod
    def _create_engine(database_url: str, *, settings: Settings | None = None) -> Engine:
        url = make_url(database_url)
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(database_url, **_engine_options(database_url, settings=settings))
        if url.get_backend_name() != "sqlite":
            pool = settings or get_settings()
            if not pool.database_pool_pre_ping:
                _ping_connections_idle_since(engine, pool.database_pool_ping_idle_seconds)
        return engine

    def create_schema_for_tests(self) -> None:
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    # Public ORM tables whose row-level security is off. Restricted to the names the ORM defines
    # so a table outside Care+'s own schema (or `alembic_version`, deliberately excluded --
    # see `infra/supabase/rls_posture_check.sql`) cannot make the service look unready.
    _OPEN_TABLES_SQL = text(
        "select c.relname from pg_class c "
        "join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' "
        "and not c.relrowsecurity and c.relname = any(:names) "
        "order by c.relname"
    )

    def readiness(self, runtime_profile: str) -> ReadinessResponse:
        backend = self.engine.url.get_backend_name()
        connected = False
        migration_revision: str | None = None
        tables_without_rls: list[str] = []
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                connected = True
                try:
                    migration_revision = connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                except SQLAlchemyError:
                    migration_revision = None
                if backend == "postgresql":
                    # `migrations.apply_rls_posture` establishes this on every start, but a
                    # posture nobody checks is a posture nobody notices losing: a table created
                    # outside Alembic, or a `disable row level security` run in a SQL console,
                    # is invisible until something looks. A failed apply is invisible too --
                    # it is logged and deliberately does not stop the process -- so this is the
                    # surface that reports it.
                    try:
                        tables_without_rls = list(
                            connection.scalars(
                                self._OPEN_TABLES_SQL.bindparams(names=sorted(Base.metadata.tables))
                            )
                        )
                    except SQLAlchemyError:
                        # A catalogue query that cannot run tells us nothing either way; the
                        # revision check below still decides readiness.
                        tables_without_rls = []
        except SQLAlchemyError:
            connected = False
        expected_revision = expected_database_revision()
        ready = connected and migration_revision == expected_revision and not tables_without_rls
        return ReadinessResponse(
            status="ready" if ready else "not_ready",
            database_backend=backend,
            runtime_profile=runtime_profile,
            database_connected=connected,
            migration_revision=migration_revision,
            expected_migration_revision=expected_revision,
            tables_without_rls=tables_without_rls,
        )

    def ensure_active_run(self, *, person_id: str = DEMO_PERSON_ID) -> None:
        with self.sessions() as session:
            active = session.scalar(
                select(ScenarioRunRow).where(
                    ScenarioRunRow.active.is_(True),
                    ScenarioRunRow.person_id == person_id,
                )
            )
        if active is None:
            self.reset(person_id=person_id)
            return

        # A run already exists, so `reset()` is deliberately not called -- but the activity
        # catalogue is reference data rather than run state, and a database created before the
        # catalogue existed has an active run and no listings. Left unseeded, "Ask Care+"
        # answers every request with "nothing quite matched that" on a freshly started demo, which
        # looks like a working feature finding nothing rather than an empty table. The seeder is
        # idempotent, so this is a no-op once the listings are there.
        with self.sessions.begin() as session:
            self._seed_activity_candidates(session, active.current_day)
            self._refresh_stale_activities(session, active.current_day)

    def reset(
        self,
        *,
        person_id: str = DEMO_PERSON_ID,
        allow_new_person: bool = False,
        end_on: date | None = None,
    ) -> DemoResetResponse:
        """Start a demo person's story over from their synthetic fixture.

        `end_on` moves every fixture day by one offset so the latest reading falls on it: the same
        values, in the same order, only the dates change. Without it, an app whose settings say
        `demo_dates_follow_today` ends the readings on today (Singapore); otherwise they keep the
        fixture's own anchor day, which every scenario and pinned test relies on. A repository
        built without settings (the YAML scenarios, the Supabase smoke) always keeps the
        anchor day. Only the synthetic fixture is written here, so a real reading is never moved.
        """
        now = _utcnow()
        if end_on is None and self._demo_dates_follow_today:
            end_on = local_date(now)
        profile = persona_profile(person_id)
        fixture_batch = SyntheticFixtureAdapter(
            persona_seed(person_id, self.seed), person_id=person_id
        ).read(end_on=end_on, now=now)
        # The programmes follow the readings by the same offset as Mdm Lim's anchor day.
        programme_shift = end_on - DEMO_ANCHOR_DAY if end_on is not None else timedelta(0)
        current = fixture_batch.metrics[-1]
        run_id = _id("run")
        checksum = _fixture_checksum(self.seed, self.scenario_version, fixture_batch.metrics)
        with self.sessions.begin() as session:
            session.execute(
                update(ScenarioRunRow)
                .where(ScenarioRunRow.active.is_(True), ScenarioRunRow.person_id == person_id)
                .values(active=False, ended_at=now)
            )
            # A reset starts the story over on the fixture's anchor day. It used to delete every
            # `activity_dimension_preferences` row here -- the only place this repository
            # destroyed derived domain state -- because the table carried no notion of which
            # run's story a row's evidence came from. It no longer deletes anything: `run_id`
            # (see `db_models.ActivityDimensionPreferenceRow`, ADR 0004) does that job instead.
            # A *standing* `senior_statement` row (the person's own words, no `until`) keeps
            # `run_id = None` and is never run-scoped; like the outreach mutes below, it is a
            # standing instruction, not learning, and carries into the new run unchanged. Every
            # other row -- a *time-boxed* `senior_statement` (an `until` day) or a
            # `decline_reason` / `inferred` one -- stays tagged with the run that produced it;
            # `_dimension_rows` treats a row whose `run_id` is not the new run's as absent, exactly
            # like a calendar-expired row, so the world model and ranking never show a belief, or a
            # promise about a day, from a story that no longer exists -- and never resurrect a
            # promise that had already lapsed just because the calendar fell behind it again. The
            # row is still there -- reused in place, not resurrected -- if the same kind of
            # evidence is observed again.
            if session.get(PersonRow, person_id) is None:
                if person_id not in DEMO_PERSONAS and not allow_new_person:
                    raise ValueError(
                        f"Unknown person_id {person_id!r}; pass allow_new_person=True to "
                        "explicitly provision a new person record."
                    )
                session.add(
                    PersonRow(
                        person_id=person_id,
                        display_name=profile.display_name,
                        preferred_language=profile.preferred_language,
                        created_at=now,
                    )
                )
            run = ScenarioRunRow(
                run_id=run_id,
                person_id=person_id,
                seed=self.seed,
                scenario_version=self.scenario_version,
                current_day=current.day,
                active=True,
                started_at=now,
            )
            session.add(run)
            session.flush()
            for metric in fixture_batch.metrics:
                session.add(self._canonical_metric_row(run_id, person_id, metric, now))
            consent = ConsentEvidenceRow(
                evidence_id=_id("consent"),
                run_id=run_id,
                person_id=person_id,
                active=True,
                reason="Synthetic demo consent fixture activated on reset.",
                actor="system",
                source="synthetic_fixture",
                recorded_at=now,
            )
            session.add(consent)
            self._seed_programmes(session, programme_shift)
            self._seed_activity_candidates(session, current.day)
            # The calendar has just been rewound to `current.day`; the catalogue follows it back.
            # Listings are fixture data, not person data -- no row is deleted and no `activity_id`
            # moves, so a plan or an offer response that names one still resolves.
            self._reanchor_fixture_sessions(session, current.day)
            session.add(
                self._audit_row(
                    run_id,
                    "demo_reset",
                    "system",
                    person_id=person_id,
                    detail={
                        "seed": self.seed,
                        "scenario_version": self.scenario_version,
                        "fixture_checksum": checksum,
                        "source_classification": "synthetic_fixture",
                        "adapter_disclosure": fixture_batch.disclosure,
                        "consent_evidence_id": consent.evidence_id,
                    },
                    at=now,
                )
            )
            session.flush()
            state = self._person_state(session, run)
        return DemoResetResponse(
            state=state,
            seed=self.seed,
            scenario_version=self.scenario_version,
            fixture_checksum=checksum,
        )

    def _seed_programmes(self, session: Session, shift: timedelta = timedelta(0)) -> None:
        for programme in synthetic_programmes(shift):
            existing = session.get(ProgrammeRow, programme.programme_id)
            if existing is not None:
                # Fixture data, not person data, and only ever seeded here: a reset puts its
                # sessions where the fixture puts them for the new run's days (the same row, so
                # anything that names it still resolves). Done with or without a shift, so a
                # reset that keeps the anchor day after one that followed today moves them back.
                existing.next_session = programme.next_session
                existing.valid_until = programme.next_session + timedelta(days=7)
                continue
            session.add(
                ProgrammeRow(
                    programme_id=programme.programme_id,
                    name=programme.name,
                    venue=programme.venue,
                    distance_km=programme.distance_km,
                    next_session=programme.next_session,
                    accessibility_json=programme.accessibility,
                    evidence_source=programme.evidence_source,
                    valid_until=programme.next_session + timedelta(days=7),
                )
            )

    def _refresh_stale_activities(self, session: Session, today: date) -> None:
        """Roll any listing whose session has already happened forward to its next weekly slot.

        The catalogue is seeded once and its session times are anchored to the day of that first
        seed. The simulation then advances -- the drift scenario alone runs eighteen days -- so
        without this every listing falls into the past and `_wrong_day` filters the entire
        catalogue as "already ran". Measured before this existed: three simulated days after a
        reset, every activity search returned nothing, for the rest of the run.

        Rolling in whole weeks preserves both the weekday and the local time of day, so a Wednesday
        morning class stays a Wednesday morning class. It changes when a fixture session happens,
        never what it is -- and these are labelled fixtures whose times were always anchored to the
        simulated timeline rather than claimed as real bookings.
        """
        rows = session.scalars(
            select(ActivityCandidateRow).where(ActivityCandidateRow.start_at.is_not(None))
        )
        for row in rows:
            start = _as_utc(row.start_at)
            if local_date(start) >= today:
                continue
            while local_date(start) < today:
                start += timedelta(days=7)
            row.start_at = start

    def _reanchor_fixture_sessions(self, session: Session, anchor_day: date) -> None:
        """Put every fixture listing's session back on the day the fixture puts it on `anchor_day`.

        **This is the simulated story restarting, not a claim about a real venue.** Nothing here
        says a centre moved, cancelled or rescheduled a class. These listings are fixtures whose
        session times were only ever anchored to the simulated calendar (`fixtures.py`'s
        `_Session.days_ahead` counts days from the scenario's own "today"), and `reset()` rewinds
        that calendar to the fixture's anchor day. The catalogue has to start over with it.

        Without this, the catalogue survived a reset while the calendar did not. The catalogue is
        global and rolls *forward* only (`_refresh_stale_activities` adds whole weeks once a
        simulated day passes a session), so a browser run that advanced several days and then
        reset left every listing a week or more ahead of a rewound today: "something outdoors
        tomorrow" matched nothing, for the whole new run. Measured on the default persona --
        anchor day 2026-08-18, five listings on the day after it; eight `advance()` calls and one
        `reset()` later, zero.

        Only rows this repository seeded (`metadata_source == _FIXTURE_METADATA_SOURCE`, stamped
        by `_seed_activity_candidates`, which runs immediately before this) and whose
        `activity_id` is still in the fixture set are moved. A listing from a real feed keeps its
        own `metadata_source` and is never touched: its session time is a fact about the world,
        not about this story. No row is deleted and no `activity_id` changes -- `week_plan_entries`
        and `activity_offer_responses` reference them, and a retired listing keeps its identity so
        a plan that names it still resolves.

        The catalogue is global while every persona has its own anchor day, so a reset cannot put
        the listings back for one persona without moving them for everyone. It must not strand a
        run that is still being played: rewound to `mdm-lim`'s anchor and then rewound *again* by a
        second persona's reset eighty days earlier, every listing fell out of `mdm-lim`'s live week
        and "add to my week" started rejecting the only activities the catalogue had. So the rewind
        is floored at the furthest-ahead active run: re-anchor first, then hand the result to
        `_refresh_stale_activities` with that day, which moves each listing by a whole number of
        weeks and so keeps its time of day and its position within the week the fixture gave it.
        (The week the fixture gives it is the new anchor's, not the old one's -- re-anchoring to a
        persona whose anchor day falls on a different weekday genuinely changes which weekday a
        class lands on. These are fixtures anchored to a simulated calendar; nothing here claims a
        centre moved a class.) With one active persona -- the demo, the offline run and the browser
        suite -- the floor *is* that persona's own anchor day and nothing rolls, which is exactly
        the fix above. With several, a persona behind the floor sees its listings sit further out
        until it catches up; that is unchanged from before this method existed, when the catalogue
        was simply frozen wherever the first reset left it. A genuinely per-run catalogue is the
        real answer if concurrent personas ever stop being a demo-only concern.
        """
        anchored = {
            candidate.activity_id: candidate.start_at
            for candidate in synthetic_activity_candidates(anchor_day)
            if candidate.start_at is not None
        }
        if not anchored:
            return
        rows = session.scalars(
            select(ActivityCandidateRow).where(
                ActivityCandidateRow.metadata_source == _FIXTURE_METADATA_SOURCE,
                ActivityCandidateRow.activity_id.in_(sorted(anchored)),
            )
        )
        for row in rows:
            row.start_at = anchored[row.activity_id]
        # The caller has already flushed the new run, so this sees the rewound calendar too and
        # the floor is `anchor_day` itself whenever no other run is further ahead.
        furthest_active_day = session.scalar(
            select(func.max(ScenarioRunRow.current_day)).where(ScenarioRunRow.active.is_(True))
        )
        self._refresh_stale_activities(session, max(anchor_day, furthest_active_day or anchor_day))

    def _seed_activity_candidates(self, session: Session, today: date) -> None:
        """Reconcile the catalogue with the current fixture set.

        A global catalogue, not scoped to the run being reset. Session times are left where they
        are here; only `reset()` moves them, through `_reanchor_fixture_sessions`, because only a
        reset rewinds the calendar they are anchored to. An API restart (`ensure_active_run`) is
        not a new story and must not reschedule a session someone has already planned for.

        This used to skip any row whose `activity_id` already existed, which quietly made the
        catalogue permanently whatever it was on the day it was first seeded. Rows created before
        the listings gained addresses, transport, booking and contact details kept `NULL` in every
        one of those columns forever, so a database seeded early showed activities with no detail
        at all and no way to acquire any -- which is precisely the "nothing to go on" problem the
        richer fields were added to solve.

        Existing rows are therefore refreshed in place. Stale rows are left alone rather than
        deleted: `week_plan_entries.activity_id` is a foreign key, so removing a listing a person
        has already planned would either fail or take their plan with it.
        """
        for candidate in synthetic_activity_candidates(today):
            existing = session.get(ActivityCandidateRow, candidate.activity_id)
            if existing is not None:
                # Everything except `start_at`; see the docstring above and
                # `_reanchor_fixture_sessions`. `availability` *is* refreshed here, which is what
                # puts a listing `programme_becomes_full` flipped to FULL back to its fixture
                # value -- the same story-restart rule, applied to the other catalogue column the
                # simulator mutates.
                existing.title = candidate.title
                existing.provider = candidate.provider
                existing.location_name = candidate.location.name
                existing.location_address = candidate.location.address
                existing.location_postal_code = candidate.location.postal_code
                existing.category = candidate.category
                existing.activity_type = (
                    candidate.activity_type.value if candidate.activity_type is not None else None
                )
                existing.activity_families_json = [
                    family.value for family in candidate.activity_families
                ]
                existing.format = candidate.format.value if candidate.format is not None else None
                existing.metadata_source = _FIXTURE_METADATA_SOURCE
                existing.distance_basis = candidate.distance_basis.value
                existing.indoor_outdoor = candidate.indoor_outdoor.value
                existing.social_shape = (
                    candidate.social_shape.value if candidate.social_shape is not None else None
                )
                existing.intensity = (
                    candidate.intensity.value if candidate.intensity is not None else None
                )
                existing.accessibility_tags_json = list(candidate.accessibility_tags)
                existing.language_tags_json = list(candidate.language_tags)
                existing.capacity = candidate.capacity
                existing.availability = candidate.availability.value
                existing.price = candidate.price
                existing.distance_m = candidate.distance_m
                existing.description = candidate.description
                existing.duration_minutes = candidate.duration_minutes
                existing.what_to_bring_json = list(candidate.what_to_bring)
                existing.booking = candidate.booking.value
                existing.booking_note = candidate.booking_note
                existing.contact_phone = candidate.contact_phone
                existing.contact_note = candidate.contact_note
                existing.getting_there_json = list(candidate.getting_there)
                existing.good_to_know_json = list(candidate.good_to_know)
                continue
            session.add(
                ActivityCandidateRow(
                    activity_id=candidate.activity_id,
                    source=candidate.source.value,
                    integration_status=candidate.integration_status.value,
                    title=candidate.title,
                    provider=candidate.provider,
                    start_at=candidate.start_at,
                    location_name=candidate.location.name,
                    location_address=candidate.location.address,
                    location_postal_code=candidate.location.postal_code,
                    location_latitude=candidate.location.latitude,
                    location_longitude=candidate.location.longitude,
                    category=candidate.category,
                    activity_type=(
                        candidate.activity_type.value
                        if candidate.activity_type is not None
                        else None
                    ),
                    activity_families_json=[family.value for family in candidate.activity_families],
                    format=candidate.format.value if candidate.format is not None else None,
                    # A fixture listing's facts came from this repository, and nobody has checked
                    # them against a real centre -- so `last_verified_at` stays null rather than
                    # claiming an assurance the catalogue does not have.
                    metadata_source=_FIXTURE_METADATA_SOURCE,
                    indoor_outdoor=candidate.indoor_outdoor.value,
                    social_shape=(
                        candidate.social_shape.value if candidate.social_shape is not None else None
                    ),
                    intensity=candidate.intensity.value if candidate.intensity else None,
                    accessibility_tags_json=candidate.accessibility_tags,
                    language_tags_json=candidate.language_tags,
                    capacity=candidate.capacity,
                    availability=candidate.availability.value,
                    price=candidate.price,
                    source_url=candidate.source_url,
                    retrieved_at=candidate.retrieved_at,
                    distance_m=candidate.distance_m,
                    distance_basis=candidate.distance_basis.value,
                    description=candidate.description,
                    duration_minutes=candidate.duration_minutes,
                    what_to_bring_json=list(candidate.what_to_bring),
                    booking=candidate.booking.value,
                    booking_note=candidate.booking_note,
                    contact_phone=candidate.contact_phone,
                    contact_note=candidate.contact_note,
                    getting_there_json=list(candidate.getting_there),
                    good_to_know_json=list(candidate.good_to_know),
                )
            )

    @staticmethod
    def _canonical_metric_row(
        run_id: str,
        person_id: str,
        metric: CanonicalDailyMetric,
        recorded_at: datetime,
    ) -> DailyMetricRow:
        return DailyMetricRow(
            metric_id=_id("metric"),
            evidence_id=f"{run_id}_{metric.evidence_id}",
            run_id=run_id,
            person_id=person_id,
            day=metric.day,
            observed_at=metric.observed_at,
            steps=metric.steps,
            active_minutes=metric.active_minutes,
            sleep_hours=metric.sleep_hours,
            wear_hours=metric.wear_hours,
            source=metric.source,
            fixture_classification=metric.source_classification.value,
            ingestion_confidence=metric.ingestion_confidence,
            context_json=metric.context.model_dump(mode="json"),
            recorded_at=recorded_at,
        )

    @staticmethod
    def _metric_row(
        run_id: str,
        person_id: str,
        metric: DailyMetric,
        context: ContextSignal,
        recorded_at: datetime,
    ) -> DailyMetricRow:
        observed_at = datetime.combine(metric.day, time(hour=12), tzinfo=UTC)
        return DailyMetricRow(
            metric_id=_id("metric"),
            evidence_id=_id("wearable"),
            run_id=run_id,
            person_id=person_id,
            day=metric.day,
            observed_at=observed_at,
            steps=metric.steps,
            active_minutes=metric.active_minutes,
            sleep_hours=metric.sleep_hours,
            wear_hours=metric.wear_hours,
            source=metric.source,
            fixture_classification="synthetic_fixture",
            ingestion_confidence=1.0,
            context_json=context.model_dump(mode="json"),
            recorded_at=recorded_at,
        )

    @staticmethod
    def _to_metric(row: DailyMetricRow) -> DailyMetric:
        return DailyMetric(
            day=row.day,
            steps=row.steps,
            active_minutes=row.active_minutes,
            sleep_hours=row.sleep_hours,
            wear_hours=row.wear_hours,
            source=row.source,
        )

    @staticmethod
    def _active_run(session: Session, person_id: str) -> ScenarioRunRow:
        # No DB constraint enforces one active run per person -- two concurrent `reset()` calls
        # can each deactivate the old run and insert a new active one before the other's UPDATE
        # commits, leaving two active rows. `order_by` + `limit(1)` makes the *selection*
        # deterministic (the most recently started active run wins) so that race degrades to
        # "picked one sensibly" instead of every later call raising `MultipleResultsFound`. It
        # does not close the window itself; a partial unique index would, and is intentionally
        # left for a follow-up rather than added this close to the demo.
        #
        # One round trip for both questions -- does the person exist, and which run is active --
        # because every person-scoped read starts here: the person is outer-joined to their active
        # runs, so no row means no person (`KeyError`) and a row without a run means no active run.
        # The person row lands in the identity map, so a later `session.get(PersonRow, ...)` in
        # the same session costs nothing.
        found = session.execute(
            select(PersonRow, ScenarioRunRow)
            .select_from(PersonRow)
            .outerjoin(
                ScenarioRunRow,
                and_(
                    ScenarioRunRow.person_id == PersonRow.person_id,
                    ScenarioRunRow.active.is_(True),
                ),
            )
            .where(PersonRow.person_id == person_id)
            .order_by(ScenarioRunRow.started_at.desc(), ScenarioRunRow.run_id.desc())
            .limit(1)
        ).first()
        if found is None:
            raise KeyError(person_id)
        SqlAlchemyRepository._hold_people(session, [found[0]])
        run = found[1]
        if run is None:
            raise RuntimeError("No active scenario run. Run the demo reset first.")
        return run

    @staticmethod
    def _consent_active(session: Session, run_id: str) -> bool:
        evidence = session.scalar(
            select(ConsentEvidenceRow)
            .where(ConsentEvidenceRow.run_id == run_id)
            .order_by(ConsentEvidenceRow.recorded_at.desc(), ConsentEvidenceRow.evidence_id.desc())
            .limit(1)
        )
        return bool(evidence and evidence.active)

    def _load_metrics(
        self, session: Session, run_id: str
    ) -> tuple[list[DailyMetric], DailyMetric, ContextSignal, DailyMetricRow]:
        rows = list(
            session.scalars(
                select(DailyMetricRow)
                .where(DailyMetricRow.run_id == run_id)
                .order_by(DailyMetricRow.day)
            )
        )
        if not rows:
            raise RuntimeError("Active scenario contains no wearable metrics.")
        current_row = rows[-1]
        return (
            [self._to_metric(row) for row in rows[:-1]],
            self._to_metric(current_row),
            ContextSignal.model_validate(current_row.context_json),
            current_row,
        )

    def _weekly_contact_count(self, session: Session, run_id: str, current_day: date) -> int:
        """Contacts made in the person's last `CONTACT_CAP_WINDOW_DAYS` simulated days.

        Read off the decision evidence's `observed_at` -- the day the person actually lived --
        rather than `created_at`, which is the machine's wall clock and moves with it (see
        `_outreach_day`). The window is `current_day` and the six days before it, so an offer made
        seven simulated days ago has left the budget by today regardless of how many real seconds
        passed in between.

        The rule itself is `_RunReads.weekly_contact_count`, which `_evaluate` reads off rows loaded
        for the whole caseload at once. Its clauses, in the order they apply:

        - Only an intervention whose decision evidence exists and was observed inside the window.
        - A positive allow-list of decisions rather than excluding COORDINATOR_REVIEW: only these
          two decisions ever produce an intervention row, so the old negative filter could never
          match and read as a safety carve-out that did nothing.
        - An offer withdrawn when consent was revoked was never received, so it must not spend the
          person's weekly contact budget. Without this, withdrawing and re-granting consent left
          them capped having been sent nothing.
        """
        run = session.get(ScenarioRunRow, run_id)
        if run is None:
            return 0
        reads = {run_id: _RunReads(run_id=run_id, person_id=run.person_id)}
        self._load_run_interventions(session, reads)
        return reads[run_id].weekly_contact_count(current_day)

    @staticmethod
    def _outreach_day(session: Session, intervention: InterventionRow) -> date:
        """The scenario day one intervention was decided on.

        Read off the decision evidence rather than `created_at`: `created_at` is wall-clock and
        moves with the machine, while `observed_at` is the day the person actually lived, which
        is the clock everything else in this loop is measured in.
        """
        decision_row = session.get(DecisionEvidenceRow, intervention.decision_evidence_id)
        if decision_row is not None:
            return _as_utc(decision_row.observed_at).date()
        return _as_utc(intervention.created_at).date()

    def _awaiting_reply_until(
        self,
        session: Session,
        row: InterventionRow,
        *,
        outcome_row: InterventionOutcomeRow | None | bool = False,
    ) -> date | None:
        """The first simulated day the response clock treats `row` as unanswered, or `None`.

        Derived, never stored: outreach day plus `RESPONSE_WINDOW_DAYS`, and only while the offer
        is genuinely still open -- `proposed`, with no outcome row. Anything answered, withdrawn or
        already closed has nothing to wait for. Callers that have already fetched the latest
        outcome row pass it (or `None`) as `outcome_row` so the listing paths do not query it a
        second time; the default sentinel means "look it up".
        """
        if row.status != "proposed":
            return None
        latest = (
            self._latest_outcome_row(session, row.intervention_id)
            if outcome_row is False
            else outcome_row
        )
        return _awaiting_reply_from(
            row,
            latest if isinstance(latest, InterventionOutcomeRow) else None,
            lambda: self._outreach_day(session, row),
        )

    def _resolve_unanswered_outreach(
        self, session: Session, run: ScenarioRunRow, current_day: date, now: datetime
    ) -> list[str]:
        """Close every offer whose response window has passed, recording `no_response`.

        The same transition `record_outcome` performs when a senior answers -- one append-only
        `InterventionOutcomeRow`, `status` to `closed`, one audit event -- with actor `system` and
        the reason it fired written into the audit detail. Nothing else that a decline triggers
        applies: silence is not a decline, so no decline reason reaches the dimensional learner
        and it never counts toward `DECLINES_BEFORE_SUPPRESSION`. The per-candidate posterior
        still moves, because `_preference_learners` is rebuilt from outcome rows and `learning.py`
        already weights `no_response` at half a unit against the candidate.

        Runs inside `advance()`'s read-phase transaction, so an offer the senior answers in the
        same instant is protected by the outcome-row check here and by `record_outcome`'s own
        duplicate guard: whichever transaction commits second sees the other's row.
        """
        if not self._consent_active(session, run.run_id):
            # Revocation already withdrew every open offer (`_withdraw_open_interventions`); a
            # withdrawn offer was never received and is not silence.
            return []
        resolved: list[str] = []
        # `with_for_update` is what makes "a human answer always wins" true on PostgreSQL: it
        # serialises this pass against a `record_outcome` racing for the same row, so whichever
        # commits second sees the other's outcome row -- the senior's path through its duplicate
        # guard, this one through the re-check below. A no-op on SQLite, which is single-writer.
        rows = list(
            session.scalars(
                select(InterventionRow)
                .where(
                    InterventionRow.run_id == run.run_id,
                    InterventionRow.status == "proposed",
                )
                .order_by(InterventionRow.created_at, InterventionRow.intervention_id)
                .with_for_update()
            )
        )
        for row in rows:
            due = self._awaiting_reply_until(session, row)
            if due is None or current_day < due:
                continue
            candidate_key = self._candidate_key_of(row)
            _, before_learner = self._preference_learners(session, row.person_id)
            preference_before = before_learner.expected_value(candidate_key)
            outcome_row = InterventionOutcomeRow(
                outcome_id=_id("outcome"),
                intervention_id=row.intervention_id,
                run_id=row.run_id,
                outcome=OutcomeKind.NO_RESPONSE.value,
                reason=None,
                actor="system",
                reviewer=None,
                recorded_at=now,
            )
            session.add(outcome_row)
            row.status = "closed"
            session.flush()
            _, after_learner = self._preference_learners(session, row.person_id)
            preference_after = after_learner.expected_value(candidate_key)
            session.add(
                self._audit_row(
                    row.run_id,
                    "intervention_outcome_recorded",
                    "system",
                    person_id=row.person_id,
                    decision=Decision(row.decision),
                    detail={
                        "intervention_id": row.intervention_id,
                        "outcome_evidence_id": outcome_row.outcome_id,
                        "outcome": OutcomeKind.NO_RESPONSE.value,
                        "reason": None,
                        "resolved_by": "response_window",
                        "response_window_days": RESPONSE_WINDOW_DAYS,
                        "awaiting_reply_until": due.isoformat(),
                        "resolved_on_day": current_day.isoformat(),
                        "decision_evidence_id": row.decision_evidence_id,
                        "candidate_key": candidate_key,
                        "preference_before": preference_before,
                        "preference_after": preference_after,
                        "learning_boundary": (
                            "Silence is recorded as silence, not a refusal: half a unit of "
                            "evidence against this option, no decline reason, no suppression. "
                            "Safety and consent policy remained unchanged."
                        ),
                    },
                    at=now,
                )
            )
            resolved.append(row.intervention_id)
        if resolved:
            session.flush()
        return resolved

    # ── Batched reads for the decision path ────────────────────────────────────
    #
    # `_evaluate` used to read each of its inputs with its own query per person -- a dozen round
    # trips per person, repeated for every person on the roster and the care-priority board. These
    # loaders read each input set once for any number of runs with an IN query, keep the database's
    # own ordering for every "latest" choice, and leave the rules to the pure `_RunReads` methods.
    # A single-person read is simply a batch of one.

    @staticmethod
    def _hold_people(session: Session, people: Iterable[PersonRow | None]) -> None:
        """Keep person rows loaded alongside a run for the rest of the session.

        The identity map holds its objects weakly, so a person read in the same query as a run
        and not otherwise referenced is gone again by the time `_load_run_reads` asks for it.
        Holding them on `session.info` -- which lives exactly as long as the session -- is what
        lets the decision path reuse them instead of looking each person up again.
        """
        held: dict[str, PersonRow] = session.info.setdefault(_HELD_PEOPLE_KEY, {})
        for person in people:
            if person is not None:
                held[person.person_id] = person

    @staticmethod
    def _load_run_interventions(session: Session, reads: dict[str, _RunReads]) -> None:
        """Each run's interventions with their decision evidence's `observed_at` and their
        follow-through report, in one query. Both joins are at most one row per intervention (the
        evidence by primary key, the report by `uq_follow_through_intervention`), so every
        intervention appears exactly once."""
        if not reads:
            return
        for intervention, observed_at, follow_through in session.execute(
            select(
                InterventionRow,
                DecisionEvidenceRow.observed_at,
                InterventionFollowThroughRow.follow_through,
            )
            .select_from(InterventionRow)
            .outerjoin(
                DecisionEvidenceRow,
                DecisionEvidenceRow.evidence_id == InterventionRow.decision_evidence_id,
            )
            .outerjoin(
                InterventionFollowThroughRow,
                InterventionFollowThroughRow.intervention_id == InterventionRow.intervention_id,
            )
            .where(InterventionRow.run_id.in_(list(reads)))
            .order_by(InterventionRow.created_at, InterventionRow.intervention_id)
        ):
            entry = reads[intervention.run_id]
            entry.interventions.append(intervention)
            if observed_at is not None:
                entry.evidence_observed_at[intervention.intervention_id] = observed_at
            if follow_through is not None:
                entry.follow_through[intervention.intervention_id] = follow_through

    def _load_run_reads(
        self, session: Session, runs: Sequence[ScenarioRunRow]
    ) -> dict[str, _RunReads]:
        """Every input `_evaluate` reads, for every run in `runs`, in a fixed number of queries.

        Keyed by `run_id` and in `runs` order. Read-only; inside a write transaction the queries
        autoflush exactly as the per-run queries they replace did.
        """
        reads: dict[str, _RunReads] = {
            run.run_id: _RunReads(run_id=run.run_id, person_id=run.person_id) for run in runs
        }
        if not reads:
            return reads
        run_ids = list(reads)
        person_ids = sorted({run.person_id for run in runs})

        # People already read with their run (`_active_run`, `_active_runs`) cost nothing.
        held: dict[str, PersonRow] = session.info.get(_HELD_PEOPLE_KEY, {})
        missing = [person_id for person_id in person_ids if person_id not in held]
        loaded: dict[str, PersonRow] = {}
        if missing:
            loaded = {
                row.person_id: row
                for row in session.scalars(
                    select(PersonRow).where(PersonRow.person_id.in_(missing))
                )
            }
        people = {
            person_id: held[person_id] if person_id in held else loaded.get(person_id)
            for person_id in person_ids
        }
        for entry in reads.values():
            entry.person = people.get(entry.person_id)

        for row in session.scalars(
            select(DailyMetricRow)
            .where(DailyMetricRow.run_id.in_(run_ids))
            .order_by(DailyMetricRow.run_id, DailyMetricRow.day)
        ):
            reads[row.run_id].metric_rows.append(row)
        for row in session.scalars(
            select(BaselineConfirmationRow)
            .where(BaselineConfirmationRow.run_id.in_(run_ids))
            .order_by(
                BaselineConfirmationRow.decided_on_day.desc(),
                BaselineConfirmationRow.confirmation_id.desc(),
            )
        ):
            reads[row.run_id].confirmations.append(row)
        for row in session.scalars(
            select(ConsentEvidenceRow)
            .where(ConsentEvidenceRow.run_id.in_(run_ids))
            .order_by(ConsentEvidenceRow.recorded_at.desc(), ConsentEvidenceRow.evidence_id.desc())
        ):
            reads[row.run_id].consents.append(row)
        for row in session.scalars(
            select(ContextQuestionAnswerRow)
            .where(ContextQuestionAnswerRow.run_id.in_(run_ids))
            .order_by(ContextQuestionAnswerRow.answered_at)
        ):
            reads[row.run_id].answers.append(row)
        for row in session.scalars(
            select(ReviewThresholdDecisionRow)
            .where(ReviewThresholdDecisionRow.run_id.in_(run_ids))
            .order_by(ReviewThresholdDecisionRow.decided_at, ReviewThresholdDecisionRow.decision_id)
        ):
            reads[row.run_id].threshold_rows.append(row)
        self._load_run_interventions(session, reads)
        self._load_run_outcomes(session, reads)
        disputes: dict[str, list[DayDisputeRow]] = {}
        for row in session.scalars(
            select(DayDisputeRow)
            .where(DayDisputeRow.person_id.in_(person_ids))
            .order_by(DayDisputeRow.recorded_at.desc(), DayDisputeRow.dispute_id.desc())
        ):
            disputes.setdefault(row.person_id, []).append(row)
        for entry in reads.values():
            entry.disputes = disputes.get(entry.person_id, [])
        return reads

    def _run_reads(self, session: Session, run: ScenarioRunRow) -> _RunReads:
        return self._load_run_reads(session, [run])[run.run_id]

    def _evaluate(
        self, session: Session, run: ScenarioRunRow, reads: _RunReads | None = None
    ) -> tuple[PersonState, PolicyResult, DailyMetricRow]:
        """The person's state and the ladder's decision for their current day.

        `reads` is the run's inputs when a caseload read has already loaded them for every run at
        once (`_load_run_reads`); without it they are loaded here as a batch of one.
        """
        if reads is None:
            reads = self._run_reads(session, run)
        person = reads.person
        if person is None:
            raise KeyError(run.person_id)
        if not reads.metric_rows:
            raise RuntimeError("Active scenario contains no wearable metrics.")
        current_row = reads.metric_rows[-1]
        history = [self._to_metric(row) for row in reads.metric_rows[:-1]]
        current = self._to_metric(current_row)
        context = ContextSignal.model_validate(current_row.context_json)
        assessment_time = datetime.combine(current.day, time(hour=12), tzinfo=UTC)
        confirmed_reference = reads.confirmed_reference()
        baseline, signal = analyse_signal(
            history,
            current,
            context,
            person_id=run.person_id,
            assessed_at=assessment_time,
            confirmed_reference=confirmed_reference,
        )
        # The person's own account of today, folded back into the quality assessment. Re-running
        # `assess_data_quality` with the conflict is deliberate: the assessment stays a single
        # pure function of (reading, self-report) rather than something patched afterwards, and
        # the evidence ID is unchanged because it describes the same day and the same source.
        conflict, conflict_note = reads.self_reported_conflict(current.day)
        if conflict:
            signal = signal.model_copy(
                update={
                    "quality": assess_data_quality(
                        current,
                        person_id=run.person_id,
                        assessed_at=assessment_time,
                        self_reported_conflict=True,
                        self_reported_conflict_note=conflict_note,
                    )
                }
            )
        consent_active = reads.consent_active
        # Resolved once and used twice: the ladder decides with it, and `PersonState` carries it so
        # the web's gate reconstruction can name the gate that fired without string-matching the
        # rationale.
        stated_explanation = reads.stated_explanation(current.day)
        # This person's review threshold, read fresh from the append-only decision rows (ADR 0008).
        # A pure fold, so reading it writes nothing; a revert, an expiry or an approval decided on
        # an earlier day is already folded in, and one decided today takes effect tomorrow.
        threshold_facts = [self._threshold_fact(row) for row in reads.threshold_rows]
        live_threshold = resolve_live_threshold(threshold_facts, current.day)
        shadow_since: date | None = None
        if live_threshold.threshold.looser_than(DEFAULT_REVIEW_THRESHOLD):
            # Only a person whose setting waits longer than the starting setting pays for the
            # per-day series: at most `SHADOW_SCAN_DAYS + 1` `analyse_signal` calls.
            shadow_since = shadow_review_since(
                self._threshold_day_signals(session, run, last_n=SHADOW_SCAN_DAYS + 1, reads=reads),
                threshold_on=lambda day: resolve_live_threshold(threshold_facts, day).threshold,
            )
        policy = decide(
            signal,
            # `decide`'s `consent_active` parameter models `ConsentScope.PROACTIVE_OUTREACH` --
            # "may Care+ contact this person on its own initiative?" -- not the raw stored
            # boolean. Today the two are the same value; routing through `scope_permitted` says
            # so in code rather than only in a docstring. See
            # `docs/adr/0001-consent-scope-model.md`.
            consent_active=scope_permitted(
                ConsentScope.PROACTIVE_OUTREACH, consent_active=consent_active
            ),
            interventions_last_7_days=reads.weekly_contact_count(current.day),
            days_since_last_accepted=reads.days_since_last_accepted(current.day),
            stated_explanation=stated_explanation,
            review_threshold=live_threshold.threshold,
            shadow_review_since=shadow_since,
        )
        # Derived from the signal and the decision, never from `support_priority`.
        #
        # `support_priority` describes how urgent the *action* is, and `suppress` deliberately
        # scores it low -- 15 for the weekly contact cap, 0 for revoked consent. Reading the band
        # off that number meant "we have already contacted them enough this week" rendered
        # identically to "they are fine": a person 39% below their own baseline for two days
        # appeared as `stable` on the queue a coordinator triages by. Not contacting someone and
        # having nothing to be concerned about are different states and must look different.
        #
        # An uninterpretable reading claims nothing either way, so it stays `stable`: the band
        # reports what the signal supports, and a tracker that was not worn supports nothing.
        severity = abs(min(0.0, signal.delta_percent))
        if not signal.quality.safe_to_interpret:
            attention_band = AttentionBand.STABLE
        elif (
            policy.decision == Decision.COORDINATOR_REVIEW
            # The person's own review threshold, or the absolute floor whatever it is. The
            # decision disjunct above also covers the shadow check, which has no signal test.
            or live_threshold.threshold.fires(severity, signal.sustained_low_days)
            or ABSOLUTE_REVIEW_FLOOR.fires(severity, signal.sustained_low_days)
        ):
            attention_band = AttentionBand.REVIEW
        elif severity >= 20 or signal.sustained_low_days >= 2:
            attention_band = AttentionBand.WATCH
        else:
            attention_band = AttentionBand.STABLE
        profile = persona_profile(person.person_id)
        state = PersonState(
            person_id=person.person_id,
            display_name=person.display_name,
            preferred_language=person.preferred_language,
            age=profile.age,
            context_note=profile.context_note,
            consent_active=consent_active,
            current_day=current.day,
            attention_band=attention_band,
            baseline=baseline,
            signal=signal,
            last_decision=policy.decision,
            rationale=policy.rationale,
            # `decide` names the gate on every branch it can return from; `PolicyResult.decided_by`
            # is only optional for the evaluation harness's alternative baselines, which never
            # reach here. A `None` would fail validation loudly rather than invent a gate.
            decided_by_gate=policy.decided_by,
            permitted_actions=[
                Decision.NO_ACTION,
                Decision.GENTLE_NUDGE,
                Decision.PROGRAMME_SUGGESTION,
                Decision.COORDINATOR_REVIEW,
            ]
            if consent_active
            else [Decision.SUPPRESS],
            stated_explanation=(
                None
                if stated_explanation is None
                else StatedContextExplanation(
                    value=stated_explanation.value,
                    label=CONTEXT_ANSWER_LABELS.get(
                        stated_explanation.value, stated_explanation.value
                    ),
                    rationale=stated_explanation.rationale,
                    stated_on=stated_explanation.stated_on,
                    explains_through=stated_explanation.explains_through,
                )
            ),
            review_threshold_notice=senior_notice_for(threshold_facts, current.day),
        )
        # At most one question, ever -- never a queue. `asked_recently` is true for the rest of
        # this run once the person has answered the one question this module ever asks; see
        # `context_question.QUESTION_ID` and `ContextQuestionAnswerRow`'s own docstring for why
        # that is the whole of what needs remembering, rather than the question itself.
        asked_recently = reads.has_context_answer
        pending_question = question_for(state, asked_recently=asked_recently)
        if pending_question is not None:
            state = state.model_copy(update={"pending_question": pending_question})

        # The other question: "is this your new normal?" -- see `baseline_confirmation.py`.
        # `history` excludes today (see `_load_metrics`), matching how `analyse_signal` computed
        # `baseline` above; the streak is about the settled pattern, not today's single reading.
        streak = _clamp_streak_days(history, state.baseline.reference_steps)
        latest_confirmation = reads.latest_confirmation
        pending_baseline_confirmation = baseline_confirmation_question_for(
            state,
            clamp_streak_days=streak,
            last_decision=(
                BaselineConfirmationDecision(latest_confirmation.decision)
                if latest_confirmation is not None
                else None
            ),
            last_decided_on=(
                latest_confirmation.decided_on_day if latest_confirmation is not None else None
            ),
        )
        if pending_baseline_confirmation is not None:
            state = state.model_copy(
                update={"pending_baseline_confirmation": pending_baseline_confirmation}
            )
        return state, policy, current_row

    def _person_state(
        self, session: Session, run: ScenarioRunRow, reads: _RunReads | None = None
    ) -> PersonState:
        state, _, _ = self._evaluate(session, run, reads)
        return state

    def person_state(self, *, person_id: str = DEMO_PERSON_ID) -> PersonState:
        with self.sessions() as session:
            return self._reported_person_state(session, self._active_run(session, person_id))

    def _reported_person_state(self, session: Session, run: ScenarioRunRow) -> PersonState:
        """The state the person's own reads report: `_person_state`, minus one read-time artefact.

        Display only. `advance` and every gate read `_evaluate` directly and never come here.

        The weekly contact count includes the intervention the current day's own decision created,
        so re-running the ladder after the day's second offer reads `SUPPRESS` from `CONTACT_CAP`
        although that offer was sent (`_with_recorded_decision` describes the same artefact on the
        care-priority board). So when the live result comes from `CONTACT_CAP`, and only then, the
        decision recorded for the current day is reported, with its own reasons. Every other gate
        sits above the contact guard and still wins live.

        Two cases keep the live result. A recorded `SUPPRESS`: the cap really held that day, or
        nothing was sent. And a running acceptance cooldown, which `_contact_guard` checks after
        the cap and so cannot name here: the person has since taken a suggestion up, and that hold
        must not be overwritten.

        `pending_question` stays the live one, never re-derived from the reported decision: an
        answer feeds the ladder, so `answer_context_question` accepts only what the live state
        offers. `_evaluate`'s call to `question_for` is the one test both paths read.
        """
        reads = self._run_reads(session, run)
        state = self._person_state(session, run, reads)
        if state.decided_by_gate != PolicyGate.CONTACT_CAP:
            return state
        days_since_accepted = reads.days_since_last_accepted(state.current_day)
        if (
            days_since_accepted is not None
            and days_since_accepted < ACCEPTED_OUTREACH_COOLDOWN_DAYS
        ):
            return state
        day_start = datetime.combine(state.current_day, time.min, tzinfo=UTC)
        recorded = session.scalar(
            select(DecisionEvidenceRow)
            .where(
                DecisionEvidenceRow.run_id == run.run_id,
                DecisionEvidenceRow.observed_at >= day_start,
                DecisionEvidenceRow.observed_at < day_start + timedelta(days=1),
            )
            .order_by(
                DecisionEvidenceRow.recorded_at.desc(), DecisionEvidenceRow.evidence_id.desc()
            )
            .limit(1)
        )
        if recorded is None or recorded.decision == Decision.SUPPRESS.value:
            return state
        return self._with_recorded_decision(state, recorded.decision).model_copy(
            update={
                "rationale": list(recorded.reasons_json),
                # The contact guard only runs inside the severity rung, and a recorded downgrade
                # to `NO_ACTION` keeps that rung, as `_resolve_decision_state` leaves it.
                "decided_by_gate": PolicyGate.SEVERITY_PERSISTENCE,
            }
        )

    def daily_metrics(
        self, *, person_id: str = DEMO_PERSON_ID, days: int = 14
    ) -> list[DailyMetric]:
        limit = max(1, min(days, MAX_DAILY_METRICS_DAYS))
        with self.sessions() as session:
            run = self._active_run(session, person_id)
            rows = list(
                session.scalars(
                    select(DailyMetricRow)
                    .where(DailyMetricRow.run_id == run.run_id)
                    .order_by(DailyMetricRow.day.desc())
                    .limit(limit)
                )
            )
            rows.reverse()
            return [self._to_metric(row) for row in rows]

    @staticmethod
    def _close_open_cases_for_consent(session: Session, run_id: str, now: datetime) -> list[str]:
        """Close every unresolved review case when consent is withdrawn.

        A review case exists to put a derived inference about a person in front of a human. Once
        that person withdraws consent, leaving it on the coordinator's queue keeps the inference
        working -- and the queue is the one surface where a human would act on it. Closing is
        recorded as an ordinary append-only review action, attributed to the system rather than to
        a coordinator, so the audit trail shows why it closed rather than the case simply
        vanishing.
        """
        rows = list(
            session.scalars(
                select(ReviewCaseRow).where(
                    ReviewCaseRow.run_id == run_id,
                    ReviewCaseRow.status != CaseStatus.RESOLVED.value,
                )
            )
        )
        closed: list[str] = []
        for row in rows:
            row.status = CaseStatus.RESOLVED.value
            row.resolution = CaseResolution.CONSENT_WITHDRAWN.value
            session.add(
                CaseReviewRow(
                    review_id=_id("review"),
                    case_id=row.case_id,
                    run_id=row.run_id,
                    status=CaseStatus.RESOLVED.value,
                    reviewer="system",
                    note=(
                        "Closed automatically: the senior withdrew consent, so this case was "
                        "removed from the review queue. No outreach was performed."
                    ),
                    recorded_at=now,
                )
            )
            closed.append(row.case_id)
        return closed

    @staticmethod
    def _close_open_cases_for_recovery(session: Session, run_id: str, now: datetime) -> list[str]:
        """Close every unresolved review case once the person's activity has come back.

        The mirror image of `_close_open_cases_for_consent`, and it exists for the same reason:
        a case is a request for a human decision, and a request nobody needs answered any more
        should not keep sitting on a queue. Leaving them open was how the coordinator surface
        filled with stale concern about people who were fine, which is the fastest way to make a
        review queue stop being read at all.

        Closed only on a genuine recovery -- an interpretable reading, no run of low days, and a
        deterministic NO_ACTION. A tracker that stopped reporting also produces NO_ACTION, and
        closing someone's case because their device went quiet would be exactly backwards.
        """
        rows = list(
            session.scalars(
                select(ReviewCaseRow).where(
                    ReviewCaseRow.run_id == run_id,
                    ReviewCaseRow.status != CaseStatus.RESOLVED.value,
                )
            )
        )
        closed: list[str] = []
        for row in rows:
            row.status = CaseStatus.RESOLVED.value
            row.resolution = CaseResolution.RECOVERED.value
            session.add(
                CaseReviewRow(
                    review_id=_id("review"),
                    case_id=row.case_id,
                    run_id=row.run_id,
                    status=CaseStatus.RESOLVED.value,
                    reviewer="system",
                    note=(
                        "Closed automatically: activity has returned to this person's usual "
                        "range and the deterministic policy returned NO_ACTION, so this case no "
                        "longer needs a human decision."
                    ),
                    recorded_at=now,
                )
            )
            closed.append(row.case_id)
        return closed

    @staticmethod
    def _withdraw_open_interventions(session: Session, run_id: str, now: datetime) -> list[str]:
        rows = list(
            session.scalars(
                select(InterventionRow).where(
                    InterventionRow.run_id == run_id,
                    InterventionRow.status == "proposed",
                )
            )
        )
        for row in rows:
            row.status = "withdrawn_consent_revoked"
            row.evidence_json = {
                **row.evidence_json,
                "withdrawn_at": now.isoformat(),
                "withdrawal_reason": "consent_revoked",
            }
        return [row.intervention_id for row in rows]

    def set_consent(
        self, active: bool, reason: str, actor: str, *, person_id: str = DEMO_PERSON_ID
    ) -> ConsentResponse:
        now = _utcnow()
        with self.sessions.begin() as session:
            run = self._active_run(session, person_id)
            run = self._lock_active_run(session, run.run_id)
            now = self._threshold_clock(session, run.run_id, _utcnow())
            evidence = ConsentEvidenceRow(
                evidence_id=_id("consent"),
                run_id=run.run_id,
                person_id=run.person_id,
                active=active,
                reason=reason,
                actor=actor,
                source="user_demo_input",
                recorded_at=now,
            )
            session.add(evidence)
            withdrawn = (
                [] if active else self._withdraw_open_interventions(session, run.run_id, now)
            )
            # Withdrawing the pending outreach is not enough: an open review case keeps the
            # derived inference in front of a coordinator, which is the surface a human would
            # act on.
            closed_cases = (
                [] if active else self._close_open_cases_for_consent(session, run.run_id, now)
            )
            if not active:
                self._reject_open_threshold_proposals_for_consent(
                    session, run, run.current_day, now
                )
            audit_row = self._audit_row(
                run.run_id,
                "consent_updated",
                actor,
                person_id=run.person_id,
                detail={
                    "consent_evidence_id": evidence.evidence_id,
                    "consent_active": active,
                    # `reason` is free text the senior may type (`ConsentRequest.reason`,
                    # 2-240 chars); it stays on its own row (`ConsentEvidenceRow`), never in the
                    # operator-readable audit, which records only its length.
                    "reason_length": len(reason),
                    "withdrawn_intervention_ids": withdrawn,
                    "closed_case_ids": closed_cases,
                },
                at=now,
            )
            session.add(audit_row)
            session.flush()
            audit = self._to_audit(audit_row)
        return ConsentResponse(
            consent_active=active,
            consent_evidence_id=evidence.evidence_id,
            withdrawn_intervention_ids=withdrawn,
            audit_event=audit,
        )

    def _resolve_decision_state(
        self, session: Session, run: ScenarioRunRow
    ) -> tuple[PersonState, DailyMetricRow]:
        """`_evaluate` plus the two decision-class downgrades `advance()` always applies:
        a programme suggestion with no fresh programme evidence, or a decision every permitted
        candidate of which this person has muted, both become an audited `NO_ACTION`.

        Pulled out so both halves of `advance()`'s planner split run the identical pipeline: the
        read phase, to brief the planner, and the write phase, to re-derive the truth right
        before persisting. The only thing that can differ between two calls is what the database
        now contains -- never the logic applied to it.
        """
        state, _, current_row = self._evaluate(session, run)
        if state.last_decision == Decision.PROGRAMME_SUGGESTION and not self._programme_models(
            session,
            current_only=True,
            as_of=datetime.combine(state.current_day, time(hour=12), tzinfo=UTC),
        ):
            state = state.model_copy(
                update={
                    "last_decision": Decision.NO_ACTION,
                    "rationale": [
                        *state.rationale,
                        "No programme evidence passed the freshness gate; NO_ACTION recorded.",
                    ],
                }
            )
        # Everything of this kind muted by the person is still a decision, and it is NO_ACTION --
        # recorded, rationalised and audited like any other. The alternative failure mode is
        # worse than it looks: without this, the planner would be handed an empty candidate list,
        # no intervention would be created, and the run would report a GENTLE_NUDGE that was
        # never sent to anyone.
        if state.last_decision in {Decision.GENTLE_NUDGE, Decision.PROGRAMME_SUGGESTION}:
            as_of = datetime.combine(state.current_day, time(hour=12), tzinfo=UTC)
            available = self._intervention_candidates(session, state.last_decision, as_of)
            permitted = self._intervention_candidates(
                session, state.last_decision, as_of, person_id=run.person_id
            )
            if available and not permitted:
                state = state.model_copy(
                    update={
                        "last_decision": Decision.NO_ACTION,
                        "rationale": [
                            *state.rationale,
                            "Every suggestion of this kind has been muted by this person; "
                            "NO_ACTION was recorded rather than sending one anyway.",
                        ],
                    }
                )
        return state, current_row

    def advance(
        self,
        event_name: str,
        event_id: str | None = None,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> AdvanceResponse:
        allowed = {
            "activity_declines",
            "rain_explains_decline",
            "rain_clears_activity_low",
            "recovery",
            "low_wear",
            "consent_revoked",
            "public_holiday",
            "programme_becomes_full",
            "weather_turns",
        }
        if event_name not in allowed:
            raise ValueError(f"Unsupported event '{event_name}'. Choose one of {sorted(allowed)}")

        # Live weather/holiday context is fetched before the locked phase, never while holding the
        # run lock: a provider call can take seconds. The day it was fetched for is re-checked
        # under the lock; if another advance moved the day meanwhile, this one fails as a
        # conflict (the same outcome two advances racing for one day already have) rather than
        # attaching context fetched for the wrong day or fetching again under the lock.
        prefetched_day: date | None = None
        prefetched: ExternalContext | None = None
        if self._context_provider is not None:
            with self.sessions() as session:
                read_run = self._active_run(session, person_id)
                _, read_current, _, _ = self._load_metrics(session, read_run.run_id)
            prefetched_day = read_current.day + timedelta(days=1)
            prefetched = self._context_provider.fetch(
                datetime.combine(prefetched_day, time(hour=12), tzinfo=UTC)
            )
        with self.sessions.begin() as session:
            run = self._active_run(session, person_id)
            # The same lock every review-setting writer takes, and first: this phase updates
            # `current_day` and, for `consent_revoked`, inserts consent and threshold rows, so it
            # must not hold KEY SHARE locks from those inserts while waiting for the row lock.
            run = self._lock_active_run(session, run.run_id)
            now = self._threshold_clock(session, run.run_id, _utcnow())
            if event_id:
                try:
                    replay = session.scalar(
                        select(SimulationEventRow).where(
                            SimulationEventRow.run_id == run.run_id,
                            SimulationEventRow.client_event_id == event_id,
                        )
                    )
                except json.JSONDecodeError as exc:
                    raise undecodable_stored_json("advance_replay", exc) from exc
                if replay:
                    if replay.event_name != event_name:
                        raise ValueError(
                            "The event_id was already used for a different simulation event."
                        )
                    return load_stored_advance(replay.response_json, source="advance_replay")
            history, current, _, _ = self._load_metrics(session, run.run_id)
            next_day = current.day + timedelta(days=1)
            if prefetched_day is not None and prefetched_day != next_day:
                raise StaleRunConflict(
                    "This simulated day was already advanced by a concurrent request. Re-read the "
                    "person's state, or pass an event_id to make the call idempotent."
                )
            context = ContextSignal()
            if event_name == "activity_declines":
                previous_low_days = sum(
                    metric.steps < 4200 and metric.wear_hours >= 8
                    for metric in [*history, current][-2:]
                )
                next_metric = _activity_decline_metric(next_day, previous_low_days)
            elif event_name == "rain_explains_decline":
                next_metric = DailyMetric(
                    day=next_day,
                    steps=3300,
                    active_minutes=25,
                    sleep_hours=7.0,
                    wear_hours=13.1,
                )
                context = ContextSignal(rainy=True, note="Heavy afternoon rain fixture")
            elif event_name == "rain_clears_activity_low":
                next_metric = DailyMetric(
                    day=next_day,
                    steps=3200,
                    active_minutes=24,
                    sleep_hours=6.8,
                    wear_hours=13.0,
                )
                context = ContextSignal(
                    rainy=False,
                    note="Skies have cleared, but activity has not recovered",
                )
            elif event_name == "public_holiday":
                next_metric = DailyMetric(
                    day=next_day,
                    steps=4300,
                    active_minutes=32,
                    sleep_hours=7.0,
                    wear_hours=13.2,
                )
                context = ContextSignal(
                    holiday=True,
                    note=(
                        "Public holiday fixture; recorded as context only -- the policy does "
                        "not treat a holiday as an automatic excuse for a decline."
                    ),
                )
            elif event_name == "recovery":
                next_metric = DailyMetric(
                    day=next_day,
                    steps=6180,
                    active_minutes=47,
                    sleep_hours=7.3,
                    wear_hours=13.8,
                )
            elif event_name == "low_wear":
                next_metric = DailyMetric(
                    day=next_day,
                    steps=900,
                    active_minutes=7,
                    sleep_hours=None,
                    wear_hours=2.1,
                )
            elif event_name == "programme_becomes_full":
                next_metric = DailyMetric(
                    day=next_day,
                    steps=4200,
                    active_minutes=32,
                    sleep_hours=7.0,
                    wear_hours=13.0,
                )
                context = ContextSignal(note="A booked session has reached capacity.")
            elif event_name == "weather_turns":
                next_metric = DailyMetric(
                    day=next_day,
                    steps=3300,
                    active_minutes=25,
                    sleep_hours=7.0,
                    wear_hours=13.1,
                )
                context = ContextSignal(
                    rainy=True,
                    note="Forecast has turned; outdoor sessions may no longer be suitable.",
                )
            else:
                next_metric = DailyMetric(
                    day=next_day,
                    steps=0,
                    active_minutes=0,
                    sleep_hours=None,
                    wear_hours=0,
                )
                session.add(
                    ConsentEvidenceRow(
                        evidence_id=_id("consent"),
                        run_id=run.run_id,
                        person_id=run.person_id,
                        active=False,
                        reason="Consent revoked by deterministic demo event.",
                        actor="senior",
                        source="synthetic_fixture",
                        recorded_at=now,
                    )
                )
                self._withdraw_open_interventions(session, run.run_id, now)
                self._close_open_cases_for_consent(session, run.run_id, now)
                # A review-setting round in flight is closed too: nothing about this person may be
                # approved once they have withdrawn consent (ADR 0008).
                self._reject_open_threshold_proposals_for_consent(session, run, next_day, now)

            if event_name != "consent_revoked" and self._authored_metric is not None:
                authored = self._authored_metric(run.person_id, next_day)
                if authored is not None:
                    if authored.day != next_day:
                        raise ValueError(
                            f"An authored metric for {next_day.isoformat()} carries the day "
                            f"{authored.day.isoformat()}."
                        )
                    next_metric = authored

            # `programme_becomes_full` and `weather_turns` exist so the world the person already
            # planned around can change out from under them -- see `replan_notices`. Each is
            # deterministic: it always affects the *soonest* upcoming planned entry it applies to
            # (any for a full session, outdoor-only for weather), never a random or "the best"
            # one, and it never deletes or reassigns the person's own plan.
            #
            # Two rules this block is careful about, both of them bugs it used to have:
            #
            #   * the plan it picks is the *active run's* (`run_id`), not merely this person's.
            #     Read person-scoped, a dead run's plan -- which a reset leaves inside the live
            #     week again -- decided which listing the live story marked FULL, so an event the
            #     senior triggered changed a listing they had nothing planned for and left their
            #     own plan alone (the same class of defect as audit I finding 1).
            #   * `weather_turns` no longer touches `availability`. Flipping a listing to FULL to
            #     represent bad weather fabricates a catalogue fact to stand in for a context one,
            #     and `_reason`'s precedence then told the senior their outing was "fully booked"
            #     when the truth was that the forecast turned (audit J finding F-J-A). The
            #     forecast is already carried by `context.rainy` below; a `weather` replan offer
            #     is what the person is told about, and the listing is left exactly as it is.
            replan_affected_activity_id: str | None = None
            if event_name == "programme_becomes_full":
                upcoming = session.scalar(
                    select(WeekPlanEntryRow)
                    .where(
                        WeekPlanEntryRow.run_id == run.run_id,
                        WeekPlanEntryRow.person_id == run.person_id,
                        WeekPlanEntryRow.day >= next_day,
                        WeekPlanEntryRow.replaced_reason.is_(None),
                    )
                    .order_by(WeekPlanEntryRow.day, WeekPlanEntryRow.plan_id)
                    .limit(1)
                )
                if upcoming is not None:
                    activity_row = session.get(ActivityCandidateRow, upcoming.activity_id)
                    if activity_row is not None:
                        # Availability genuinely is a catalogue fact, and this event is the
                        # catalogue changing: this one stays.
                        activity_row.availability = ActivityAvailability.FULL.value
                        replan_affected_activity_id = activity_row.activity_id
            elif event_name == "weather_turns":
                # Only the day the forecast is actually about. "Today's forecast has turned"
                # cannot honestly speak for an outing three days out, and the offer written below
                # follows the same rule (`replanning.notices_for`: rain matters for today's plan).
                upcoming_rows = session.scalars(
                    select(WeekPlanEntryRow)
                    .where(
                        WeekPlanEntryRow.run_id == run.run_id,
                        WeekPlanEntryRow.person_id == run.person_id,
                        WeekPlanEntryRow.day == next_day,
                        WeekPlanEntryRow.replaced_reason.is_(None),
                    )
                    .order_by(WeekPlanEntryRow.day, WeekPlanEntryRow.plan_id)
                )
                for entry in upcoming_rows:
                    activity_row = session.get(ActivityCandidateRow, entry.activity_id)
                    if (
                        activity_row is not None
                        and activity_row.indoor_outdoor == IndoorOutdoor.OUTDOOR.value
                    ):
                        replan_affected_activity_id = activity_row.activity_id
                        break

            external_evidence: list[ContextEvidence] = []
            expired_context_evidence: list[dict[str, str]] = []
            if self._context_provider is not None:
                # Supplements the scripted `context` above; it can only OR in additional true
                # signals (rain, holiday), never override or race what the simulator already
                # decided for this event.
                evaluation_instant = datetime.combine(next_day, time(hour=12), tzinfo=UTC)
                if (
                    prefetched is None
                ):  # pragma: no cover - fetched above whenever a provider is set
                    raise RuntimeError("External context was not fetched before the locked phase.")
                external = prefetched
                external_evidence = external.evidence
                # Freshness gate, mirroring the programme freshness check below: a
                # `ContextEvidence` whose `expires_at` has already passed by the time this event
                # is evaluated must not contribute a true signal -- it is stale, not "checked and
                # clear". Dropped evidence is still recorded (never silently discarded).
                rain_fresh = True
                holiday_fresh = True
                # Live weather says what the sky is doing now, so it may only speak for the day
                # being evaluated when that day is today in Singapore, and only while it is still
                # current now. A simulated day keeps its simulated weather; nothing is invented
                # for it and nothing real is stamped onto it.
                real_now = _utcnow()
                for evidence in external.evidence:
                    if evidence.source == "nea_weather_live":
                        if next_day != local_date(real_now):
                            rain_fresh = False
                            expired_context_evidence.append(
                                {
                                    "evidence_id": evidence.evidence_id,
                                    "source": evidence.source,
                                    "expires_at": evidence.expires_at.isoformat(),
                                    "reason": "not_about_this_day",
                                }
                            )
                            continue
                        if evidence.expires_at >= real_now:
                            continue
                    elif evidence.expires_at >= evaluation_instant:
                        continue
                    expired_context_evidence.append(
                        {
                            "evidence_id": evidence.evidence_id,
                            "source": evidence.source,
                            "expires_at": evidence.expires_at.isoformat(),
                        }
                    )
                    if evidence.source == "nea_weather_live":
                        rain_fresh = False
                    elif evidence.source == "nager_date_public_holidays":
                        holiday_fresh = False
                # Which weather this day's decisions use, said plainly: the scripted rain when the
                # simulation set some, else the live reading when it speaks for this day (or that
                # the live lookup had nothing current), else the simulation's dry day.
                live_today = rain_fresh and next_day == local_date(real_now)
                weather_source: Literal["simulated", "live", "unavailable"]
                if context.rainy or next_day != local_date(real_now):
                    weather_source = "simulated"
                elif not rain_fresh:
                    weather_source = "unavailable"  # today's reading went stale before use
                else:
                    weather_source = external.signal.weather_source
                context = ContextSignal(
                    rainy=context.rainy or (external.signal.rainy and rain_fresh),
                    holiday=context.holiday or (external.signal.holiday and holiday_fresh),
                    air_quality=context.air_quality,
                    note=context.note or (external.signal.note if live_today else None),
                    weather_source=weather_source,
                    weather_valid_until=(
                        external.signal.weather_valid_until if weather_source == "live" else None
                    ),
                )

            run.current_day = next_day
            # The simulated day just moved, so listings may now be in the past. Refresh
            # here rather than at read time: a search is a read, and silently rewriting
            # catalogue rows inside one would make the same query return different data
            # depending on who asked first.
            self._refresh_stale_activities(session, next_day)
            # A plan the world changed under is now an offer with a row of its own, written here
            # -- in the same transaction as the change that invalidated it -- rather than a notice
            # recomputed on every read. That is what makes "no thanks" stick, keeps the reason
            # code stable between two reads, and puts `replan_offered` in the audit trail at the
            # moment it happened. See `_record_replan_offers`.
            self._expire_open_replan_offers(session, run, next_day, now)
            self._record_replan_offers(session, run, next_day, context, now)
            # The response clock: an offer still open past its window is closed as silence
            # before today is decided, so the decision, the planner's brief and the audit trail
            # all see the same history. See `RESPONSE_WINDOW_DAYS`.
            unanswered_outreach_resolved = self._resolve_unanswered_outreach(
                session, run, next_day, now
            )
            session.add(self._metric_row(run.run_id, run.person_id, next_metric, context, now))
            session.flush()
            run_id = run.run_id
            # Read phase ends here. Everything above is a domain fact independent of any model;
            # everything below the planner call is too (the decision, a review case, an audit
            # event). What is briefed here, while the session is open, is only what the outreach
            # planner needs -- and that planner may call Bedrock or Anthropic over the network.
            # That call must never happen inside a write transaction: on the measured
            # Supabase/Bedrock configuration it can run for seconds, and this transaction holds
            # row locks on `scenario_runs`, `daily_metrics` and related tables for as long as it
            # stays open. The session this `with` block owns is released (committed and closed)
            # when this block ends, before the planner is ever consulted -- see
            # `_prepare_outreach_plan` and `_plan_outreach_safely`.
            planned_state, _ = self._resolve_decision_state(session, run)
            plan = self._prepare_outreach_plan(session, run, planned_state)

        # No database session is open below this line, and none is opened again until the write
        # phase's own `with self.sessions.begin()`. `plan` is `None` whenever the decision just
        # read does not call for outreach, in which case the planner is never consulted at all --
        # unchanged from before this split.
        agent_run: AgentRun | None = None
        if plan is not None:
            agent_run = self._plan_outreach_safely(plan)

        with self.sessions.begin() as session:
            # Re-fetched by primary key rather than `_active_run(session, person_id)`: this write
            # phase belongs to the specific run the event above was applied to, even if a demo
            # reset has since made a different run active for this person. Re-deriving the
            # decision from scratch here, rather than reusing `planned_state`, is what lets this
            # phase notice that consent was withdrawn, the weekly contact cap was newly reached,
            # this person's preferences changed, or the run itself was reset in the window since
            # the planner was briefed -- and discard a stale plan rather than act on it. See
            # `_finalize_intervention` for exactly how that comparison is made. A run a demo reset
            # deactivated during the planner window is refused outright (409): phase 1's day stays
            # on that dead run without a decision, and the new run's days are unaffected.
            # Locked first, before the decision evidence, a case or any review-setting row is
            # inserted, and before threshold facts are read (see `_lock_threshold_run`).
            run = self._lock_active_run(session, run_id)
            # Stamped after the lock and past every stored review-setting decision, so a shadow
            # clear written below folds after an approval committed during the planner window.
            now = self._threshold_clock(session, run.run_id, _utcnow())
            state, current_row = self._resolve_decision_state(session, run)
            # A case asks a human to decide something. Once the person's activity is back and the
            # policy has returned to NO_ACTION, there is nothing left to decide.
            recovery_closed_cases: list[str] = []
            if (
                state.last_decision == Decision.NO_ACTION
                and state.signal.quality.safe_to_interpret
                and state.signal.sustained_low_days == 0
            ):
                recovery_closed_cases = self._close_open_cases_for_recovery(
                    session, run.run_id, now
                )
            decision_row = DecisionEvidenceRow(
                evidence_id=_id("decision"),
                run_id=run.run_id,
                person_id=run.person_id,
                observed_at=current_row.observed_at,
                recorded_at=now,
                source=current_row.source,
                fixture_classification=current_row.fixture_classification,
                confidence=state.signal.confidence,
                policy_version=POLICY_VERSION,
                decision=state.last_decision.value,
                reasons_json=state.rationale,
                input_event=event_name,
                quality_evidence_id=state.signal.quality.evidence_id,
            )
            session.add(decision_row)
            session.flush()
            intervention = self._finalize_intervention(
                session, run, state, decision_row, plan, agent_run
            )
            review_case = self._create_case(session, run, state, decision_row)
            # Written here and only here: a shadow-check revert and the audit row for a lapsed
            # looser setting. Both take effect from facts the evaluation above already folded in,
            # so the day just decided is never re-decided (ADR 0007 §5).
            review_threshold_decision_ids = self._apply_review_threshold_daily_checks(
                session, run, state, now, created_case=review_case
            )
            # Every revert owed a write-up: today's, and any earlier one whose follow-up never ran.
            session.flush()
            write_up_follow_ups = [
                _ThresholdFollowUp("write_up", run.run_id, decision_id=decision_id)
                for decision_id in self._owed_write_ups(session, run.run_id)
            ]
            audit_row = self._audit_row(
                run.run_id,
                "decision_recorded",
                "policy-engine",
                person_id=run.person_id,
                decision=state.last_decision,
                detail={
                    "input_event": event_name,
                    "evidence_id": decision_row.evidence_id,
                    "wearable_evidence_id": current_row.evidence_id,
                    "source": current_row.source,
                    "fixture_classification": current_row.fixture_classification,
                    "observed_at": _as_utc(current_row.observed_at).isoformat(),
                    "confidence": state.signal.confidence,
                    "ingestion_confidence": current_row.ingestion_confidence,
                    "policy_version": POLICY_VERSION,
                    "rationale": state.rationale,
                    "quality_evidence_id": state.signal.quality.evidence_id,
                    "external_context_evidence": [
                        evidence.model_dump(mode="json") for evidence in external_evidence
                    ],
                    "expired_context_evidence": expired_context_evidence,
                    "closed_case_ids": recovery_closed_cases,
                    "replan_affected_activity_id": replan_affected_activity_id,
                    "unanswered_outreach_resolved": unanswered_outreach_resolved,
                    "review_threshold_decision_ids": review_threshold_decision_ids,
                },
                at=now,
            )
            session.add(audit_row)
            session.flush()
            audit = self._to_audit(audit_row)
            loop_trace = self._build_loop_trace(
                state,
                current_row,
                decision_row,
                intervention,
                review_case,
                audit,
            )
            response = AdvanceResponse(
                state=state,
                created_intervention=intervention,
                created_case=review_case,
                audit_event=audit,
                loop_trace=loop_trace,
            )
            if event_id:
                session.add(
                    SimulationEventRow(
                        simulation_event_id=_id("sim_event"),
                        client_event_id=event_id,
                        run_id=run.run_id,
                        event_name=event_name,
                        response_json=response.model_dump(mode="json"),
                        recorded_at=now,
                    )
                )
        # After the day's commit, with no session open: a write-up of each revert the day wrote of
        # an agent or fixed-rule approval. It never changes the response; failures are audited.
        self._run_threshold_follow_ups(write_up_follow_ups)
        return response

    @staticmethod
    def _build_loop_trace(
        state: PersonState,
        metric: DailyMetricRow,
        decision: DecisionEvidenceRow,
        intervention: Intervention | None,
        review_case: ReviewCase | None,
        audit: AuditEvent,
    ) -> list[DecisionTraceStep]:
        validation_status = (
            TraceStatus.COMPLETED if state.signal.quality.safe_to_interpret else TraceStatus.BLOCKED
        )
        policy_status = (
            TraceStatus.BLOCKED
            if state.last_decision == Decision.SUPPRESS
            else TraceStatus.COMPLETED
        )
        if intervention:
            action_detail = f"Created permitted action: {intervention.title}."
            # Show how the candidate and wording were chosen inside the class the policy had
            # already permitted -- the planner's contribution, or the reason it was not used.
            agent_evidence = intervention.evidence.get("agent") or {}
            if agent_detail := agent_evidence.get("trace_detail"):
                action_detail = f"{action_detail} {agent_detail}"
            action_evidence = intervention.intervention_id
            response_detail = "Waiting for the senior to accept, decline or give no response."
            if intervention.awaiting_reply_until is not None:
                # The wait has an end, and the trace says when: silence past the window is
                # recorded as `no_response` by the response clock, not left pending forever.
                response_detail = (
                    f"{response_detail} If nothing is recorded by "
                    f"{intervention.awaiting_reply_until.strftime('%a %d %b')}, it is recorded "
                    "as silence, not a refusal."
                )
            outcome_status = TraceStatus.PENDING
            learning_status = TraceStatus.PENDING
        elif review_case:
            action_detail = "Opened a human-review case; no outreach was sent."
            action_evidence = review_case.case_id
            response_detail = "Waiting for an explicit coordinator review."
            outcome_status = TraceStatus.PENDING
            learning_status = TraceStatus.NOT_APPLICABLE
        else:
            action_detail = f"Recorded {state.last_decision.value.upper()} as the action."
            action_evidence = decision.evidence_id
            response_detail = "No response is requested because no outreach was created."
            outcome_status = TraceStatus.NOT_APPLICABLE
            learning_status = TraceStatus.NOT_APPLICABLE
        # Only outreach that was actually sent can be followed through on. A review case is a
        # request for a human decision, not something the person was asked to do.
        follow_through_status = TraceStatus.PENDING if intervention else TraceStatus.NOT_APPLICABLE
        return [
            DecisionTraceStep(
                order=1,
                stage="observation",
                status=TraceStatus.COMPLETED,
                title="Observation received",
                detail=(
                    f"{metric.steps:,} steps and {metric.wear_hours:.1f} wear-hours "
                    f"from {metric.fixture_classification}; ingestion confidence "
                    f"{metric.ingestion_confidence:.0%}."
                ),
                evidence_id=metric.evidence_id,
            ),
            DecisionTraceStep(
                order=2,
                stage="validation",
                status=validation_status,
                title="Data quality checked",
                detail=" ".join(state.signal.quality.reasons),
                evidence_id=state.signal.quality.evidence_id,
            ),
            DecisionTraceStep(
                order=3,
                stage="reasoning",
                status=TraceStatus.COMPLETED,
                title="Personal baseline compared",
                detail=(
                    f"Current activity is {state.signal.delta_percent:.1f}% from the personal "
                    f"baseline across {state.signal.sustained_low_days} low "
                    f"{'day' if state.signal.sustained_low_days == 1 else 'days'}."
                ),
                evidence_id=decision.evidence_id,
            ),
            DecisionTraceStep(
                order=4,
                stage="policy_gate",
                status=policy_status,
                title=f"Deterministic policy: {state.last_decision.value}",
                detail=" ".join(state.rationale),
                evidence_id=decision.evidence_id,
            ),
            DecisionTraceStep(
                order=5,
                stage="action",
                status=(TraceStatus.PENDING if review_case else TraceStatus.COMPLETED),
                title="Bounded action selected",
                detail=action_detail,
                evidence_id=action_evidence,
            ),
            DecisionTraceStep(
                order=6,
                stage="response",
                status=(
                    TraceStatus.PENDING
                    if intervention or review_case
                    else TraceStatus.NOT_APPLICABLE
                ),
                title="Response checkpoint",
                detail=response_detail,
                evidence_id=None,
            ),
            DecisionTraceStep(
                order=7,
                stage="outcome",
                status=outcome_status,
                title="Outcome evidence",
                detail=(
                    "Any response will be appended as separate outcome evidence."
                    if outcome_status == TraceStatus.PENDING
                    else "No outcome is inferred for a no-action decision."
                ),
                evidence_id=None,
            ),
            DecisionTraceStep(
                order=8,
                stage="follow_through",
                status=follow_through_status,
                title="Follow through",
                detail=(
                    "If the suggestion is accepted, the person is asked later what actually "
                    "happened. Acceptance on its own is not recorded as success."
                    if follow_through_status == TraceStatus.PENDING
                    else "No follow-through is requested because no outreach was sent."
                ),
                evidence_id=None,
            ),
            DecisionTraceStep(
                order=9,
                stage="learning",
                status=learning_status,
                title="Transparent preference update",
                detail=(
                    "The outcome may rank future policy-permitted candidates only."
                    if learning_status == TraceStatus.PENDING
                    else "No preference update is applicable."
                ),
                evidence_id=None,
            ),
            DecisionTraceStep(
                order=10,
                stage="audit",
                status=TraceStatus.COMPLETED,
                title="Audit evidence appended",
                detail=f"Policy {POLICY_VERSION}; decision and reasons preserved.",
                evidence_id=audit.event_id,
            ),
        ]

    @staticmethod
    def _latest_outcome_ids_subquery():  # type: ignore[no-untyped-def]
        """The `outcome_id` of the single most recent `InterventionOutcomeRow` per intervention.

        `intervention_outcomes` is append-only: `record_outcome`'s reason-amendment path adds a
        second row for the same intervention and outcome rather than updating the first, because
        a migration-created trigger rejects UPDATE/DELETE on this table outright. Every reader
        that folds outcomes into a count or into preference learning has to resolve to this one
        row per intervention -- joining on `intervention_id` alone would visit an amended
        decline's evidence twice and either double-count it or apply its learning weight twice,
        which is exactly the property the amendment path exists to avoid.
        """
        ranked = select(
            InterventionOutcomeRow.outcome_id,
            func.row_number()
            .over(
                partition_by=InterventionOutcomeRow.intervention_id,
                order_by=(
                    InterventionOutcomeRow.recorded_at.desc(),
                    InterventionOutcomeRow.outcome_id.desc(),
                ),
            )
            .label("rn"),
        ).subquery()
        return select(ranked.c.outcome_id).where(ranked.c.rn == 1)

    def _preference_learners(
        self, session: Session, person_id: str
    ) -> tuple[PreferenceLearner, PreferenceLearner]:
        return self._learners_from(self._preference_rows(session, person_id))

    def _preference_rows(
        self, session: Session, person_id: str
    ) -> list[tuple[InterventionRow, str, str | None, str | None, str | None]]:
        """`(intervention, latest outcome, follow-through, decline reason, enjoyment)` for every
        intervention of this person that has an outcome -- the rows both posteriors are rebuilt
        from, read once so a caller that also wants `_candidate_outcome_counts` does not read them
        twice."""
        # Outer-joined, not inner-joined, so an intervention with an outcome and no follow-through
        # still contributes. The join is what makes a rebuild from scratch reproduce the numbers
        # that `record_follow_through` produced incrementally: the learner applies the
        # follow-through weight INSTEAD OF the acceptance weight, so replaying the outcomes
        # without the follow-throughs would leave every acted-on suggestion scored as a bare tap.
        rows = session.execute(
            select(
                InterventionRow,
                InterventionOutcomeRow.outcome,
                InterventionFollowThroughRow.follow_through,
                # The one-tap decline reason, stored on the outcome row since declines first
                # carried one and, until now, read only by the deterministic suppression guard.
                # Without it every decline reached `PreferenceLearner.record` as a bare
                # `declined`, so "just a bad day" and "the tracker is wrong, I am already getting
                # about" ranked a candidate down exactly as hard as "it is not for me" -- the
                # suppression ladder was reason-aware and the ordering underneath it was not.
                InterventionOutcomeRow.reason,
            )
            # Explicit, rather than left implicit as it was before `_latest_outcome_ids_subquery`
            # existed: with a plain `==` onclause the join's left side was unambiguous, but the
            # `.in_(subquery)` condition also mentions `InterventionOutcomeRow` -- the same table
            # `InterventionOutcomeRow.outcome` above is already selected from -- which is enough
            # for SQLAlchemy to see two candidate lefts and refuse to guess.
            .select_from(InterventionRow)
            .join(
                InterventionOutcomeRow,
                and_(
                    InterventionOutcomeRow.intervention_id == InterventionRow.intervention_id,
                    InterventionOutcomeRow.outcome_id.in_(self._latest_outcome_ids_subquery()),
                ),
            )
            .outerjoin(
                InterventionFollowThroughRow,
                InterventionFollowThroughRow.intervention_id == InterventionRow.intervention_id,
            )
            # And the enjoyment report -- folded into a second, EXPERIENCE posterior alongside
            # the ENGAGEMENT one this join already builds, never in place of it: attending is not
            # the same as it having been any good, and `PreferenceLearner.expected_value` learns
            # both. See `learning.PreferenceLearner`.
            .outerjoin(
                InterventionEnjoymentRow,
                InterventionEnjoymentRow.intervention_id == InterventionRow.intervention_id,
            )
            .add_columns(InterventionEnjoymentRow.enjoyment)
            .where(InterventionRow.person_id == person_id)
        )
        return [
            (intervention, outcome, follow_through, reason, enjoyment)
            for intervention, outcome, follow_through, reason, enjoyment in rows
        ]

    @staticmethod
    def _learners_from(
        rows: Iterable[tuple[InterventionRow, str, str | None, str | None, str | None]],
    ) -> tuple[PreferenceLearner, PreferenceLearner]:
        decision_learner = PreferenceLearner()
        candidate_learner = PreferenceLearner()
        for intervention, outcome, follow_through, reason, enjoyment in rows:
            decision_learner.record(
                intervention.decision, outcome, follow_through, enjoyment, reason
            )
            candidate_key = str(
                intervention.evidence_json.get("candidate_key", intervention.decision)
            )
            candidate_learner.record(candidate_key, outcome, follow_through, enjoyment, reason)
        return decision_learner, candidate_learner

    def _candidate_outcome_counts(
        self, session: Session, person_id: str
    ) -> dict[str, tuple[int, int]]:
        """Per-candidate `(accepted-like outcomes, all recorded outcomes)` counts, from the same
        intervention/outcome join `_preference_learners` scores from.

        "Offers" here means "outcomes that fed the score", not "interventions ever created" --
        a still-pending intervention (no outcome recorded yet) has not contributed to the score
        and is not counted, which keeps this the exact sample size behind
        `candidate_preference_scores`, not an approximation of it.
        """
        rows = session.execute(
            select(InterventionRow, InterventionOutcomeRow.outcome)
            .select_from(InterventionRow)
            .join(
                InterventionOutcomeRow,
                and_(
                    InterventionOutcomeRow.intervention_id == InterventionRow.intervention_id,
                    InterventionOutcomeRow.outcome_id.in_(self._latest_outcome_ids_subquery()),
                ),
            )
            .where(InterventionRow.person_id == person_id)
        )
        return self._outcome_counts_from((intervention, outcome) for intervention, outcome in rows)

    @staticmethod
    def _outcome_counts_from(
        rows: Iterable[tuple[InterventionRow, str]],
    ) -> dict[str, tuple[int, int]]:
        """`_candidate_outcome_counts` over `(intervention, latest outcome)` pairs already read --
        `_preference_rows` holds exactly those pairs, one per intervention with an outcome."""
        accepted_counts: dict[str, int] = {}
        offer_counts: dict[str, int] = {}
        for intervention, outcome in rows:
            candidate_key = str(
                intervention.evidence_json.get("candidate_key", intervention.decision)
            )
            offer_counts[candidate_key] = offer_counts.get(candidate_key, 0) + 1
            if outcome in {"accepted", "activity_recovered"}:
                accepted_counts[candidate_key] = accepted_counts.get(candidate_key, 0) + 1
        return {key: (accepted_counts.get(key, 0), offer_counts[key]) for key in offer_counts}

    @staticmethod
    def _suppressed_candidate_keys(session: Session, person_id: str) -> set[str]:
        """Candidate keys this person has muted.

        Deterministic and entirely outside the Beta-Bernoulli learner. Suppression REMOVES
        options from the permitted set; the learner only ever reorders what policy already
        allowed. Keeping them apart is what preserves that invariant -- narrowing the permitted
        set is a safety-preserving direction, and a learned score must never be able to widen it.
        """
        return set(
            session.scalars(
                select(CandidatePreferenceRow.candidate_key).where(
                    CandidatePreferenceRow.person_id == person_id,
                    CandidatePreferenceRow.suppressed.is_(True),
                )
            )
        )

    def _candidate_activity_counts_for(
        self, session: Session, person_ids: Sequence[str]
    ) -> dict[str, dict[str, dict[str, int]]]:
        """`_candidate_activity_counts` for every person in `person_ids`, in one query."""
        counts_by_person: dict[str, dict[str, dict[str, int]]] = {
            person_id: {} for person_id in person_ids
        }
        if not person_ids:
            return counts_by_person

        def bucket(person_id: str, key: str) -> dict[str, int]:
            return counts_by_person[person_id].setdefault(
                key,
                {"offered": 0, "accepted": 0, "declined": 0, "followed": 0, "completed": 0},
            )

        rows = session.execute(
            select(
                InterventionRow,
                InterventionOutcomeRow.outcome,
                InterventionFollowThroughRow.follow_through,
            )
            .select_from(InterventionRow)
            .outerjoin(
                InterventionOutcomeRow,
                and_(
                    InterventionOutcomeRow.intervention_id == InterventionRow.intervention_id,
                    InterventionOutcomeRow.outcome_id.in_(self._latest_outcome_ids_subquery()),
                ),
            )
            .outerjoin(
                InterventionFollowThroughRow,
                InterventionFollowThroughRow.intervention_id == InterventionRow.intervention_id,
            )
            .where(InterventionRow.person_id.in_(person_ids))
        )
        for intervention, outcome, follow_through in rows:
            key = str(intervention.evidence_json.get("candidate_key", intervention.decision))
            entry = bucket(intervention.person_id, key)
            entry["offered"] += 1
            if outcome == OutcomeKind.ACCEPTED.value:
                entry["accepted"] += 1
            elif outcome == OutcomeKind.DECLINED.value:
                entry["declined"] += 1
            if follow_through:
                entry["followed"] += 1
                if follow_through == FollowThrough.COMPLETED.value:
                    entry["completed"] += 1
        return counts_by_person

    def _candidate_catalogue(self, session: Session) -> dict[str, str]:
        """Human-readable title for every known candidate key, sourced from the same catalogue
        that constructs intervention candidates (`_intervention_candidates`) and programme
        records -- never a second, hand-maintained copy of the title strings.
        """
        titles = {
            candidate.key: candidate.title
            for candidate in self._intervention_candidates(
                session, Decision.GENTLE_NUDGE, _utcnow()
            )
        }
        titles.update(
            {
                f"programme:{programme.programme_id}": programme.name
                for programme in self._programme_models(session)
            }
        )
        return titles

    def _intervention_candidates(
        self,
        session: Session,
        decision: Decision,
        as_of: datetime,
        *,
        person_id: str | None = None,
    ) -> list[InterventionCandidate]:
        """Every candidate this decision class permits, minus anything the person has muted.

        `person_id` is optional and omitting it returns the unfiltered catalogue: the label
        catalogue and the preferences panel both need to name a muted candidate in order for the
        person to un-mute it, so filtering must not be baked into the source of the names.
        """
        candidates = self._decision_candidates(session, decision, as_of)
        if person_id is None:
            return candidates
        suppressed = self._suppressed_candidate_keys(session, person_id)
        return [candidate for candidate in candidates if candidate.key not in suppressed]

    def _decision_candidates(
        self, session: Session, decision: Decision, as_of: datetime
    ) -> list[InterventionCandidate]:
        if decision == Decision.GENTLE_NUDGE:
            return [
                # Both nudges are things a person does alone, at home -- neither has ever
                # involved anyone else. `social_shape=SOLO` is what stops a planner from
                # borrowing a "socially motivated" profile note and turning either into an
                # invitation to a group that does not exist.
                InterventionCandidate(
                    key="gentle_nudge:indoor_walk",
                    title="Gentle movement check-in",
                    message=(
                        "Would a short indoor walk feel manageable today? No pressure—"
                        "you can also choose not today."
                    ),
                    social_shape=SocialPreference.SOLO,
                ),
                InterventionCandidate(
                    key="gentle_nudge:chair_mobility",
                    title="Five-minute movement option",
                    message=(
                        "Would you like a gentle five-minute seated movement option today? "
                        "It is completely optional."
                    ),
                    social_shape=SocialPreference.SOLO,
                    # "Seated" is the fact that makes this option, not the indoor walk, the
                    # right one for someone who cannot easily stand for five minutes. Losing it
                    # to a generic word like "stretch" silently removes the reason it was chosen.
                    accessibility_terms=("seated",),
                ),
                # The one nudge in this class that genuinely involves company, which is what makes
                # `social_shape` discriminating here at all: with three candidates the learner and
                # the planner have a real choice to make, and a senior who has told us they prefer
                # company can be offered something that reflects it. It suggests company in
                # general and never names a person -- Care+ arranges nothing and contacts
                # nobody, so the copy must not imply it has.
                InterventionCandidate(
                    key="gentle_nudge:companion_walk",
                    title="Walk with company",
                    message=(
                        "Would you like to walk with someone today? Some people find company "
                        "makes it easier to get going. Completely optional, and nothing has "
                        "been arranged."
                    ),
                    social_shape=SocialPreference.SOCIAL,
                ),
            ]
        if decision == Decision.PROGRAMME_SUGGESTION:
            return [
                InterventionCandidate(
                    key=f"programme:{programme.programme_id}",
                    title=programme.name,
                    message=(
                        f"Would you like to hear more about {programme.name} at "
                        f"{programme.venue}? Nothing has been booked."
                    ),
                    # AAC programmes are group sessions at a shared venue and time -- unlike the
                    # two nudges above, "with others" is a true statement about a programme.
                    social_shape=SocialPreference.SOCIAL,
                )
                for programme in self._programme_models(session, current_only=True, as_of=as_of)
            ]
        return []

    def _tool_context(
        self,
        session: Session,
        run: ScenarioRunRow,
        state: PersonState,
        ranked: list[InterventionCandidate],
        candidate_learner: PreferenceLearner,
    ) -> ToolContext:
        """Assemble exactly what the planner is allowed to see for this decision.

        Built from the same session and the same `state` that produced the policy decision, so
        the planner reasons over the gate's own view rather than a second, looser copy. The
        candidate list is the allow-list the guardrail later validates against.
        """
        # `(accepted, offers)` per candidate, from the same join that produced the preference
        # scores -- so the counts the planner sees are the exact sample behind each score.
        outcome_counts = self._candidate_outcome_counts(session, run.person_id)
        candidates = [
            CandidateOption(
                key=candidate.key,
                title=candidate.title,
                preference_score=candidate_learner.expected_value(candidate.key),
                times_accepted=outcome_counts.get(candidate.key, (0, 0))[0],
                times_offered=outcome_counts.get(candidate.key, (0, 0))[1],
                social_shape=candidate.social_shape,
                accessibility_terms=candidate.accessibility_terms,
            )
            for candidate in ranked
        ]

        programmes: list[ProgrammeOption] = []
        if state.last_decision == Decision.PROGRAMME_SUGGESTION:
            as_of = datetime.combine(state.current_day, time(hour=12), tzinfo=UTC)
            programmes = [
                ProgrammeOption(
                    key=f"programme:{programme.programme_id}",
                    name=programme.name,
                    venue=programme.venue,
                    distance_km=programme.distance_km,
                    next_session=programme.next_session.isoformat(),
                    accessibility=list(programme.accessibility),
                )
                for programme in self._programme_models(session, current_only=True, as_of=as_of)
            ]

        history_rows = list(
            session.scalars(
                select(InterventionRow)
                .where(InterventionRow.run_id == run.run_id)
                .order_by(InterventionRow.created_at.desc())
                .limit(MAX_AGENT_HISTORY_ROWS)
            )
        )
        history = [
            HistoryEntry(
                created_at=_as_utc(row.created_at).isoformat(),
                decision=row.decision,
                title=row.title,
                outcome=self._latest_outcome(session, row.intervention_id),
                follow_through=self._latest_follow_through(session, row.intervention_id),
                decline_reason=self._latest_decline_reason(session, row.intervention_id),
                # The identity the grounding guardrail matches on. `title` is what the person
                # saw; only this says WHICH option it was, and `_accepted_before` needs the
                # latter. `evidence_json` may predate the key, in which case the entry is
                # unattributable and the guardrail fails closed on it.
                candidate_key=row.evidence_json.get("candidate_key"),
            )
            for row in history_rows
        ]

        profile = persona_profile(run.person_id)
        return ToolContext(
            decision=state.last_decision,
            display_name=state.display_name,
            preferred_language=state.preferred_language,
            context_note=profile.context_note,
            delta_percent=state.signal.delta_percent,
            sustained_low_days=state.signal.sustained_low_days,
            confidence=state.signal.confidence,
            rainy=state.signal.context.rainy,
            holiday=state.signal.context.holiday,
            candidates=candidates,
            programmes=programmes,
            history=history,
            weather_source=state.signal.context.weather_source,
        )

    def _rank_intervention_candidates(
        self, session: Session, run: ScenarioRunRow, state: PersonState
    ) -> tuple[list[InterventionCandidate], PreferenceLearner, PreferenceLearner] | None:
        """The permitted candidates for this decision, ranked, plus the learners that ranked
        them. `None` when the decision does not call for outreach, or nothing permitted remains.

        Pure and read-only, and deliberately callable twice -- once to brief the planner, once
        more inside the write transaction to check nothing has moved since. Both callers must see
        the exact same computation for "unchanged" to mean anything.
        """
        if state.last_decision not in {Decision.GENTLE_NUDGE, Decision.PROGRAMME_SUGGESTION}:
            return None
        candidates = self._intervention_candidates(
            session,
            state.last_decision,
            datetime.combine(state.current_day, time(hour=12), tzinfo=UTC),
            person_id=run.person_id,
        )
        if not candidates:
            # Unreachable in practice on the read phase: `advance` downgrades an all-muted
            # decision to an audited NO_ACTION before it gets here. Reachable on the write phase
            # if every candidate was muted in the window between the two -- handled the same way,
            # no outreach rather than an exception.
            return None
        decision_learner, candidate_learner = self._preference_learners(session, run.person_id)
        # The per-candidate posterior (`expected_value`) is the primary signal, exactly as
        # before -- it is the only one with real acceptance/decline history behind it for this
        # exact key. `social_shape_score` adds a small secondary nudge from the person's SOCIAL
        # dimension preference, which this same person's F27 activity search may already have
        # taught (a stated preference, a decline, or an enjoyed activity's liked aspects) even
        # though this specific outreach candidate has never been offered before. The weight is
        # deliberately small: it can break a near-tie (both gentle-nudge candidates start at an
        # identical 0.25 prior -- see ADR 0005) but cannot outweigh a real acceptance/decline
        # history the way it would if the two terms carried equal magnitude.
        # `run.current_day`, not the wall clock: a preference the person time-boxed ("not this
        # week") must lapse on their simulated calendar here exactly as it does on the activity
        # surface, or outreach would keep ranking on a belief the activity search has retired.
        activity_preferences = self._activity_preferences_model(
            session, run.person_id, run.current_day, run.run_id
        )
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -(
                    candidate_learner.expected_value(candidate.key)
                    + SOCIAL_DIMENSION_RANKING_WEIGHT
                    * social_shape_score(candidate.social_shape, activity_preferences)
                ),
                candidate.key,
            ),
        )
        return ranked, decision_learner, candidate_learner

    def _prepare_outreach_plan(
        self, session: Session, run: ScenarioRunRow, state: PersonState
    ) -> _OutreachPlan | None:
        """The read phase of outreach planning: everything the planner needs, gathered while a
        session is open. Called once, before the session that produced `state` is released and
        before any model is consulted -- see `_plan_outreach_safely` and `_finalize_intervention`
        for what happens either side of that boundary.
        """
        resolved = self._rank_intervention_candidates(session, run, state)
        if resolved is None:
            return None
        ranked, _decision_learner, candidate_learner = resolved
        return _OutreachPlan(
            decision=state.last_decision,
            ranked=ranked,
            # The deterministic ranker's answer is computed first and always. It is the fallback
            # the planner degrades to, so the system holds a valid, safe choice before any model
            # is consulted -- and an identical one when `llm_enabled` is false.
            deterministic=ranked[0],
            tool_context=self._tool_context(session, run, state, ranked, candidate_learner),
        )

    def _plan_outreach_safely(self, plan: _OutreachPlan) -> AgentRun:
        """Runs the planner with no database session open, and always returns.

        `plan_outreach` already degrades every provider failure -- a disabled flag, a timeout, a
        refusal, an exhausted budget -- to a fallback `AgentRun` rather than raising; see its own
        docstring. This still wraps the call, because the phase split downstream depends on it:
        `advance()` calls this between two independent transactions, and whatever comes back
        (or is synthesised here) is what lets the write phase proceed and stay idempotent per
        `event_id`. An exception escaping here must never be allowed to skip that write phase.
        """
        fallback_choice = (plan.deterministic.key, plan.deterministic.message)
        try:
            return plan_outreach(
                plan.tool_context,
                settings=self.settings,
                fallback_choice=fallback_choice,
            )
        except Exception as error:  # noqa: BLE001 - must degrade, never break the write phase
            key, message = fallback_choice
            return AgentRun(
                evidence_id=_id("agent"),
                agent_version=AGENT_VERSION,
                mode="fallback_error",
                decision=plan.decision,
                model=None,
                started_at=_utcnow(),
                latency_ms=0,
                iterations=0,
                max_iterations=self.settings.llm_max_iterations,
                tool_calls=[],
                guardrail_rejections=[],
                proposal=None,
                selected_candidate_key=key,
                selected_message=message,
                # The exception's class only; `log_provider_failure` puts the text on the
                # operator log with the request id instead. `evidence_json` is append-only and
                # coordinator-visible, so a provider message must never land in it.
                fallback_reason=log_provider_failure(error, loop="outreach"),
                usage=AgentUsage(),
            )

    def _finalize_intervention(
        self,
        session: Session,
        run: ScenarioRunRow,
        state: PersonState,
        decision_row: DecisionEvidenceRow,
        plan: _OutreachPlan | None,
        agent_run: AgentRun | None,
    ) -> Intervention | None:
        """The write phase of outreach planning: persists an intervention against candidates and
        preferences read fresh, in this transaction -- never against what `plan` saw before the
        planner call.

        `agent_run`'s choice is honoured only if the world it was planned against still holds
        exactly: the same decision class, and the exact same ranked candidate keys. Consent
        being revoked, the weekly contact cap being newly reached, or a candidate being freshly
        muted or unmuted, or a decline changing a ranking, all change that fingerprint. Any
        mismatch discards the planner's output outright and falls back to the deterministic
        choice this transaction just computed -- the same path taken when the planner was never
        consulted at all. An LLM-chosen action must never outlive the policy decision that
        permitted it; this is what enforces that at the only point it can be enforced, right
        before the row is written.
        """
        resolved = self._rank_intervention_candidates(session, run, state)
        if resolved is None:
            return None
        ranked, decision_learner, candidate_learner = resolved
        deterministic = ranked[0]
        by_key = {candidate.key: candidate for candidate in ranked}

        unchanged = (
            plan is not None
            and plan.decision == state.last_decision
            and [candidate.key for candidate in plan.ranked]
            == [candidate.key for candidate in ranked]
        )
        stale_plan_discarded = False
        if unchanged and agent_run is not None:
            resolved_agent_run = agent_run
        else:
            stale_plan_discarded = agent_run is not None
            resolved_agent_run = AgentRun(
                evidence_id=_id("agent"),
                agent_version=AGENT_VERSION,
                mode="fallback_error" if stale_plan_discarded else "fallback_disabled",
                decision=state.last_decision,
                model=agent_run.model if agent_run else None,
                started_at=agent_run.started_at if agent_run else _utcnow(),
                latency_ms=agent_run.latency_ms if agent_run else 0,
                iterations=agent_run.iterations if agent_run else 0,
                max_iterations=(
                    agent_run.max_iterations if agent_run else self.settings.llm_max_iterations
                ),
                tool_calls=agent_run.tool_calls if agent_run else [],
                guardrail_rejections=agent_run.guardrail_rejections if agent_run else [],
                proposal=None,
                selected_candidate_key=deterministic.key,
                selected_message=deterministic.message,
                fallback_reason=(
                    "The permitted candidates changed between planning and writing -- consent, "
                    "the weekly contact cap, or this person's preferences moved in the "
                    "meantime -- so the planner's proposal was discarded and the deterministic "
                    "ranker's choice, computed fresh, was used instead."
                    if stale_plan_discarded
                    else "No outreach was planned ahead of this write; the deterministic "
                    "ranker's choice was used."
                ),
                usage=agent_run.usage if agent_run else AgentUsage(),
            )

        # `selected_candidate_key` is guaranteed to be in the permitted set here: either
        # `resolved_agent_run` is the original, unmodified `agent_run` and `unchanged` proved its
        # key is among `by_key`'s own keys, or it is the synthetic fallback above, whose key is
        # `deterministic.key`. The `.get` default is belt and braces, not an expected branch.
        selected = by_key.get(resolved_agent_run.selected_candidate_key, deterministic)
        selected_message = resolved_agent_run.selected_message or selected.message
        evidence = {
            "decision_evidence_id": decision_row.evidence_id,
            "delta_percent": state.signal.delta_percent,
            "confidence": state.signal.confidence,
            "policy_version": POLICY_VERSION,
            "candidate_key": selected.key,
            "candidate_preference_score": candidate_learner.expected_value(selected.key),
            "decision_preference_score": decision_learner.expected_value(state.last_decision.value),
            "candidate_ranking": [
                {
                    "candidate_key": candidate.key,
                    "score": candidate_learner.expected_value(candidate.key),
                }
                for candidate in ranked
            ],
            "learning_boundary": (
                "Ranking occurred only after deterministic policy and consent gates passed."
            ),
            "deterministic_candidate_key": deterministic.key,
            "agent": resolved_agent_run.as_evidence(),
            "stale_plan_discarded": stale_plan_discarded,
        }
        row = InterventionRow(
            intervention_id=_id("int"),
            run_id=run.run_id,
            person_id=run.person_id,
            decision_evidence_id=decision_row.evidence_id,
            decision=state.last_decision.value,
            title=selected.title,
            message=selected_message,
            created_at=_utcnow(),
            status="proposed",
            evidence_json=evidence,
        )
        session.add(row)
        session.flush()
        return self._to_intervention(session, row)

    def _create_case(
        self,
        session: Session,
        run: ScenarioRunRow,
        state: PersonState,
        decision_row: DecisionEvidenceRow,
    ) -> ReviewCase | None:
        if state.last_decision != Decision.COORDINATOR_REVIEW:
            return None

        # "valid-wear days", never a bare "days": `analytics._sustained_low_days` skips a day
        # with too little wear-time rather than counting it, so the number is a count of days
        # Care+ could actually read, and reading it as "the last N days" overstates how much
        # of the person's week is behind the percentage beside it. The web twin
        # (`view-models.severityDetail`) has always carried the qualifier and the ladder's own
        # `why_human` says "for enough valid-wear days"; the surface that shows the number is the
        # one that most needs the caveat. Coordinator-facing, where a percentage is permitted.
        summary = (
            f"Activity is {abs(state.signal.delta_percent):.0f}% below "
            f"{state.display_name}'s personal baseline across "
            f"{state.signal.sustained_low_days} valid-wear "
            f"{'day' if state.signal.sustained_low_days == 1 else 'days'}."
        )

        # One open case per person, refreshed — not one per day the concern persists.
        #
        # A sustained decline re-reaches this rung every single day it continues, and creating a
        # row each time produced eighteen near-identical cards for one person in the drift
        # scenario. That makes the queue unreadable exactly when it matters most, and makes
        # `metrics.open_cases` count days rather than people.
        #
        # Updating in place is also the truthful model: it is still the same concern, and a
        # coordinator wants its current state, not a stack of snapshots. `created_case` is
        # deliberately `None` on a refresh, because nothing was created.
        #
        # "Unresolved", not "open" -- the same predicate `_close_open_cases_for_consent` and
        # `_close_open_cases_for_recovery` already use. `ACKNOWLEDGED` is a non-terminal status
        # the old `== OPEN` test did not recognise, so a coordinator who acknowledged a case and
        # then saw one more declining day got a *second* card for the same concern about the same
        # person, while the acknowledged one froze at the day count it had when they read it and
        # `metrics.open_cases` still said one. Only a genuinely closed concern that returns opens
        # a new case.
        existing = session.scalar(
            select(ReviewCaseRow)
            .where(
                ReviewCaseRow.run_id == run.run_id,
                ReviewCaseRow.person_id == run.person_id,
                ReviewCaseRow.status != CaseStatus.RESOLVED.value,
            )
            .order_by(ReviewCaseRow.opened_at.desc(), ReviewCaseRow.case_id.desc())
        )
        if existing is not None:
            # The status is deliberately left alone. A coordinator acknowledged the *concern*,
            # not one day's number; quietly reopening it would erase the fact that a human has
            # already picked this up, and would put it back on the queue they had cleared it
            # from.
            existing.summary = summary
            existing.evidence_json = state.rationale
            existing.decision_evidence_id = decision_row.evidence_id
            session.flush()
            return None

        row = ReviewCaseRow(
            case_id=_id("case"),
            run_id=run.run_id,
            person_id=run.person_id,
            decision_evidence_id=decision_row.evidence_id,
            title="Sustained activity decline requires human review",
            status=CaseStatus.OPEN.value,
            priority=4,
            opened_at=_utcnow(),
            # The simulated day the concern reached a human, not the wall clock beside it. Set
            # once here; the refresh branch above deliberately leaves it alone.
            opened_day=state.current_day,
            summary=summary,
            evidence_json=state.rationale,
            recommendation=("Check what you know about them, then decide whether to check in."),
        )
        session.add(row)
        session.flush()
        return self._to_case(session, row)

    @staticmethod
    def _audit_row(
        run_id: str,
        event_type: str,
        actor: str,
        *,
        person_id: str,
        decision: Decision | None = None,
        detail: dict[str, object] | None = None,
        at: datetime | None = None,
    ) -> AuditEventRow:
        return AuditEventRow(
            event_id=_id("evt"),
            run_id=run_id,
            person_id=person_id,
            event_type=event_type,
            actor=actor,
            decision=decision.value if decision else None,
            detail_json=detail or {},
            recorded_at=at or _utcnow(),
        )

    @staticmethod
    def _to_audit(row: AuditEventRow) -> AuditEvent:
        return AuditEvent(
            event_id=row.event_id,
            at=_as_utc(row.recorded_at),
            event_type=row.event_type,
            actor=row.actor,
            person_id=row.person_id,
            decision=Decision(row.decision) if row.decision else None,
            detail=row.detail_json,
        )

    @staticmethod
    def _latest_outcome_row(
        session: Session, intervention_id: str
    ) -> InterventionOutcomeRow | None:
        return session.scalar(
            select(InterventionOutcomeRow)
            .where(InterventionOutcomeRow.intervention_id == intervention_id)
            .order_by(
                InterventionOutcomeRow.recorded_at.desc(),
                InterventionOutcomeRow.outcome_id.desc(),
            )
            .limit(1)
        )

    def _latest_outcome(self, session: Session, intervention_id: str) -> str | None:
        row = self._latest_outcome_row(session, intervention_id)
        return row.outcome if row else None

    def _latest_decline_reason(self, session: Session, intervention_id: str) -> str | None:
        """The most recent `DeclineReason` recorded for this intervention, if any -- reusing the
        same latest-outcome row `_latest_outcome` reads, since a reason can arrive with the
        original answer or as a later amendment (see `record_outcome`).
        """
        row = self._latest_outcome_row(session, intervention_id)
        return row.reason if row else None

    @staticmethod
    def _follow_through_row(
        session: Session, intervention_id: str
    ) -> InterventionFollowThroughRow | None:
        return session.scalar(
            select(InterventionFollowThroughRow).where(
                InterventionFollowThroughRow.intervention_id == intervention_id
            )
        )

    def _latest_follow_through(self, session: Session, intervention_id: str) -> str | None:
        row = self._follow_through_row(session, intervention_id)
        return row.follow_through if row else None

    @staticmethod
    def _candidate_key_of(row: InterventionRow) -> str:
        return str(row.evidence_json.get("candidate_key", row.decision))

    @staticmethod
    def _catalogue_row_for_programme(
        session: Session, programme_row: ProgrammeRow
    ) -> ActivityCandidateRow | None:
        """The catalogue listing a programme is, matched by title.

        `Programme` and `activity_candidates` are separate tables with unrelated ids, so title is
        the only join there is. The soonest upcoming session wins; any session will do if none is
        upcoming. The one place this lookup lives -- `outreach_detail` and the decline learner
        both go through it, which is the point: they used to resolve the *same* programme two
        different ways, so the detail card knew the listing was a light chair class while the
        learner, looking at a synthesised programme candidate with no intensity at all, recorded
        a belief that contradicted it.
        """
        row = session.scalar(
            select(ActivityCandidateRow)
            .where(
                ActivityCandidateRow.title == programme_row.name,
                ActivityCandidateRow.start_at.is_not(None),
            )
            .order_by(ActivityCandidateRow.start_at)
        )
        if row is not None:
            return row
        return session.scalar(
            select(ActivityCandidateRow).where(ActivityCandidateRow.title == programme_row.name)
        )

    @staticmethod
    def _series_for_candidate_key(session: Session, candidate_key: str) -> str | None:
        """The programme `candidate_key` is a session of, as `activity_search.series_key`.

        An `activity:<id>` key is its listing's series. A `programme:<id>` key is the series of the
        catalogue listing that programme is (`_catalogue_row_for_programme`, the same title join
        `_activity_candidate_for_key` resolves through), so an outreach decline on a programme and
        a search decline on any session of its listing name the same programme. A programme with
        no listing is only ever the same programme as itself, so it is its own key -- which no
        series key can equal. Anything else (a gentle nudge, an unknown id) is `None`: no
        programme, and so no claim that two answers were about the same one.

        Resolved from the rows as they are now, never from a stored copy, so both sides of a
        comparison are always read the same way.
        """
        kind, _, identifier = candidate_key.partition(":")
        if kind == "activity":
            row = session.get(ActivityCandidateRow, identifier)
            return series_key(row) if row is not None else None
        if kind == "programme":
            programme_row = session.get(ProgrammeRow, identifier)
            if programme_row is None:
                return None
            listing_row = SqlAlchemyRepository._catalogue_row_for_programme(session, programme_row)
            return SqlAlchemyRepository._programme_series(candidate_key, listing_row)
        return None

    @staticmethod
    def _programme_series(candidate_key: str, listing_row: ActivityCandidateRow | None) -> str:
        """A `programme:<id>` key's series: its catalogue listing's, or the key itself when it has
        none. The one rule `_series_for_candidate_key` and `_activity_candidate_and_series` share,
        so the answer being folded and the origins it is compared with are read the same way."""
        return series_key(listing_row) if listing_row is not None else candidate_key

    @staticmethod
    def _origin_series(session: Session, origin_ids: Iterable[str | None]) -> dict[str, str]:
        """`origin_id -> series key` for every origin that is an answer about a programme.

        `preferences._fold` reads this to tell a second answer about the *same* programme (not a
        second agreeing answer -- the cooldown already holds that programme back) from one about a
        different programme. An origin is looked up by id in the two tables a decline's origin
        can live in -- a search response (`ActivityOfferResponseRow` -> its listing) and an
        intervention outcome (`InterventionOutcomeRow` -> `InterventionRow` -> its candidate key)
        -- and never by parsing the id's prefix. An origin found in neither (a plan, a statement,
        a legacy or deleted row) is simply absent, and an absent origin keeps today's behaviour.
        """
        ids = sorted({origin_id for origin_id in origin_ids if origin_id})
        if not ids:
            return {}
        series: dict[str, str] = {}
        for response_id, listing_row in session.execute(
            select(ActivityOfferResponseRow.response_id, ActivityCandidateRow)
            .join(
                ActivityCandidateRow,
                ActivityCandidateRow.activity_id == ActivityOfferResponseRow.activity_id,
            )
            .where(ActivityOfferResponseRow.response_id.in_(ids))
        ):
            series[response_id] = series_key(listing_row)
        by_candidate_key: dict[str, str | None] = {}
        for outcome_id, intervention_row in session.execute(
            select(InterventionOutcomeRow.outcome_id, InterventionRow)
            .join(
                InterventionRow,
                InterventionRow.intervention_id == InterventionOutcomeRow.intervention_id,
            )
            .where(InterventionOutcomeRow.outcome_id.in_(ids))
        ):
            candidate_key = SqlAlchemyRepository._candidate_key_of(intervention_row)
            if candidate_key not in by_candidate_key:
                by_candidate_key[candidate_key] = SqlAlchemyRepository._series_for_candidate_key(
                    session, candidate_key
                )
            resolved = by_candidate_key[candidate_key]
            if resolved is not None:
                series[outcome_id] = resolved
        return series

    def _activity_candidate_and_series(
        self, session: Session, candidate_key: str
    ) -> tuple[ActivityCandidate | None, str | None]:
        """`_activity_candidate_for_key` and `_series_for_candidate_key` in one resolution, so a
        `programme:<id>` key looks its catalogue listing up once rather than twice."""
        kind, _, identifier = candidate_key.partition(":")
        if kind == "activity":
            row = session.get(ActivityCandidateRow, identifier)
            if row is None:
                return None, None
            return self._to_activity_candidate(row), series_key(row)
        if kind == "programme":
            programme_row = session.get(ProgrammeRow, identifier)
            if programme_row is None:
                return None, None
            programme_candidate = ActivityCandidate(
                activity_id=f"programme:{programme_row.programme_id}",
                source=ActivitySource.AAC_FIXTURE,
                integration_status=IntegrationStatus.FIXTURE,
                title=programme_row.name,
                provider=programme_row.venue,
                start_at=_as_utc(programme_row.next_session),
                location=ActivityLocation(name=programme_row.venue),
                accessibility_tags=list(programme_row.accessibility_json),
                retrieved_at=_as_utc(programme_row.next_session),
                distance_m=int(round(programme_row.distance_km * 1000)),
                distance_basis=DistanceBasis.LISTING_STATIC,
            )
            listing_row = self._catalogue_row_for_programme(session, programme_row)
            series = self._programme_series(candidate_key, listing_row)
            if listing_row is None:
                return programme_candidate, series
            listing = self._to_activity_candidate(listing_row)
            return programme_candidate.model_copy(
                update={
                    "activity_type": listing.activity_type,
                    "activity_families": list(listing.activity_families),
                    "format": listing.format,
                    "category": listing.category,
                    "indoor_outdoor": listing.indoor_outdoor,
                    "intensity": listing.intensity,
                    "social_shape": listing.social_shape,
                    "language_tags": list(listing.language_tags),
                }
            ), series
        return None, None

    def _apply_activity_decline(
        self,
        session: Session,
        person_id: str,
        candidate_key: str,
        decline_reason: str | None,
        now: datetime,
        *,
        clarification: ClarificationScope | None = None,
        origin_id: str | None = None,
    ) -> list[DimensionPreference]:
        """Fold a decline reason into the person's dimension preferences; return what moved.

        A no-op whenever there is nothing to learn from: no reason given, a reason that maps to
        no dimension (`bad_day`, `already_active`), or a candidate that is not a real, resolvable
        `ActivityCandidate` -- `apply_decline` already encodes all three, so this only has to
        supply it a real candidate and persist whatever comes back. Returns the moved preferences
        so a caller can show the person what their answer taught.

        `origin_id` names the one thing the person did that this decline *is* -- the search
        response row, or the intervention outcome row -- and every production caller passes one.
        It is what `preferences._fold` counts distinct origins by, so a null here is a belief
        that can be grown twice from a single answer (red team P1-1); `candidate_key` is a
        different thing entirely and naming the listing there is not naming the answer.

        `series` and `origin_series` name the programme this answer is about and the programme
        each held belief's origin was about (`_series_for_candidate_key`, `_origin_series`), so an
        unclarified second answer about the same programme -- the same listing on another day, a
        sibling session, or the programme's outreach card -- leaves an item-level belief held
        back rather than widening it. Only an answer about a different programme agrees.
        """
        if decline_reason is None:
            return []
        candidate, candidate_series = self._activity_candidate_and_series(session, candidate_key)
        if candidate is None:
            return []
        run = self._active_run(session, person_id)
        if not scope_permitted(
            ConsentScope.PREFERENCE_LEARNING,
            consent_active=self._consent_active(session, run.run_id),
        ):
            # Pausing Care+ pauses inference. The answer itself is still recorded (it is the
            # person's, under `ConsentScope.USER_INITIATED_SEARCH`, which is never paused), and
            # anything they state outright through `state_preference` is still honoured, but
            # nothing new is *inferred* about them while consent is withdrawn.
            return []
        today = run.current_day
        active_rows, expired_rows = self._dimension_rows(session, person_id, today, run.run_id)
        existing = [self._to_dimension_preference(row) for row in active_rows]
        reason = DeclineReason(decline_reason)
        # Only TIMING and ACTIVITY_TYPE declines are item-level, so only they read the programme
        # rule -- and only against rows on that same axis. Every other reason skips the lookups.
        dimension = DECLINE_REASON_DIMENSIONS.get(reason)
        item_level = dimension in _PROGRAMME_RULE_DIMENSIONS
        updated = apply_decline(
            existing,
            reason,
            candidate,
            now,
            clarification=clarification,
            origin_id=origin_id,
            series=candidate_series if item_level else None,
            origin_series=(
                self._origin_series(
                    session,
                    (
                        preference.origin_id
                        for preference in existing
                        if preference.dimension is dimension
                    ),
                )
                if item_level
                else None
            ),
        )
        if updated == existing:
            return []
        moved = self._persist_dimension_preferences(
            session, person_id, run.run_id, active_rows, expired_rows, existing, updated, now
        )
        return self._only_what_is_actually_held(moved, updated, today, run.run_id)

    @staticmethod
    def _only_what_is_actually_held(
        moved: list[DimensionPreference],
        updated: list[DimensionPreference],
        today: date,
        run_id: str,
    ) -> list[DimensionPreference]:
        """What the person is told their answer taught, restricted to what it *actually* taught.

        An item-level answer is recorded the moment it happens -- the row is the evidence, and a
        second answer about a different programme is what widens it -- but until it resolves it
        changes nothing the person will see in what they are offered. Telling them "Care+
        will lean away from activities in the morning" after one bad Tuesday would be describing a
        belief the ranker does not hold. `resolve` is the same gate the ranker reads, so the two
        cannot disagree.
        """
        if not moved:
            return []
        held = {
            (preference.dimension, preference.value)
            for preference in resolve(updated, today, run_id)
        }
        return [
            preference for preference in moved if (preference.dimension, preference.value) in held
        ]

    @staticmethod
    def _latest_outcome_rows(
        session: Session, intervention_ids: Sequence[str]
    ) -> dict[str, InterventionOutcomeRow]:
        """`_latest_outcome_row` for every id in `intervention_ids`, in one query."""
        if not intervention_ids:
            return {}
        latest: dict[str, InterventionOutcomeRow] = {}
        for row in session.scalars(
            select(InterventionOutcomeRow)
            .where(InterventionOutcomeRow.intervention_id.in_(intervention_ids))
            .order_by(
                InterventionOutcomeRow.recorded_at.desc(),
                InterventionOutcomeRow.outcome_id.desc(),
            )
        ):
            latest.setdefault(row.intervention_id, row)
        return latest

    @staticmethod
    def _follow_through_by_id(session: Session, intervention_ids: Sequence[str]) -> dict[str, str]:
        """`_latest_follow_through` for every id in `intervention_ids`, in one query (at most one
        report per intervention, by constraint)."""
        if not intervention_ids:
            return {}
        return {
            intervention_id: report
            for intervention_id, report in session.execute(
                select(
                    InterventionFollowThroughRow.intervention_id,
                    InterventionFollowThroughRow.follow_through,
                ).where(InterventionFollowThroughRow.intervention_id.in_(intervention_ids))
            )
        }

    @staticmethod
    def _observed_at_for(
        session: Session, rows: Sequence[InterventionRow]
    ) -> dict[str, datetime | None]:
        """Each intervention's decision evidence `observed_at` (`None` where that evidence does
        not exist), in one query -- what `_outreach_day` reads one row at a time."""
        facts = SqlAlchemyRepository._evidence_facts(
            session, [row.decision_evidence_id for row in rows]
        )
        return {
            row.intervention_id: (
                facts[row.decision_evidence_id][0] if row.decision_evidence_id in facts else None
            )
            for row in rows
        }

    @staticmethod
    def _outreach_day_from(row: InterventionRow, observed_at: datetime | None) -> date:
        """`_outreach_day`, given the decision evidence's `observed_at` already read."""
        if observed_at is not None:
            return _as_utc(observed_at).date()
        return _as_utc(row.created_at).date()

    def _to_intervention(self, session: Session, row: InterventionRow) -> Intervention:
        return self._to_interventions(session, [row])[0]

    def _to_interventions(
        self,
        session: Session,
        rows: Sequence[InterventionRow],
        *,
        observed_at: dict[str, datetime | None] | None = None,
    ) -> list[Intervention]:
        """The contract shape of each intervention, in `rows` order, in a fixed number of queries.

        `observed_at` is each row's decision evidence `observed_at` when the caller read it with
        the rows; otherwise it is read here, and only if some row is still awaiting a reply.
        """
        if not rows:
            return []
        ids = [row.intervention_id for row in rows]
        latest = self._latest_outcome_rows(session, ids)
        follow_through = self._follow_through_by_id(session, ids)
        enjoyment = {
            intervention_id: value
            for intervention_id, value in session.execute(
                select(
                    InterventionEnjoymentRow.intervention_id,
                    InterventionEnjoymentRow.enjoyment,
                ).where(InterventionEnjoymentRow.intervention_id.in_(ids))
            )
        }
        waiting = [
            row for row in rows if row.status == "proposed" and row.intervention_id not in latest
        ]
        if observed_at is None and waiting:
            observed_at = self._observed_at_for(session, waiting)
        evidence_observed = observed_at or {}
        interventions: list[Intervention] = []
        for row in rows:
            outcome_row = latest.get(row.intervention_id)
            interventions.append(
                Intervention(
                    intervention_id=row.intervention_id,
                    person_id=row.person_id,
                    decision=Decision(row.decision),
                    title=row.title,
                    message=row.message,
                    created_at=_as_utc(row.created_at),
                    status=row.status,
                    outcome=outcome_row.outcome if outcome_row else None,
                    follow_through=follow_through.get(row.intervention_id),
                    # Written by `record_enjoyment` and, until this line existed, never read back:
                    # the field was always null over HTTP, so the senior screen re-asked "how was
                    # it?" on every visit and the second answer was rejected as a duplicate.
                    enjoyment=enjoyment.get(row.intervention_id),
                    candidate_key=self._candidate_key_of(row),
                    awaiting_reply_until=_awaiting_reply_from(
                        row,
                        outcome_row,
                        lambda row=row: self._outreach_day_from(
                            row, evidence_observed.get(row.intervention_id)
                        ),
                    ),
                    evidence=row.evidence_json,
                )
            )
        return interventions

    def list_interventions(self, *, person_id: str = DEMO_PERSON_ID) -> list[Intervention]:
        with self.sessions() as session:
            run = self._active_run(session, person_id)
            found = session.execute(
                select(InterventionRow, DecisionEvidenceRow.observed_at)
                .select_from(InterventionRow)
                .outerjoin(
                    DecisionEvidenceRow,
                    DecisionEvidenceRow.evidence_id == InterventionRow.decision_evidence_id,
                )
                .where(InterventionRow.run_id == run.run_id)
                .order_by(InterventionRow.created_at.desc(), InterventionRow.intervention_id.desc())
            ).all()
            return self._to_interventions(
                session,
                [row for row, _ in found],
                observed_at={row.intervention_id: observed for row, observed in found},
            )

    def record_outcome(
        self,
        intervention_id: str,
        outcome: OutcomeKind | str,
        actor: str = "senior",
        *,
        reason: DeclineReason | str | None = None,
        person_id: str | None = None,
    ) -> OutcomeResponse:
        outcome = OutcomeKind(outcome)
        allowed = {
            OutcomeKind.ACCEPTED,
            OutcomeKind.DECLINED,
            # "Maybe later" is an answer, and it is not the same answer as silence. It is
            # recorded through this route so that it moves the posterior by nothing at all
            # rather than being filed as a near-refusal.
            OutcomeKind.DEFERRED,
            OutcomeKind.NO_RESPONSE,
            OutcomeKind.ACTIVITY_RECOVERED,
        }
        if outcome not in allowed:
            raise ValueError("Coordinator outcomes must be recorded through case review.")
        decline_reason = DeclineReason(reason).value if reason is not None else None
        now = _utcnow()
        with self.sessions.begin() as session:
            # Locked for the same reason `_resolve_unanswered_outreach` locks it: the response
            # clock and a person's answer must never both be recorded against one offer.
            row = session.get(InterventionRow, intervention_id, with_for_update=True)
            if row is None:
                raise KeyError(intervention_id)
            if person_id is not None and row.person_id != person_id:
                # An intervention that belongs to someone else must be indistinguishable from
                # one that does not exist -- do not leak existence via a different error/status.
                raise KeyError(intervention_id)
            active_run = self._require_current_run(session, row)
            existing = session.scalar(
                select(InterventionOutcomeRow)
                .where(InterventionOutcomeRow.intervention_id == intervention_id)
                .order_by(
                    InterventionOutcomeRow.recorded_at.desc(),
                    InterventionOutcomeRow.outcome_id.desc(),
                )
                .limit(1)
            )
            if existing is not None:
                # One narrow amendment is allowed: attaching a reason to an answer already given.
                #
                # The senior screen records "Not today" first and only then offers the optional
                # reasons, because the decline must be saved whether or not the person goes on to
                # say why -- making the reason a precondition would hold a refusal hostage to a
                # follow-up question. That means the reason necessarily arrives as a second call.
                #
                # It stays narrow on purpose. The same answer, a reason that is actually present,
                # and none stored yet; anything else is still the duplicate that gets rejected.
                # Crucially the posterior is NOT recomputed -- "duplicate outcomes are rejected
                # without applying preference learning twice" is the property this guard exists
                # to hold, and adding a note to an answer is not a second answer.
                if existing.actor == "system":
                    # Not a duplicate of anything the person said, and not something a reason can
                    # be attached to either: the response clock closed this offer as unanswered.
                    # Telling them their answer is "already recorded" would be literally true and
                    # plainly misleading.
                    raise ValueError(
                        "This offer was closed as unanswered after "
                        f"{RESPONSE_WINDOW_DAYS} days, so a reply can no longer be recorded "
                        "against it. Nothing was counted against the person; a newer "
                        "suggestion is answered in the usual way."
                    )
                if (
                    existing.outcome != outcome.value
                    or decline_reason is None
                    or existing.reason is not None
                ):
                    raise ValueError("An outcome has already been recorded for this intervention.")
                # `intervention_outcomes` is append-only -- a migration-created trigger rejects
                # UPDATE and DELETE outright (SQLite: `intervention_outcomes_reject_update`;
                # Postgres: `intervention_outcomes_append_only`), so `existing.reason = ...`
                # followed by a flush would abort the transaction on every environment whose
                # schema came from `alembic upgrade head`. The reason is instead recorded as a
                # new evidence row for the same intervention and outcome, which is what
                # append-only means: the amendment supersedes the original by being newer, not
                # by overwriting it. `_latest_outcome_row`/`_latest_outcome` already resolve to
                # the most recent row per intervention (`order_by(recorded_at.desc(), ...)`), so
                # every read of "the" outcome picks this one up automatically. The only readers
                # that fold *every* outcome row into a count -- `_preference_learners`,
                # `_candidate_outcome_counts`, `_candidate_activity_counts` -- are filtered down
                # to one (latest) row per intervention via `_latest_outcome_ids_subquery`, so this
                # second row is never learned from twice.
                candidate_key = self._candidate_key_of(row)
                # Read before the amendment lands. A reason is still not a second answer -- the
                # amendment supersedes the original row rather than adding to it, so the
                # candidate keeps exactly one unit of evidence -- but since declines became
                # reason-keyed the single unit is no longer necessarily the same size: attaching
                # `bad_day` to a decline already recorded RE-WEIGHTS that one answer down to the
                # zero-weight carve-out. Reporting the post-amendment value as `preference_before`
                # hid that correction behind two identical numbers.
                _, amend_before_learner = self._preference_learners(session, row.person_id)
                preference_before = amend_before_learner.expected_value(candidate_key)
                amendment_row = InterventionOutcomeRow(
                    outcome_id=_id("outcome"),
                    intervention_id=intervention_id,
                    run_id=row.run_id,
                    outcome=existing.outcome,
                    reason=decline_reason,
                    actor=actor,
                    reviewer=None,
                    recorded_at=now,
                )
                session.add(amendment_row)
                # This is the one point a reason can arrive for the first time -- the initial
                # call may have carried none -- so it is also the one point the dimensional
                # learner (ranking-only, distinct from the per-candidate posterior below) gets
                # to see it.
                self._apply_activity_decline(
                    session,
                    row.person_id,
                    candidate_key,
                    decline_reason,
                    now,
                    # The amendment row *is* the origin of this reason: it is the first (and,
                    # since a reason can only be attached to an answer that has none, the only)
                    # outcome row carrying it. Naming it keeps `_fold`'s one-origin rule live on
                    # this path too, so a retried amendment folds once.
                    origin_id=amendment_row.outcome_id,
                )
                session.flush()
                _, amend_after_learner = self._preference_learners(session, row.person_id)
                preference_after = amend_after_learner.expected_value(candidate_key)
                amend_audit = self._audit_row(
                    row.run_id,
                    "intervention_outcome_reason_added",
                    actor,
                    person_id=row.person_id,
                    decision=Decision(row.decision),
                    detail={
                        "intervention_id": intervention_id,
                        "outcome_evidence_id": amendment_row.outcome_id,
                        "superseded_outcome_evidence_id": existing.outcome_id,
                        "outcome": amendment_row.outcome,
                        "reason": decline_reason,
                        "candidate_key": candidate_key,
                        "learning_boundary": (
                            "A reason is context on one answer, not a second answer: it "
                            "re-weights that single answer rather than adding a second unit "
                            "of evidence."
                        ),
                    },
                    at=now,
                )
                session.add(amend_audit)
                session.flush()
                return OutcomeResponse(
                    intervention=self._to_intervention(session, row),
                    outcome_evidence_id=amendment_row.outcome_id,
                    outcome=outcome,
                    preference_before=preference_before,
                    preference_after=preference_after,
                    candidate_key=candidate_key,
                    audit_event=self._to_audit(amend_audit),
                )
            if not self._consent_active(session, active_run.run_id) or row.status.startswith(
                "withdrawn"
            ):
                raise ValueError("Consent is inactive; this intervention has been withdrawn.")
            candidate_key = self._candidate_key_of(row)
            _, before_learner = self._preference_learners(session, row.person_id)
            preference_before = before_learner.expected_value(candidate_key)
            outcome_row = InterventionOutcomeRow(
                outcome_id=_id("outcome"),
                intervention_id=intervention_id,
                run_id=row.run_id,
                outcome=outcome.value,
                reason=decline_reason,
                actor=actor,
                reviewer=None,
                recorded_at=now,
            )
            session.add(outcome_row)
            row.status = "closed"
            session.flush()
            self._apply_activity_decline(
                session,
                row.person_id,
                candidate_key,
                decline_reason,
                now,
                # One outcome row, one observation -- see `_fold`.
                origin_id=outcome_row.outcome_id,
            )
            suppressed = self._suppress_after_repeated_declines(
                session, row, candidate_key, actor, now
            )
            _, after_learner = self._preference_learners(session, row.person_id)
            preference_after = after_learner.expected_value(candidate_key)
            audit_row = self._audit_row(
                row.run_id,
                "intervention_outcome_recorded",
                actor,
                person_id=row.person_id,
                decision=Decision(row.decision),
                detail={
                    "intervention_id": intervention_id,
                    "outcome_evidence_id": outcome_row.outcome_id,
                    "outcome": outcome.value,
                    "reason": decline_reason,
                    "decision_evidence_id": row.decision_evidence_id,
                    "candidate_key": candidate_key,
                    "preference_before": preference_before,
                    "preference_after": preference_after,
                    "candidate_suppressed": suppressed,
                    "learning_boundary": "Safety and consent policy remained unchanged.",
                },
                at=now,
            )
            session.add(audit_row)
            session.flush()
            result = self._to_intervention(session, row)
            audit = self._to_audit(audit_row)
        return OutcomeResponse(
            intervention=result,
            outcome_evidence_id=outcome_row.outcome_id,
            outcome=outcome,
            preference_before=preference_before,
            preference_after=preference_after,
            candidate_key=candidate_key,
            audit_event=audit,
        )

    @staticmethod
    def _decline_counts_toward_suppression() -> ColumnElement[bool]:
        """A "bad day" or "I was already active" decline says nothing about the option, so it
        never counts toward muting it -- the same boundary `preferences.apply_decline` keeps.
        Three of those in a row used to silence a candidate for good."""
        return or_(
            InterventionOutcomeRow.reason.is_(None),
            InterventionOutcomeRow.reason.not_in(
                [DeclineReason.BAD_DAY.value, DeclineReason.ALREADY_ACTIVE.value]
            ),
        )

    def _suppress_after_repeated_declines(
        self,
        session: Session,
        row: InterventionRow,
        candidate_key: str,
        actor: str,
        now: datetime,
    ) -> bool:
        """Stop offering a candidate the person has declined `DECLINES_BEFORE_SUPPRESSION` times.

        Deterministic, audited, and reversible by the person. It is not a learned score: the
        learner ranks what policy permits, and this changes what policy permits. Declining three
        times is a person saying something plainly, and a system that keeps asking is not
        learning from them, it is ignoring them politely.
        """
        declines = int(
            session.scalar(
                select(func.count())
                .select_from(InterventionOutcomeRow)
                .join(
                    InterventionRow,
                    InterventionRow.intervention_id == InterventionOutcomeRow.intervention_id,
                )
                .where(
                    InterventionRow.person_id == row.person_id,
                    InterventionOutcomeRow.outcome == OutcomeKind.DECLINED.value,
                    self._decline_counts_toward_suppression(),
                )
            )
            or 0
        )
        if declines < DECLINES_BEFORE_SUPPRESSION:
            return False
        # Count again for this candidate only; the cheap total above avoids the join in the
        # common case where nothing has been declined at all.
        declines = sum(
            1
            for intervention in session.scalars(
                select(InterventionRow)
                .join(
                    InterventionOutcomeRow,
                    InterventionOutcomeRow.intervention_id == InterventionRow.intervention_id,
                )
                .where(
                    InterventionRow.person_id == row.person_id,
                    InterventionOutcomeRow.outcome == OutcomeKind.DECLINED.value,
                    self._decline_counts_toward_suppression(),
                )
            ).unique()
            if self._candidate_key_of(intervention) == candidate_key
        )
        if declines < DECLINES_BEFORE_SUPPRESSION:
            return False
        preference = session.scalar(
            select(CandidatePreferenceRow).where(
                CandidatePreferenceRow.person_id == row.person_id,
                CandidatePreferenceRow.candidate_key == candidate_key,
            )
        )
        if preference is not None and preference.suppressed:
            return False
        suppressed_reason = (
            f"Declined {declines} times, so this suggestion is no longer offered. "
            "It can be turned back on at any time."
        )
        if preference is None:
            session.add(
                CandidatePreferenceRow(
                    preference_id=_id("pref"),
                    person_id=row.person_id,
                    candidate_key=candidate_key,
                    suppressed=True,
                    reason=suppressed_reason,
                    actor="system",
                    updated_at=now,
                )
            )
        else:
            preference.suppressed = True
            preference.reason = suppressed_reason
            preference.actor = "system"
            preference.updated_at = now
        session.add(
            self._audit_row(
                row.run_id,
                "candidate_suppressed",
                "system",
                person_id=row.person_id,
                detail={
                    "candidate_key": candidate_key,
                    "declines": declines,
                    "threshold": DECLINES_BEFORE_SUPPRESSION,
                    "reason": suppressed_reason,
                    "recorded_by": actor,
                    "reversible": True,
                    "learning_boundary": (
                        "Deterministic suppression narrows the permitted candidate set; it never "
                        "widens it and it is not a learned score."
                    ),
                },
                at=now,
            )
        )
        session.flush()
        return True

    # ── The follow-through loop ───────────────────────────────────────────────

    def _require_current_run(self, session: Session, row: InterventionRow) -> ScenarioRunRow:
        """The intervention's own run must still be its person's currently active run.

        `reset()` deactivates the previous `ScenarioRunRow` but deliberately leaves its
        `InterventionRow`s (and their consent evidence) in place -- they are the append-only
        history of a prior run, not something a reset may rewrite. Without this check, a stale
        browser tab still holding an `intervention_id` from a dead run could keep recording
        outcomes/follow-through/enjoyment against it: `_consent_active` was being evaluated
        against the intervention's *own* historical `run_id`, which is almost always still
        "active" (nothing in that dead run ever revoked it), so the write would succeed. That
        answer then folds into `_preference_learners` / `_candidate_activity_counts` /
        `_suppress_after_repeated_declines`, all `person_id`-scoped and therefore cross-run -- a
        ghost answer from a run that no longer exists would move live preference state. Every
        caller must therefore evaluate both consent and run-currency against the person's active
        run, never the intervention's own.
        """
        active_run = self._active_run(session, row.person_id)
        if active_run.run_id != row.run_id:
            raise ValueError(
                "This suggestion belongs to a previous run and can no longer be responded to."
            )
        return active_run

    # ── Personal preferences ──────────────────────────────────────────────────

    @staticmethod
    def _candidate_preference_rows(
        session: Session, person_ids: Sequence[str]
    ) -> dict[str, list[CandidatePreferenceRow]]:
        """Every stored candidate preference row of each person, in one query."""
        rows: dict[str, list[CandidatePreferenceRow]] = {person_id: [] for person_id in person_ids}
        if not person_ids:
            return rows
        for row in session.scalars(
            select(CandidatePreferenceRow).where(CandidatePreferenceRow.person_id.in_(person_ids))
        ):
            rows[row.person_id].append(row)
        return rows

    def _known_candidate_keys_for(
        self,
        session: Session,
        person_ids: Sequence[str],
        *,
        catalogue: dict[str, str],
        preference_rows: dict[str, list[CandidatePreferenceRow]],
    ) -> dict[str, dict[str, str]]:
        """`_known_candidate_keys` for every person in `person_ids`: the catalogue, then each
        person's stored preference keys, then their outreach titles -- in that precedence."""
        labels: dict[str, dict[str, str]] = {}
        for person_id in person_ids:
            known = dict(catalogue)
            for row in preference_rows.get(person_id, []):
                known.setdefault(row.candidate_key, _readable_candidate_label(row.candidate_key))
            labels[person_id] = known
        if person_ids:
            for row in session.scalars(
                select(InterventionRow).where(InterventionRow.person_id.in_(person_ids))
            ).unique():
                key = self._candidate_key_of(row)
                labels[row.person_id].setdefault(key, row.title or _readable_candidate_label(key))
        return labels

    def _candidate_preferences_for(
        self,
        session: Session,
        person_ids: Sequence[str],
        *,
        catalogue: dict[str, str],
        preference_rows: dict[str, list[CandidatePreferenceRow]],
    ) -> dict[str, list[CandidatePreference]]:
        """`list_candidate_preferences` for every person in `person_ids`, in a fixed number of
        queries."""
        labels_by_person = self._known_candidate_keys_for(
            session, person_ids, catalogue=catalogue, preference_rows=preference_rows
        )
        counts_by_person = self._candidate_activity_counts_for(session, person_ids)
        preferences_by_person: dict[str, list[CandidatePreference]] = {}
        for person_id in person_ids:
            labels = labels_by_person[person_id]
            counts = counts_by_person[person_id]
            stored = {row.candidate_key: row for row in preference_rows.get(person_id, [])}
            preferences: list[CandidatePreference] = []
            for key in sorted(labels):
                entry = counts.get(key, {})
                row = stored.get(key)
                preferences.append(
                    CandidatePreference(
                        candidate_key=key,
                        label=labels[key],
                        suppressed=bool(row.suppressed) if row else False,
                        suppressed_reason=(row.reason if row and row.suppressed else None),
                        declines=entry.get("declined", 0),
                        times_offered=entry.get("offered", 0),
                        times_accepted=entry.get("accepted", 0),
                        times_completed=entry.get("completed", 0),
                    )
                )
            preferences_by_person[person_id] = preferences
        return preferences_by_person

    def list_candidate_preferences(
        self, *, person_id: str = DEMO_PERSON_ID
    ) -> list[CandidatePreference]:
        with self.sessions() as session:
            self._active_run(session, person_id)
            return self._candidate_preferences_for(
                session,
                [person_id],
                catalogue=self._candidate_catalogue(session),
                preference_rows=self._candidate_preference_rows(session, [person_id]),
            )[person_id]

    @staticmethod
    def _to_programme(row: ProgrammeRow) -> Programme:
        return Programme(
            programme_id=row.programme_id,
            name=row.name,
            venue=row.venue,
            distance_km=row.distance_km,
            next_session=_as_utc(row.next_session),
            accessibility=row.accessibility_json or [],
            evidence_source=row.evidence_source,
        )

    @classmethod
    def _programme_models(
        cls,
        session: Session,
        *,
        current_only: bool = False,
        as_of: datetime | None = None,
    ) -> list[Programme]:
        statement = select(ProgrammeRow).order_by(ProgrammeRow.distance_km)
        if current_only:
            statement = statement.where(ProgrammeRow.valid_until >= (as_of or _utcnow()))
        return [cls._to_programme(row) for row in session.scalars(statement)]

    # ── The user-initiated loop ───────────────────────────────────────────────

    @staticmethod
    def _to_activity_candidate(row: ActivityCandidateRow) -> ActivityCandidate:
        """Read one catalogue row, tolerating columns added after it was written.

        Every JSON list is coalesced. A column added by a later migration is `NULL` on every
        pre-existing row, and handing `None` to a `list[str]` field raises a ValidationError that
        takes the entire listing down -- so a database seeded before the enrichment did not merely
        show activities without detail, it failed to show them at all. An absent list and an empty
        one mean the same thing here: the listing does not say.
        """
        return ActivityCandidate(
            activity_id=row.activity_id,
            source=ActivitySource(row.source),
            integration_status=IntegrationStatus(row.integration_status),
            title=row.title,
            provider=row.provider,
            start_at=_as_utc(row.start_at) if row.start_at is not None else None,
            location=ActivityLocation(
                name=row.location_name,
                address=row.location_address,
                postal_code=row.location_postal_code,
                latitude=row.location_latitude,
                longitude=row.location_longitude,
            ),
            category=row.category,
            activity_type=(
                ActivityType(row.activity_type) if row.activity_type is not None else None
            ),
            activity_families=[
                ActivityFamily(family) for family in row.activity_families_json or []
            ],
            format=Format(row.format) if row.format is not None else None,
            indoor_outdoor=IndoorOutdoor(row.indoor_outdoor),
            social_shape=(SocialPreference(row.social_shape) if row.social_shape else None),
            intensity=ActivityIntensity(row.intensity) if row.intensity is not None else None,
            accessibility_tags=row.accessibility_tags_json or [],
            language_tags=row.language_tags_json or [],
            capacity=row.capacity,
            availability=ActivityAvailability(row.availability),
            price=row.price,
            source_url=row.source_url,
            retrieved_at=_as_utc(row.retrieved_at),
            distance_m=row.distance_m,
            # Read from the row. A row written before the column existed has null here, and only
            # for those does the old inference stand in -- every distance this build knows is a
            # fixed figure on the listing, and no adapter measures a route yet.
            distance_basis=(
                DistanceBasis(row.distance_basis)
                if row.distance_basis is not None
                else (
                    DistanceBasis.LISTING_STATIC
                    if row.distance_m is not None
                    else DistanceBasis.UNKNOWN
                )
            ),
            description=row.description,
            duration_minutes=row.duration_minutes,
            what_to_bring=row.what_to_bring_json or [],
            booking=ActivityBooking(row.booking),
            booking_note=row.booking_note,
            contact_phone=row.contact_phone,
            contact_note=row.contact_note,
            getting_there=row.getting_there_json or [],
            good_to_know=row.good_to_know_json or [],
        )

    @classmethod
    def _activity_candidate_models(cls, session: Session) -> list[ActivityCandidate]:
        rows = session.scalars(
            select(ActivityCandidateRow).order_by(ActivityCandidateRow.activity_id)
        )
        return [cls._to_activity_candidate(row) for row in rows]

    @staticmethod
    def _to_dimension_preference(row: ActivityDimensionPreferenceRow) -> DimensionPreference:
        return DimensionPreference(
            dimension=PreferenceDimension(row.dimension),
            value=row.value,
            strength=row.strength,
            source=row.source,
            confirmed=row.confirmed,
            observations=row.observations,
            updated_at=_as_utc(row.updated_at),
            expires_at=_as_utc(row.expires_at) if row.expires_at is not None else None,
            stated_text=row.stated_text,
            first_observed_at=(
                _as_utc(row.first_observed_at) if row.first_observed_at is not None else None
            ),
            # A row written before the evidence split carries `None` on both sides. The
            # migration backfilled every one of them from `observations` and the sign of
            # `strength`, so `None` here means a row this process wrote before flushing, never a
            # belief whose evidence is unknown; reading it as zero is the honest default.
            positive_evidence=row.positive_evidence or 0.0,
            negative_evidence=row.negative_evidence or 0.0,
            pivot=row.pivot,
            direction=row.direction,
            scope=ClarificationScope(row.scope) if row.scope is not None else None,
            origin_id=row.origin_id,
            superseded_by=row.superseded_by,
        )

    @staticmethod
    def _preference_expired(row: ActivityDimensionPreferenceRow, today: date) -> bool:
        """Expired on the person's own simulated calendar -- the clock everything else in the
        loop keeps -- never the machine's. "Until Friday" means through Friday in their days."""
        return row.expires_at is not None and local_date(_as_utc(row.expires_at)) < today

    @classmethod
    def _preference_inactive(
        cls, row: ActivityDimensionPreferenceRow, today: date, run_id: str
    ) -> bool:
        """Whether a row is absent from what the person currently holds.

        Two independent reasons. Calendar expiry (`expires_at`, checked against the *active
        run's* simulated calendar) applies only to `senior_statement` rows, since
        `apply_decline`/`apply_enjoyment` never set that field. Run-scoping applies to every row
        that is not a *standing* statement -- and "standing" is derived from the fact itself
        (`source == "senior_statement"` and `expires_at is None`), never from `row.run_id` being
        `None`. A `decline_reason`/`inferred` row always carries a `run_id` once written by this
        codebase (every write path stamps one; see `_persist_dimension_preferences`), and so does
        a *time-boxed* `senior_statement` row -- one with `expires_at` set (see
        `_confirm_dimension_preference`). But a row written before `run_id` existed, or backfilled
        for a person with no active run at the time, also has `run_id = None` without being
        standing -- deriving "standing" from `run_id is None` would misread either as exempt from
        run-scoping, reviving the exact bug (a permanent inferred belief, a resurrectable lapsed
        promise) this column exists to close. Such a row is correctly run-scoped and simply never
        matches any real `run_id`, so it reads as inactive until new evidence on its key reattaches
        it to a real run.

        "Avoid until Friday" is a promise about a day on the calendar of the run it was made in,
        not an absolute fact independent of which story is being told; carrying it past a reset
        would resurrect a promise that had already lapsed the moment the calendar rewinds to the
        fixture's anchor day, behind the date it was timeboxed against. See
        `db_models.ActivityDimensionPreferenceRow` for the full rule.
        """
        if row.superseded_by is not None:
            return True
        if cls._preference_expired(row, today):
            return True
        standing = row.source == SENIOR_STATEMENT_SOURCE and row.expires_at is None
        if standing:
            return False
        return row.run_id != run_id

    @classmethod
    def _dimension_rows(
        cls, session: Session, person_id: str, today: date, run_id: str
    ) -> tuple[list[ActivityDimensionPreferenceRow], list[ActivityDimensionPreferenceRow]]:
        """Every preference row this person holds, split into (active, inactive) as of `today`
        and `run_id`.

        The one place that decision is made. Every reader that ranks, explains or lists
        preferences sees only the active rows (`_activity_preferences_model`); the writers see
        both, because an inactive row still occupies its `(dimension, value, source)` key and
        must be started again in place -- run reattached, observations restarted -- rather than
        duplicated or, worse, incremented back to life.

        A **superseded** row is inactive for both of those reasons at once. `forget` stamps
        `superseded_by` rather than deleting, so the audit trail is not rewritten -- but the
        belief is gone as far as every reader is concerned, the Privacy screen shows nothing, and
        the next observation on that key restarts it from zero rather than resurrecting a count
        the person believed they had erased.
        """
        rows = list(
            session.scalars(
                select(ActivityDimensionPreferenceRow)
                .where(ActivityDimensionPreferenceRow.person_id == person_id)
                .order_by(
                    ActivityDimensionPreferenceRow.dimension,
                    ActivityDimensionPreferenceRow.value,
                    ActivityDimensionPreferenceRow.source,
                )
            )
        )
        active = [row for row in rows if not cls._preference_inactive(row, today, run_id)]
        inactive = [row for row in rows if cls._preference_inactive(row, today, run_id)]
        return active, inactive

    @classmethod
    def _activity_preferences_model(
        cls, session: Session, person_id: str, today: date, run_id: str
    ) -> ActivityPreferences:
        """What the person currently holds as of `today` and `run_id`. An expired, superseded or
        stale-run preference is absent, not weak.

        Returns both readings of the same rows in one pass: `dimensions` is the raw record the
        Privacy screen renders and the person edits, and `resolved` is what the ranker reads --
        tiers applied, item-level answers held back until a second agrees, contradictions listed
        rather than scored. Two readings, one query, so they cannot disagree about what is held.

        Goals are folded in at `SourceTier.STATED_GOAL`. `meet_people` and `morning_activity` are
        literal SOCIAL and TIMING statements that lived in a table the ranker could not see.
        """
        _, _, preferences = cls._activity_preferences_parts(session, person_id, today, run_id)
        return preferences

    @classmethod
    def _activity_preferences_parts(
        cls, session: Session, person_id: str, today: date, run_id: str
    ) -> tuple[list[DimensionPreference], list[ActivityGoal], ActivityPreferences]:
        """`_activity_preferences_model`, also returning the raw rows and goals it resolved from.

        A caller that previews a change to what is held (the ranker inspector) must re-resolve
        from these rather than reuse `resolved`, which silently ignores any edit to `dimensions`.
        """
        active, _ = cls._dimension_rows(session, person_id, today, run_id)
        dimensions = [cls._to_dimension_preference(row) for row in active]
        goals = cls._active_goals(session, person_id)
        return (
            dimensions,
            goals,
            ActivityPreferences(
                person_id=person_id,
                dimensions=dimensions,
                resolved=resolve(dimensions, today, run_id, goals=goals),
            ),
        )

    @staticmethod
    def _active_goals(session: Session, person_id: str) -> list[ActivityGoal]:
        """The person's active goals, as models. Read here rather than passed in because every
        caller that ranks already holds a session and none of them should have to remember that a
        goal is also a preference.

        Person-scoped, not run-scoped, because `activity_goals` is: a goal is something the
        person chose about their own life, not something a simulated story taught.
        """
        rows = session.scalars(
            select(ActivityGoalRow)
            .where(
                ActivityGoalRow.person_id == person_id,
                ActivityGoalRow.active.is_(True),
            )
            .order_by(ActivityGoalRow.created_at, ActivityGoalRow.goal_id)
        )
        return [SqlAlchemyRepository._to_goal(row) for row in rows]

    def _persist_dimension_preferences(
        self,
        session: Session,
        person_id: str,
        run_id: str,
        active_rows: list[ActivityDimensionPreferenceRow],
        expired_rows: list[ActivityDimensionPreferenceRow],
        existing: list[DimensionPreference],
        updated: list[DimensionPreference],
        now: datetime,
    ) -> list[DimensionPreference]:
        """Write back what `apply_decline` / `apply_enjoyment` returned; return what changed.

        Keyed on `(dimension, value, source)` -- the table's unique key. The learners keep their
        evidence on separate source tiers on purpose (see `preferences.py`), and the old
        `(dimension, value)` key let a decline silently overwrite an enjoyment row's source and
        count the moment both named the same value. `apply_decline`/`apply_enjoyment` only ever
        produce `decline_reason`/`inferred` rows -- never `senior_statement`, which is written
        exclusively by `_confirm_dimension_preference` -- so every row this method touches is
        run-scoped and gets stamped with `run_id`.

        An inactive row on the same key -- calendar-expired, or (see `_dimension_rows`) tagged
        with a run that is no longer active -- is started again in place: its count comes from
        `updated` (which never saw it, so the count is one), its expiry is cleared, its run is
        reattached to the current one, and its first-observed stamp is reset -- a preference that
        lapsed and returned is a new observation, not a resurrection of the old total.
        """
        by_key = {(row.dimension, row.value, row.source): row for row in active_rows}
        expired_by_key = {(row.dimension, row.value, row.source): row for row in expired_rows}
        existing_by_key = {(p.dimension, p.value, p.source): p for p in existing}
        changed: list[DimensionPreference] = []
        for preference in updated:
            key = (preference.dimension.value, preference.value, preference.source)
            if existing_by_key.get((preference.dimension, preference.value, preference.source)) == (
                preference
            ):
                continue
            row = by_key.get(key)
            if row is None and key in expired_by_key:
                row = expired_by_key[key]
                row.expires_at = None
                row.first_observed_at = now
                row.run_id = run_id
                # A row the person retracted, or one a statement consumed, is started again from
                # nothing. Clearing the stamp is what makes the restart a *new* belief rather
                # than the return of one they believed they had erased.
                row.superseded_by = None
            if row is None:
                row = ActivityDimensionPreferenceRow(
                    preference_id=_id("dimpref"),
                    person_id=person_id,
                    dimension=preference.dimension.value,
                    value=preference.value,
                    strength=preference.strength,
                    source=preference.source,
                    confirmed=preference.confirmed,
                    observations=preference.observations,
                    updated_at=preference.updated_at,
                    first_observed_at=now,
                    run_id=run_id,
                )
                session.add(row)
            else:
                row.strength = preference.strength
                row.source = preference.source
                row.confirmed = preference.confirmed
                row.observations = preference.observations
                row.updated_at = preference.updated_at
            # The evidence split, the ordinal line and the scope travel together on every write
            # path, new row or existing: `strength` is derived from the first of these, so a row
            # whose counts were not written back would resolve to a strength its own evidence
            # does not support the next time it is read.
            row.positive_evidence = preference.positive_evidence
            row.negative_evidence = preference.negative_evidence
            row.pivot = preference.pivot
            row.direction = preference.direction
            row.scope = preference.scope.value if preference.scope is not None else None
            row.origin_id = preference.origin_id
            # Stamped on every write path rather than relied on to already hold: that is what
            # actually backs the docstring's claim that every row this method touches belongs to
            # the current run. A legacy row can never reach here (a `None` or stale `run_id` reads
            # as inactive; see `_preference_inactive`), so this never re-associates one wrongly.
            row.run_id = run_id
            changed.append(
                preference.model_copy(
                    update={"first_observed_at": _as_utc(row.first_observed_at or now)}
                )
            )
        return changed

    # ── The senior answers a search result ────────────────────────────────────

    @staticmethod
    def _activity_engagement(
        session: Session, person_id: str, run_id: str
    ) -> dict[str, ActivityEngagement]:
        """Per listing, what this person has said and done about it, within the active run.

        Scoped to the run rather than the person on purpose: a demo reset rewinds the simulated
        calendar to the fixture's anchor day, and a "not for me" recorded on a later simulated
        day of an earlier run would then sit in the new run's future -- a cooldown that never
        lapses. The rows themselves stay (append-only); they simply belong to the story that
        recorded them.

        One *scored* response per `(activity_id, response, day)`. Every tap is still stored and
        still audited -- a person tapping twice is a fact, and the rows are append-only -- but a
        stuck button, a browser retry or a bored demo operator must not be able to out-weigh a
        real outing: three taps of "I'm interested" used to contribute the whole `engagement`
        weight, more than actually going (audit D §8), and repeated declines compounded the
        `repetition` hold the same way. Counting the person's answer for a day once is what makes
        the signal a fact about them rather than about their thumb. `went` / `did_not_go` /
        `enjoyed` need no such rule: those come from plan rows, one report each, enforced already.

        **Series-scoped, with a per-session override.** A programme with sessions on Monday,
        Wednesday and Friday is three `activity_id`s and one thing to go to. Keyed per session,
        "not for me" on Monday's chair class left Wednesday's and Friday's untouched and the
        person was shown the identical class twice more that week -- the cooldown was real and
        reached nothing. Counts therefore roll up to `series_key` and apply to every session of
        the series; a session the person has answered *themselves* keeps its own most recent word
        on the cooldown, so an "interested" on Friday is not overruled by Monday's decline.

        A verdict of "not for me" after actually going is counted (`not_enjoyed`) and scores
        against the listing. It used to be counted nowhere at all -- only `enjoyed` had a field --
        so someone who went and disliked it saw the same card promoted back up with "You went to
        this one before." printed on it as a reason it suited them.
        """
        offers, follow_through, verdicts = SqlAlchemyRepository._engagement_rows(
            session, person_id, run_id
        )
        counted = count_engagement(offers, follow_through, verdicts)
        if not counted.counts:
            return {}
        # Every session of every series the person has answered anything about. Read in one
        # query rather than per listing: the catalogue is small, and a per-listing lookup inside
        # the ranker would be a query per candidate per search. Keyed by
        # `activity_search.series_keys_for`, the one definition of "the same programme" the
        # ranker, the dedupe and `RankedActivity.series_key` share -- never a copy of it, which
        # is how this read and the search path used to be able to disagree.
        series_keys = series_keys_for(SqlAlchemyRepository._activity_candidate_models(session))
        return engagement_by_series(
            counted.counts, counted.last_declined, counted.answered, series_keys
        )

    @staticmethod
    def _engagement_rows(
        session: Session, person_id: str, run_id: str
    ) -> tuple[list[tuple[str, str, date]], list[tuple[str, str]], list[tuple[str, str]]]:
        """The raw rows `_activity_engagement` counts: search-card answers in the order they were
        recorded, planned follow-through reports, and planned enjoyment verdicts -- all scoped to
        the run. Counting them is `activity_search.count_engagement`'s job, not this read's."""
        offers = [
            (activity_id, response, day)
            for activity_id, response, day in session.execute(
                select(
                    ActivityOfferResponseRow.activity_id,
                    ActivityOfferResponseRow.response,
                    ActivityOfferResponseRow.recorded_on_day,
                )
                .where(
                    ActivityOfferResponseRow.person_id == person_id,
                    ActivityOfferResponseRow.run_id == run_id,
                )
                .order_by(
                    ActivityOfferResponseRow.recorded_at, ActivityOfferResponseRow.response_id
                )
            )
        ]
        follow_through = [
            (activity_id, report)
            for activity_id, report in session.execute(
                select(WeekPlanEntryRow.activity_id, PlanFollowThroughRow.follow_through)
                .join(
                    PlanFollowThroughRow, PlanFollowThroughRow.plan_id == WeekPlanEntryRow.plan_id
                )
                .where(WeekPlanEntryRow.person_id == person_id, WeekPlanEntryRow.run_id == run_id)
            )
        ]
        verdicts = [
            (activity_id, verdict)
            for activity_id, verdict in session.execute(
                select(WeekPlanEntryRow.activity_id, PlanEnjoymentRow.enjoyment)
                .join(PlanEnjoymentRow, PlanEnjoymentRow.plan_id == WeekPlanEntryRow.plan_id)
                .where(
                    WeekPlanEntryRow.person_id == person_id,
                    WeekPlanEntryRow.run_id == run_id,
                )
            )
        ]
        return offers, follow_through, verdicts

    @staticmethod
    def _attended_series(
        session: Session, person_id: str, run_id: str
    ) -> list[ActivityHistoryFact]:
        """The programmes this person has actually been to in this run, one entry each.

        Read from the plan rows themselves rather than from `_activity_engagement`: that map hands
        every session of a touched programme the programme's totals, which is what makes a
        cooldown reach the whole class -- and what made the world model state, of one Wednesday
        attendance at a Monday/Wednesday/Friday class, three separate "You went to ..." facts,
        each `EXPLICIT`, `HIGH` and confirmed, for two sessions the person never attended.

        Only a session carrying a `went` report of its own is counted here; the counts are then
        rolled up to the programme, so the person is told the one thing that is true -- that they
        have been to it, and how often. `enjoyed` is read off the same plans (an enjoyment row
        cannot exist without a `went` report; `record_planned_enjoyment` enforces it).

        Run-scoped like every other read of this table (ADR 0004): a demo reset rewinds the
        simulated calendar, and a dead run's outing is not something this run's story includes.
        """
        return SqlAlchemyRepository._attended_series_for(session, [(person_id, run_id)])[run_id]

    @staticmethod
    def _attended_series_for(
        session: Session, people_runs: Sequence[tuple[str, str]]
    ) -> dict[str, list[ActivityHistoryFact]]:
        """`_attended_series` for every `(person_id, run_id)`, keyed by run, in at most three
        queries whatever the number of runs."""
        result: dict[str, list[ActivityHistoryFact]] = {run_id: [] for _, run_id in people_runs}
        if not people_runs:
            return result
        person_of_run = {run_id: person_id for person_id, run_id in people_runs}
        run_ids = list(result)
        attended_by_run: dict[str, list[tuple[str, str]]] = {}
        for activity_id, plan_id, run_id, person_id in session.execute(
            select(
                WeekPlanEntryRow.activity_id,
                WeekPlanEntryRow.plan_id,
                WeekPlanEntryRow.run_id,
                WeekPlanEntryRow.person_id,
            )
            .join(PlanFollowThroughRow, PlanFollowThroughRow.plan_id == WeekPlanEntryRow.plan_id)
            .where(
                WeekPlanEntryRow.run_id.in_(run_ids),
                PlanFollowThroughRow.follow_through == PlannedFollowThrough.WENT.value,
            )
        ):
            if person_of_run.get(run_id) != person_id:
                continue
            attended_by_run.setdefault(run_id, []).append((activity_id, plan_id))
        if not attended_by_run:
            return result
        enjoyed_plans: dict[str, set[str]] = {}
        for plan_id, run_id, person_id in session.execute(
            select(
                PlanEnjoymentRow.plan_id, PlanEnjoymentRow.run_id, PlanEnjoymentRow.person_id
            ).where(
                PlanEnjoymentRow.run_id.in_(list(attended_by_run)),
                PlanEnjoymentRow.enjoyment == Enjoyment.ENJOYED.value,
            )
        ):
            if person_of_run.get(run_id) == person_id:
                enjoyed_plans.setdefault(run_id, set()).add(plan_id)
        listings = {
            row.activity_id: row
            for row in session.scalars(
                select(ActivityCandidateRow).where(
                    ActivityCandidateRow.activity_id.in_(
                        {
                            listing
                            for attended in attended_by_run.values()
                            for listing, _ in attended
                        }
                    )
                )
            )
        }
        for run_id, attended in attended_by_run.items():
            enjoyed_here = enjoyed_plans.get(run_id, set())
            titles: dict[tuple[str, str], str] = {}
            went: dict[tuple[str, str], int] = {}
            enjoyed: dict[tuple[str, str], int] = {}
            for activity_id, plan_id in attended:
                listing = listings.get(activity_id)
                # `series_identity`, the ranker's own definition of "the same programme", and its
                # fallback: a session the catalogue has no row for -- there is none in practice --
                # stands as its own programme rather than being dropped.
                key = (
                    series_identity(listing) if listing is not None else (activity_id, activity_id)
                )
                titles.setdefault(key, listing.title if listing is not None else activity_id)
                went[key] = went.get(key, 0) + 1
                if plan_id in enjoyed_here:
                    enjoyed[key] = enjoyed.get(key, 0) + 1
            result[run_id] = [
                ActivityHistoryFact(
                    # "|" is only the world model's fact-key encoding (`activity:{provider|title}`),
                    # kept stable for facts already shown; the ranker's opaque key is `series_key`.
                    series_key="|".join(key),
                    title=titles[key],
                    went=went[key],
                    enjoyed=enjoyed.get(key, 0),
                )
                for key in sorted(went)
            ]
        return result

    # ── Goals and the week ─────────────────────────────────────────────────────

    _GOAL_LABELS: dict[GoalKind, str] = {
        GoalKind.GET_OUT_MORE: "Get out and about more",
        GoalKind.MEET_PEOPLE: "Spend more time with other people",
        GoalKind.MORNING_ACTIVITY: "Do something active in the mornings",
        GoalKind.LESS_TRAVEL: "Stick to things closer to home",
    }

    @classmethod
    def _goal_text(cls, kind: GoalKind, target_per_week: int | None) -> str:
        label = cls._GOAL_LABELS[kind]
        if target_per_week is None:
            return label
        times = "once a week" if target_per_week == 1 else f"{target_per_week} times a week"
        return f"{label}, {times}"

    @classmethod
    def _to_goal(cls, row: ActivityGoalRow) -> ActivityGoal:
        kind = GoalKind(row.kind)
        return ActivityGoal(
            goal_id=row.goal_id,
            kind=kind,
            text=cls._goal_text(kind, row.target_per_week),
            target_per_week=row.target_per_week,
            active=row.active,
            created_at=_as_utc(row.created_at),
        )

    # ── The personal world model ──────────────────────────────────────────────

    def _outreach_responses(
        self, session: Session, person_id: str, run_id: str
    ) -> list[OutreachResponseFact]:
        """What the person did with each kind of outreach *in this run*, outcome by outcome.

        Deliberately not `_candidate_activity_counts`, for two reasons the world model cannot
        live without and its other callers do not want.

        **The breakdown.** That map keeps `offered`/`accepted`/`declined`/`followed`/`completed`
        and nothing else, so "not accepted" swallowed an explicit "maybe later", a response
        window that closed on silence, and an offer sitting unanswered on the person's home page
        alike -- and the world model narrated all three as *"passed on it"*. Every one of those
        is a different fact, so every one of them is counted apart here, along with the person's
        own decline reason (the most recent one, resolved through `_latest_outcome_ids_subquery`
        like every other reader of this append-only table).

        **The run.** Run-scoped like `_attended_series` and the plan reads (ADR 0004): a demo
        reset starts the story over, and the previous run's offers are not this run's memory --
        read person-scoped, a fresh demo opened with the last operator's outreach already in the
        senior's own "what Care+ remembers" page. Nothing is deleted; the rows stay exactly
        where they are, and the person-level learner (`_preference_learners`) still reads all of
        them, because a posterior is about the person and not about one demo run.
        """
        return self._outreach_responses_for(
            session,
            [(person_id, run_id)],
            {person_id: self._known_candidate_keys(session, person_id)},
        )[run_id]

    def _outreach_responses_for(
        self,
        session: Session,
        people_runs: Sequence[tuple[str, str]],
        labels_by_person: dict[str, dict[str, str]],
    ) -> dict[str, list[OutreachResponseFact]]:
        """`_outreach_responses` for every `(person_id, run_id)` in one query, keyed by run."""
        tallies_by_run: dict[str, dict[str, _OutreachTally]] = {
            run_id: {} for _, run_id in people_runs
        }
        person_of_run = {run_id: person_id for person_id, run_id in people_runs}
        rows = (
            session.execute(
                select(
                    InterventionRow,
                    InterventionOutcomeRow.outcome,
                    InterventionOutcomeRow.reason,
                    InterventionOutcomeRow.recorded_at,
                    InterventionFollowThroughRow.follow_through,
                )
                .select_from(InterventionRow)
                .outerjoin(
                    InterventionOutcomeRow,
                    and_(
                        InterventionOutcomeRow.intervention_id == InterventionRow.intervention_id,
                        InterventionOutcomeRow.outcome_id.in_(self._latest_outcome_ids_subquery()),
                    ),
                )
                .outerjoin(
                    InterventionFollowThroughRow,
                    InterventionFollowThroughRow.intervention_id == InterventionRow.intervention_id,
                )
                .where(InterventionRow.run_id.in_(list(tallies_by_run)))
            )
            if people_runs
            else []
        )
        for intervention, outcome, reason, recorded_at, follow_through in rows:
            if person_of_run.get(intervention.run_id) != intervention.person_id:
                continue
            tallies = tallies_by_run[intervention.run_id]
            key = self._candidate_key_of(intervention)
            tally = tallies.setdefault(key, _OutreachTally())
            tally.offered += 1
            if outcome == OutcomeKind.ACCEPTED.value:
                tally.accepted += 1
            elif outcome == OutcomeKind.DECLINED.value:
                tally.declined += 1
                # The most recent reason the person gave, and only if they gave one: the reason
                # sheet is always skippable, so `None` is the common answer, and it is never
                # backfilled from an older decline of the same thing.
                at = _as_utc(recorded_at) if recorded_at is not None else None
                if reason is not None and (
                    tally.decline_reason_at is None
                    or (at is not None and at >= tally.decline_reason_at)
                ):
                    tally.decline_reason = _decline_reason_or_none(reason)
                    tally.decline_reason_at = at
            elif outcome == OutcomeKind.DEFERRED.value:
                tally.deferred += 1
            elif outcome == OutcomeKind.NO_RESPONSE.value:
                tally.no_response += 1
            if follow_through == FollowThrough.COMPLETED.value:
                tally.completed += 1
        return {
            run_id: [
                OutreachResponseFact(
                    candidate_key=key,
                    label=labels_by_person.get(person_of_run[run_id], {}).get(
                        key, _readable_candidate_label(key)
                    ),
                    offered=tally.offered,
                    accepted=tally.accepted,
                    completed=tally.completed,
                    declined=tally.declined,
                    deferred=tally.deferred,
                    no_response=tally.no_response,
                    decline_reason=tally.decline_reason,
                )
                for key, tally in sorted(tallies.items())
            ]
            for run_id, tallies in tallies_by_run.items()
        }

    def _world_models(
        self,
        session: Session,
        runs: Sequence[ScenarioRunRow],
        reads: dict[str, _RunReads] | None = None,
        *,
        catalogue: dict[str, str] | None = None,
        preference_rows: dict[str, list[CandidatePreferenceRow]] | None = None,
        skip_unreadable: bool = False,
    ) -> dict[str, PersonWorldModel]:
        """`world_model` for every run in `runs`, keyed by run, in a fixed number of queries.

        `reads`, `catalogue` and `preference_rows` are reused when the caller already holds them.
        A run whose person cannot be evaluated raises as `world_model` does, unless
        `skip_unreadable` is set, in which case it is left out -- the caseload reads skip a run with
        no readings the same way.
        """
        if reads is None:
            reads = self._load_run_reads(session, runs)
        states: dict[str, PersonState] = {}
        for run in runs:
            try:
                states[run.run_id] = self._person_state(session, run, reads[run.run_id])
            except (KeyError, RuntimeError):
                if not skip_unreadable:
                    raise
        evaluated = [run for run in runs if run.run_id in states]
        if not evaluated:
            return {}
        person_ids = list(dict.fromkeys(run.person_id for run in evaluated))
        run_ids = [run.run_id for run in evaluated]
        people_runs = [(run.person_id, run.run_id) for run in evaluated]
        if catalogue is None:
            catalogue = self._candidate_catalogue(session)
        if preference_rows is None:
            preference_rows = self._candidate_preference_rows(session, person_ids)

        dimension_rows: dict[str, list[ActivityDimensionPreferenceRow]] = {
            person_id: [] for person_id in person_ids
        }
        for row in session.scalars(
            select(ActivityDimensionPreferenceRow)
            .where(ActivityDimensionPreferenceRow.person_id.in_(person_ids))
            .order_by(
                ActivityDimensionPreferenceRow.dimension,
                ActivityDimensionPreferenceRow.value,
                ActivityDimensionPreferenceRow.source,
            )
        ):
            dimension_rows[row.person_id].append(row)

        # The simulated day each answer was about, for rows written before
        # `ContextQuestionAnswerRow.answered_on_day` existed: recovered from the audit event
        # that recorded the answer. Rows written since carry the day on the row itself and are
        # read from there below, so this scan is a fallback for legacy rows only and can be
        # deleted once no database still holds one -- and it is not run at all when no answer
        # needs it. An answer is a fact about one day; the world model bounds it to that day.
        answered_on: dict[str, dict[str, date]] = {run_id: {} for run_id in run_ids}
        legacy_runs = [
            run_id
            for run_id in run_ids
            if any(row.answered_on_day is None for row in reads[run_id].answers)
        ]
        if legacy_runs:
            for event in session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id.in_(legacy_runs),
                    AuditEventRow.event_type == "context_question_answered",
                )
            ):
                detail = event.detail_json or {}
                answer_id = detail.get("answer_evidence_id")
                day_text = detail.get("day")
                if isinstance(answer_id, str) and isinstance(day_text, str) and event.run_id:
                    answered_on[event.run_id][answer_id] = date.fromisoformat(day_text)

        active_goals: dict[str, list[ActivityGoal]] = {person_id: [] for person_id in person_ids}
        for row in session.scalars(
            select(ActivityGoalRow)
            .where(
                ActivityGoalRow.person_id.in_(person_ids),
                ActivityGoalRow.active.is_(True),
            )
            .order_by(ActivityGoalRow.created_at, ActivityGoalRow.goal_id)
        ):
            active_goals[row.person_id].append(self._to_goal(row))
        all_goals: dict[str, list[ActivityGoal]] = {person_id: [] for person_id in person_ids}
        for row in session.scalars(
            select(ActivityGoalRow).where(ActivityGoalRow.person_id.in_(person_ids))
        ):
            all_goals[row.person_id].append(self._to_goal(row))

        mutes = self._candidate_preferences_for(
            session, person_ids, catalogue=catalogue, preference_rows=preference_rows
        )
        labels = self._known_candidate_keys_for(
            session, person_ids, catalogue=catalogue, preference_rows=preference_rows
        )
        outreach_responses = self._outreach_responses_for(session, people_runs, labels)
        activity_history = self._attended_series_for(session, people_runs)
        # No real senior response timestamps exist to read until an authorised adapter does
        # (`ADAPTER_MODE=fixture` is every build today, including the shared demo): a
        # simulated run can advance a week of days inside a real minute, so the response
        # hour would measure the operator's clicking rather than a routine, and the fact is
        # dropped entirely rather than shown with a caveat nobody would read.
        is_simulated_run = self.settings.adapter_mode == "fixture"

        models: dict[str, PersonWorldModel] = {}
        for run in evaluated:
            person_id = run.person_id
            run_reads = reads[run.run_id]
            state = states[run.run_id]
            profile = persona_profile(person_id)
            consent = run_reads.consents[0] if run_reads.consents else None
            latest_confirmation = run_reads.latest_confirmation
            confirmed_reference = (
                ConfirmedReferenceFact(
                    steps=latest_confirmation.new_reference_steps,
                    confirmation_id=latest_confirmation.confirmation_id,
                    decided_on_day=latest_confirmation.decided_on_day,
                    decided_at=_as_utc(latest_confirmation.decided_at),
                )
                if latest_confirmation is not None
                and latest_confirmation.decision == BaselineConfirmationDecision.CONFIRM.value
                and latest_confirmation.new_reference_steps is not None
                else None
            )
            rows = dimension_rows[person_id]
            active_rows = [
                row
                for row in rows
                if not self._preference_inactive(row, run.current_day, run.run_id)
            ]
            expired_rows = [
                row for row in rows if self._preference_inactive(row, run.current_day, run.run_id)
            ]
            preferences = [self._to_dimension_preference(row) for row in active_rows]
            answers = [
                ContextAnswerFact(
                    question_id=row.question_id,
                    value=row.value,
                    label=CONTEXT_ANSWER_LABELS.get(row.value, row.value),
                    answer_id=row.answer_id,
                    answered_at=_as_utc(row.answered_at),
                    answered_on_day=(
                        row.answered_on_day or answered_on[run.run_id].get(row.answer_id)
                    ),
                )
                for row in run_reads.answers
            ]
            typical_hour, response_hours = self._typical_response_hour_from(
                run_reads.outcomes, run.run_id
            )
            inputs = WorldModelInputs(
                person_id=person_id,
                display_name=state.display_name,
                as_of_day=run.current_day,
                as_of=_utcnow(),
                preferred_language=state.preferred_language,
                age=profile.age,
                background=profile.context_note,
                # Every curated persona is synthetic demo data and says so; a person who exists
                # only because someone registered them carries no fixture biography at all.
                is_synthetic_profile=person_id in DEMO_PERSONAS,
                consent_active=state.consent_active,
                consent_evidence_id=consent.evidence_id if consent else None,
                consent_recorded_at=_as_utc(consent.recorded_at) if consent else None,
                consent_source=consent.source if consent else None,
                baseline=state.baseline,
                baseline_observed_at=datetime.combine(state.current_day, time(hour=12), tzinfo=UTC),
                confirmed_reference=confirmed_reference,
                preferences=preferences,
                # The same rows, resolved: tiers applied, retracted and consumed rows gone,
                # contradictions already worked out. The world model used to derive its own
                # contradictions by pairing rows itself, which is how "That's right" came to
                # manufacture a disagreement with the very belief the person had just agreed
                # with -- the statement was a second row, and nothing had consumed the first.
                # Resolved exactly as `_activity_preferences_model` resolves them.
                resolved=resolve(
                    preferences, run.current_day, run.run_id, goals=active_goals[person_id]
                ),
                # `expired_rows` (the inactive rows) is broader than this field's name: it
                # also holds a `decline_reason`/`inferred` or time-boxed row that is merely
                # run-scoped to a run that is no longer active (ADR 0004), which is not the same
                # fact as having lapsed on the calendar and would make this count grow with every
                # reset if included. Kept to calendar expiry only, exactly what it counted before
                # run-scoping existed -- a stale-run row is simply absent, not shown as "expired".
                expired_preferences=sum(
                    1 for row in expired_rows if self._preference_expired(row, run.current_day)
                ),
                mutes=mutes[person_id],
                goals=all_goals[person_id],
                context_answers=answers,
                disputed_days=sum(
                    1
                    for dispute in run_reads.disputes
                    if dispute.run_id == run.run_id and dispute.accurate is False
                ),
                typical_response_hour=typical_hour,
                typical_response_hour_sample=len(response_hours),
                is_simulated_run=is_simulated_run,
                # Outcome by outcome and scoped to this run -- never "accepted or not", which
                # told the person they had "passed on" an offer still open on their home page,
                # and never person-scoped, which carried the previous demo's offers into a fresh
                # one. See `_outreach_responses`.
                outreach_responses=outreach_responses[run.run_id],
                # Attendance read per session and rolled up to the programme, *not* the ranking
                # roll-up (`_activity_engagement`), which hands every session of a touched
                # programme the programme's totals: read that way, one Wednesday outing stated
                # three "You went to ..." facts, two of them about sessions nobody attended.
                activity_history=activity_history[run.run_id],
            )
            models[run.run_id] = build_world_model(inputs)
        return models

    def _planned_model(self, session: Session, row: WeekPlanEntryRow) -> PlannedActivity | None:
        """One `WeekPlanEntryRow` as the replanning module wants it, or `None` when the listing
        behind it has gone from the catalogue entirely (there is nothing to describe then)."""
        activity_row = session.get(ActivityCandidateRow, row.activity_id)
        if activity_row is None:
            return None
        return PlannedActivity(
            plan_id=row.plan_id,
            day=row.day,
            activity=self._to_activity_candidate(activity_row),
            origin=row.origin,
            replaced_reason=row.replaced_reason,
        )

    def _expire_open_replan_offers(
        self, session: Session, run: ScenarioRunRow, today: date, now: datetime
    ) -> list[str]:
        """Close every open offer whose day has come and gone.

        An offer is a question about a specific day; once that day is past, leaving it open would
        keep asking about something that can no longer be answered. `no_alternative` rather than
        `expired` when nothing was ever offered alongside it, because the two say different things
        about why nothing happened and only one of them is about the person.
        """
        expired: list[str] = []
        rows = session.scalars(
            select(ReplanOfferRow)
            .join(WeekPlanEntryRow, WeekPlanEntryRow.plan_id == ReplanOfferRow.plan_id)
            .where(
                ReplanOfferRow.run_id == run.run_id,
                ReplanOfferRow.resolution.is_(None),
                WeekPlanEntryRow.day < today,
            )
            .order_by(ReplanOfferRow.offered_at, ReplanOfferRow.offer_id)
        )
        for row in rows:
            row.resolution = (
                ReplanResolution.EXPIRED.value
                if row.alternative_activity_id
                else ReplanResolution.NO_ALTERNATIVE.value
            )
            row.resolved_at = now
            expired.append(row.offer_id)
        return expired

    def _record_replan_offers(
        self,
        session: Session,
        run: ScenarioRunRow,
        today: date,
        context: ContextSignal,
        now: datetime,
    ) -> list[ReplanOfferRow]:
        """One offer per plan the world has just changed under, written where the change was.

        Detection is `replanning.notices_for`, unchanged and still pure -- this method only
        decides what to persist. An offer is written at most once per `(run, plan, reason)`: a
        notice the person has already answered must not come back on the next simulated day, which
        is precisely what made declining meaningless when the notice was recomputed on every read
        (audit F finding 8).
        """
        rows = session.scalars(
            select(WeekPlanEntryRow)
            .where(
                # The active run's own plans, the same rule `_week_plan_model` reads by: an offer
                # about a dead run's outing is an offer the person cannot see and cannot act on.
                WeekPlanEntryRow.run_id == run.run_id,
                WeekPlanEntryRow.person_id == run.person_id,
                WeekPlanEntryRow.day >= today,
                WeekPlanEntryRow.replaced_reason.is_(None),
            )
            .order_by(WeekPlanEntryRow.day, WeekPlanEntryRow.plan_id)
        )
        planned = [model for row in rows if (model := self._planned_model(session, row))]
        if not planned:
            return []
        notices = notices_for(
            planned,
            self._activity_candidate_models(session),
            self._activity_preferences_model(session, run.person_id, today, run.run_id),
            today=today,
            rainy=context.rainy,
            rain_until=context.weather_valid_until if context.weather_source == "live" else None,
            engagement=self._activity_engagement(session, run.person_id, run.run_id),
        )
        written: list[ReplanOfferRow] = []
        for notice in notices:
            already = session.scalar(
                select(ReplanOfferRow).where(
                    ReplanOfferRow.run_id == run.run_id,
                    ReplanOfferRow.plan_id == notice.plan_id,
                    ReplanOfferRow.reason == notice.reason_code.value,
                )
            )
            if already is not None:
                continue
            alternative_id = (
                notice.alternative.candidate.activity_id if notice.alternative else None
            )
            offer_row = ReplanOfferRow(
                offer_id=_id("offer"),
                run_id=run.run_id,
                person_id=run.person_id,
                plan_id=notice.plan_id,
                reason=notice.reason_code.value,
                alternative_activity_id=alternative_id,
                offered_at=now,
                resolved_at=None,
                resolution=None,
            )
            session.add(offer_row)
            session.flush()
            session.add(
                self._audit_row(
                    run.run_id,
                    "replan_offered",
                    "silverloop",
                    person_id=run.person_id,
                    detail={
                        "offer_id": offer_row.offer_id,
                        "plan_id": notice.plan_id,
                        "activity_id": next(
                            entry.activity.activity_id
                            for entry in planned
                            if entry.plan_id == notice.plan_id
                        ),
                        "reason_code": notice.reason_code.value,
                        "alternative_activity_id": alternative_id,
                        # Deterministic, every time: the same `filter_candidates`/
                        # `rank_candidates` pair the search uses. No model ranks a replacement,
                        # and none may add one.
                        "alternative_rank_basis": "deterministic",
                        "learning_boundary": (
                            "An offer is a proposal. Nothing is replaced until the person says so."
                        ),
                    },
                    at=now,
                )
            )
            written.append(offer_row)
        session.flush()
        return written

    @staticmethod
    def _evidence_facts(
        session: Session, evidence_ids: Iterable[str]
    ) -> dict[str, tuple[datetime, str]]:
        """`(observed_at, decision)` for each decision evidence id that exists, in one query."""
        ids = sorted(set(evidence_ids))
        if not ids:
            return {}
        return {
            evidence_id: (observed_at, decision)
            for evidence_id, observed_at, decision in session.execute(
                select(
                    DecisionEvidenceRow.evidence_id,
                    DecisionEvidenceRow.observed_at,
                    DecisionEvidenceRow.decision,
                ).where(DecisionEvidenceRow.evidence_id.in_(ids))
            )
        }

    @staticmethod
    def _case_clock_from(
        row: ReviewCaseRow, latest_observed: datetime | None
    ) -> tuple[date | None, int | None, date | None]:
        """`(opened_day, days_in_review, review_by_day)`, all in simulated days.

        `opened_day` is stored. The other two are derived, because both are functions of it and a
        second stored copy could disagree with the first:

        - `days_in_review` counts to the day of the reading that most recently refreshed the case
          (`decision_evidence_id`, rewritten on every refresh), not to today. A case nothing has
          re-confirmed has not quietly aged. Inclusive of the opening day, so a case on screen
          right now never reads "0 days".
        - `review_by_day` is `opened_day + CASE_REVIEW_WINDOW_DAYS`, and only while the case is
          still unresolved -- once a human has answered, there is nothing left to re-surface.

        All three are `None` for a case opened before the clock existed. That is reported as
        "not recorded" rather than back-filled from a wall clock, which would invent a day the
        simulation never ran.

        `latest_observed` is the `observed_at` of the case's current `decision_evidence_id`, or
        `None` if that evidence does not exist; callers read it for every case at once
        (`_evidence_facts`).
        """
        opened_day = row.opened_day
        if opened_day is None:
            return None, None, None
        last_refreshed_day = (
            _as_utc(latest_observed).date() if latest_observed is not None else opened_day
        )
        days_in_review = max(1, (last_refreshed_day - opened_day).days + 1)
        review_by_day = (
            None
            if row.status == CaseStatus.RESOLVED.value
            else opened_day + timedelta(days=CASE_REVIEW_WINDOW_DAYS)
        )
        return opened_day, days_in_review, review_by_day

    @staticmethod
    def _prior_outreach(
        reads: _RunReads,
        opened_day: date | None,
        latest_outcomes: dict[str, InterventionOutcomeRow],
        follow_through: dict[str, str],
    ) -> list[PriorOutreach]:
        """Everything Care+ offered this person in this run, up to the day the case opened.

        Oldest first: this is a story, and a story told backwards is a list. Bounded by
        `opened_day` rather than by "now" so the card answers "what had been tried when a human
        was asked for?" -- outreach that happened afterwards belongs to whatever the coordinator
        decided, not to the reason the case exists. A case with no recorded opening day (one that
        predates the clock) reports the whole run, which is the widest honest answer.

        Pure: the run's interventions, their latest outcomes and their follow-through reports are
        read for every case at once by `_to_cases` (`_load_run_interventions`).
        """
        steps: list[PriorOutreach] = []
        for item in reads.interventions:
            day = reads.outreach_day(item)
            if opened_day is not None and day > opened_day:
                continue
            outcome_row = latest_outcomes.get(item.intervention_id)
            steps.append(
                PriorOutreach(
                    intervention_id=item.intervention_id,
                    decision=Decision(item.decision),
                    title=item.title,
                    day=day,
                    outcome=outcome_row.outcome if outcome_row else None,
                    follow_through=follow_through.get(item.intervention_id),
                )
            )
        steps.sort(key=lambda step: (step.day, step.intervention_id))
        return steps

    @staticmethod
    def _load_run_outcomes(session: Session, reads: dict[str, _RunReads]) -> None:
        """Every outcome row of the runs' interventions, latest first, in one query. Skipped when
        no run has an intervention, since there can then be no outcome either."""
        if not any(entry.interventions for entry in reads.values()):
            return
        for outcome, intervention_run_id in session.execute(
            select(InterventionOutcomeRow, InterventionRow.run_id)
            .join(
                InterventionRow,
                InterventionRow.intervention_id == InterventionOutcomeRow.intervention_id,
            )
            .where(InterventionRow.run_id.in_(list(reads)))
            .order_by(
                InterventionOutcomeRow.recorded_at.desc(),
                InterventionOutcomeRow.outcome_id.desc(),
            )
        ):
            reads[intervention_run_id].outcomes.append(outcome)

    def _to_case(self, session: Session, row: ReviewCaseRow) -> ReviewCase:
        return self._to_cases(session, [row])[0]

    def _to_cases(
        self,
        session: Session,
        rows: Sequence[ReviewCaseRow],
    ) -> list[ReviewCase]:
        """The contract shape of each case, in `rows` order.

        A fixed number of queries however many cases there are: reviews, decision evidence,
        interventions with their follow-through, outcomes and consent are each read once for every
        case.
        """
        if not rows:
            return []
        case_ids = [row.case_id for row in rows]
        reviews_by_case: dict[str, list[CaseReviewRow]] = {case_id: [] for case_id in case_ids}
        for review in session.scalars(
            select(CaseReviewRow)
            .where(CaseReviewRow.case_id.in_(case_ids))
            .order_by(CaseReviewRow.recorded_at, CaseReviewRow.review_id)
        ):
            reviews_by_case[review.case_id].append(review)
        evidence = self._evidence_facts(session, [row.decision_evidence_id for row in rows])
        reads: dict[str, _RunReads] = {}
        for row in rows:
            reads.setdefault(row.run_id, _RunReads(run_id=row.run_id, person_id=row.person_id))
        run_ids = list(reads)
        self._load_run_interventions(session, reads)
        self._load_run_outcomes(session, reads)
        latest_consent: dict[str, ConsentEvidenceRow] = {}
        for consent in session.scalars(
            select(ConsentEvidenceRow)
            .where(ConsentEvidenceRow.run_id.in_(run_ids))
            .order_by(ConsentEvidenceRow.recorded_at.desc(), ConsentEvidenceRow.evidence_id.desc())
        ):
            latest_consent.setdefault(consent.run_id, consent)

        cases: list[ReviewCase] = []
        for row in rows:
            reviews = reviews_by_case[row.case_id]
            review = reviews[-1] if reviews else None
            facts = evidence.get(row.decision_evidence_id)
            opened_day, days_in_review, review_by_day = self._case_clock_from(
                row, facts[0] if facts is not None else None
            )
            run_reads = reads[row.run_id]
            prior_outreach = self._prior_outreach(
                run_reads,
                opened_day,
                run_reads.latest_outcome_by_intervention(),
                run_reads.follow_through,
            )
            opening_decision = facts[1] if facts is not None else None
            gate = (
                _CASE_GATE_BY_DECISION.get(Decision(opening_decision))
                if opening_decision is not None
                else None
            )
            consent = latest_consent.get(row.run_id)
            cases.append(
                ReviewCase(
                    case_id=row.case_id,
                    person_id=row.person_id,
                    title=row.title,
                    status=CaseStatus(row.status),
                    priority=row.priority,
                    opened_at=_as_utc(row.opened_at),
                    summary=row.summary,
                    evidence=row.evidence_json,
                    recommendation=row.recommendation,
                    reviewer_note=review.note if review else None,
                    decision_evidence_id=row.decision_evidence_id,
                    consent_active=bool(consent and consent.active),
                    action_history=[
                        ReviewAction(
                            review_evidence_id=item.review_id,
                            status=CaseStatus(item.status),
                            reviewer=item.reviewer,
                            note=item.note,
                            recorded_at=_as_utc(item.recorded_at),
                            agent_recommendation=item.agent_recommendation,
                            human_action=(
                                HumanAction(item.human_action) if item.human_action else None
                            ),
                            override_reason=(
                                OverrideReason(item.override_reason)
                                if item.override_reason
                                else None
                            ),
                            reached_too_late=item.reached_too_late,
                            context_gap_category=(
                                ContextGapCategory(item.context_gap_category)
                                if item.context_gap_category
                                else None
                            ),
                        )
                        for item in reviews
                    ],
                    opened_day=opened_day,
                    days_in_review=days_in_review,
                    review_by_day=review_by_day,
                    last_reviewed_at=_as_utc(review.recorded_at) if review else None,
                    reviewer=review.reviewer if review else None,
                    resolution=CaseResolution(row.resolution) if row.resolution else None,
                    prior_outreach=prior_outreach,
                    why_human=_why_human(gate, prior_outreach),
                )
            )
        return cases

    def list_cases(self, *, person_id: str | None = None) -> list[ReviewCase]:
        with self.sessions() as session:
            if person_id is None:
                # Coordinator semantic: the union of every active run's cases, across every
                # person. A strict no-op when only one person exists.
                active_run_ids = select(ScenarioRunRow.run_id).where(
                    ScenarioRunRow.active.is_(True)
                )
                statement = select(ReviewCaseRow).where(ReviewCaseRow.run_id.in_(active_run_ids))
            else:
                run = self._active_run(session, person_id)
                statement = select(ReviewCaseRow).where(ReviewCaseRow.run_id == run.run_id)
            rows = session.scalars(
                statement.order_by(ReviewCaseRow.priority.desc(), ReviewCaseRow.opened_at.desc())
            )
            return self._to_cases(session, list(rows))

    @staticmethod
    def _with_recorded_decision(state: PersonState, recorded: str | None) -> PersonState:
        """`state` with `last_decision` replaced by the decision recorded for its current day.

        Outreach (`GENTLE_NUDGE`, `PROGRAMME_SUGGESTION`) is only ever returned from the
        severity rung, so a recorded outreach decision also names that gate -- the read-time gate
        can only differ from it by counting that day's own intervention against the cap. Any
        other recorded decision keeps the read-time gate, which is the same rung minus the
        downgrades, and a downgrade only ever lowers the decision. With no recorded decision for
        the day, a read-time outreach decision is lowered to `NO_ACTION`: nothing was sent for it.

        The more conservative of the two always wins. A hold that arose *after* the decision was
        recorded -- the person accepted the suggestion that day (cooldown), explained their week,
        withdrew consent -- shows in the read-time gate, and the recorded decision must not
        overwrite it.

        `recorded` is `_recorded_decisions`' answer for the run: `None` when nothing was recorded
        for the day (or the read-time gate holds, in which case it is never read).
        """
        if state.decided_by_gate in _READ_TIME_HOLDS:
            return state
        outreach = {Decision.GENTLE_NUDGE, Decision.PROGRAMME_SUGGESTION}
        if recorded is None:
            if state.last_decision in outreach:
                return state.model_copy(update={"last_decision": Decision.NO_ACTION})
            return state
        decision = Decision(recorded)
        update: dict[str, object] = {"last_decision": decision}
        if decision in outreach:
            update["decided_by_gate"] = PolicyGate.SEVERITY_PERSISTENCE
        return state.model_copy(update=update)

    # ── Review setting, person by person (ADR 0008) ───────────────────────────────────────────
    #
    # The live review threshold is a pure fold over append-only decision rows, read fresh on every
    # evaluation. Everything below either reads (state, replay) or appends a proposal or decision
    # row plus one audit event carrying ids, kinds and values -- never a note, a reasoning or any
    # other free text (`test_audit_redaction.py`).

    @staticmethod
    def _threshold_decision_rows(session: Session, run_id: str) -> list[ReviewThresholdDecisionRow]:
        return list(
            session.scalars(
                select(ReviewThresholdDecisionRow)
                .where(ReviewThresholdDecisionRow.run_id == run_id)
                .order_by(
                    ReviewThresholdDecisionRow.decided_at,
                    ReviewThresholdDecisionRow.decision_id,
                )
            )
        )

    @staticmethod
    def _threshold_fact(row: ReviewThresholdDecisionRow) -> ThresholdDecisionFact:
        after = (
            ReviewThreshold(row.severity_pct, row.persistence_days)
            if row.severity_pct is not None and row.persistence_days is not None
            else None
        )
        return ThresholdDecisionFact(
            decision_id=row.decision_id,
            kind=ReviewThresholdDecisionKind(row.kind),
            previous=ReviewThreshold(row.previous_severity_pct, row.previous_persistence_days),
            after=after,
            decided_on_day=row.decided_on_day,
            effective_from_day=row.effective_from_day,
            decided_at=_as_utc(row.decided_at),
            revert_trigger=(
                ReviewThresholdRevertTrigger(row.revert_trigger) if row.revert_trigger else None
            ),
            ends_approval_id=row.ends_approval_id,
            affects_decision_id=row.affects_decision_id,
            proposal_id=row.proposal_id,
            rejection_reason=(
                ReviewThresholdRejectionReason(row.rejection_reason)
                if row.rejection_reason
                else None
            ),
        )

    def _threshold_facts(self, session: Session, run_id: str) -> list[ThresholdDecisionFact]:
        return [self._threshold_fact(row) for row in self._threshold_decision_rows(session, run_id)]

    def _threshold_day_signals(
        self,
        session: Session,
        run: ScenarioRunRow,
        *,
        last_n: int,
        include_self_reports: bool = True,
        metric_rows: Sequence[DailyMetricRow] | None = None,
        reads: _RunReads | None = None,
    ) -> list[DaySignal]:
        """The last `last_n` stored days' signals, each recomputed as `_evaluate` computed it.

        Every earlier row, that row's stored context, the confirmed reference in force on that
        day, and the person's own account of that day. Read-only.

        `include_self_reports=False` leaves the person's own account out: the calibration agent's
        view, into which nothing derived from a day dispute may enter (see
        `agent.threshold_tools`).

        `metric_rows`, when a caller has already loaded every one of this run's `DailyMetricRow`s
        in day order in the same session, is used instead of reading them again.

        `reads`, the run's `_load_run_reads` inputs, supplies the rows, the confirmations and the
        self-reports without another query. With self-reports wanted and no `reads`, they are
        loaded once for the run rather than queried day by day.
        """
        if reads is None and include_self_reports:
            reads = self._run_reads(session, run)
        if reads is not None:
            rows = list(metric_rows) if metric_rows is not None else list(reads.metric_rows)
            confirmations = list(reads.confirmations)
        else:
            rows = (
                list(metric_rows)
                if metric_rows is not None
                else list(
                    session.scalars(
                        select(DailyMetricRow)
                        .where(DailyMetricRow.run_id == run.run_id)
                        .order_by(DailyMetricRow.day)
                    )
                )
            )
            confirmations = list(
                session.scalars(
                    select(BaselineConfirmationRow).where(
                        BaselineConfirmationRow.run_id == run.run_id
                    )
                )
            )
        self_reports = reads

        def confirmed_reference_on(day: date) -> ConfirmedReference | None:
            # `_confirmed_reference`, as of `day`: the latest decision decided on or before it.
            in_force = [row for row in confirmations if row.decided_on_day <= day]
            if not in_force:
                return None
            latest = max(in_force, key=lambda row: (row.decided_on_day, row.confirmation_id))
            if latest.decision != BaselineConfirmationDecision.CONFIRM.value:
                return None
            if latest.new_reference_steps is None:
                return None
            return ConfirmedReference(steps=latest.new_reference_steps, days=latest.streak_days)

        return day_signals(
            [self._to_metric(row) for row in rows],
            [ContextSignal.model_validate(row.context_json) for row in rows],
            person_id=run.person_id,
            last_n=last_n,
            confirmed_reference_on=confirmed_reference_on,
            conflict_on=(
                self_reports.self_reported_conflict
                if include_self_reports and self_reports is not None
                else (lambda _day: (False, None))
            ),
        )

    def _add_threshold_decision(
        self,
        session: Session,
        run: ScenarioRunRow,
        *,
        kind: ReviewThresholdDecisionKind,
        previous: ReviewThreshold,
        after: ReviewThreshold | None,
        decided_by: str,
        now: datetime,
        decided_on_day: date | None = None,
        effective_from_day: date | None = None,
        proposal_id: str | None = None,
        ends_approval_id: str | None = None,
        affects_decision_id: str | None = None,
        revert_trigger: ReviewThresholdRevertTrigger | None = None,
        rejection_reason: ReviewThresholdRejectionReason | None = None,
        note: str | None = None,
        cause_confirmed: bool | None = None,
        replay: ReviewThresholdReplay | None = None,
        trigger_case_id: str | None = None,
        trigger_review_id: str | None = None,
    ) -> ReviewThresholdDecisionRow:
        decided_on = decided_on_day or run.current_day
        row = ReviewThresholdDecisionRow(
            decision_id=_id("threshold_decision"),
            run_id=run.run_id,
            person_id=run.person_id,
            kind=kind.value,
            proposal_id=proposal_id,
            ends_approval_id=ends_approval_id,
            affects_decision_id=affects_decision_id,
            revert_trigger=revert_trigger.value if revert_trigger else None,
            previous_severity_pct=previous.severity_pct,
            previous_persistence_days=previous.persistence_days,
            severity_pct=after.severity_pct if after else None,
            persistence_days=after.persistence_days if after else None,
            decided_by=decided_by,
            rejection_reason=rejection_reason.value if rejection_reason else None,
            note=note,
            cause_confirmed=cause_confirmed,
            replay_json=replay.model_dump(mode="json") if replay is not None else None,
            trigger_case_id=trigger_case_id,
            trigger_review_id=trigger_review_id,
            decided_on_day=decided_on,
            # Every change takes effect from the next simulated day: the day just decided is never
            # re-decided (ADR 0007 §5). `expired` rows pass the day expiry already applied.
            effective_from_day=effective_from_day or decided_on + timedelta(days=1),
            decided_at=now,
        )
        session.add(row)
        session.flush()
        return row

    def _threshold_decision_audit(
        self,
        run: ScenarioRunRow,
        event_type: str,
        actor: str,
        row: ReviewThresholdDecisionRow,
        now: datetime,
        extra: dict[str, object] | None = None,
    ) -> AuditEventRow:
        """Ids, kinds, values and days only. `note_present`, never the note (the coordinator's
        words stay on the decision row). `extra` adds ids and flags only."""
        return self._audit_row(
            run.run_id,
            event_type,
            actor,
            person_id=run.person_id,
            detail={
                "decision_id": row.decision_id,
                "kind": row.kind,
                "proposal_id": row.proposal_id,
                "ends_approval_id": row.ends_approval_id,
                "affects_decision_id": row.affects_decision_id,
                "revert_trigger": row.revert_trigger,
                "before": {
                    "severity_pct": row.previous_severity_pct,
                    "persistence_days": row.previous_persistence_days,
                },
                "after": (
                    {"severity_pct": row.severity_pct, "persistence_days": row.persistence_days}
                    if row.severity_pct is not None
                    else None
                ),
                "rejection_reason": row.rejection_reason,
                "cause_confirmed": row.cause_confirmed,
                "note_present": bool(row.note),
                "replay_recorded": row.replay_json is not None,
                "trigger_case_id": row.trigger_case_id,
                "trigger_review_id": row.trigger_review_id,
                "decided_on_day": row.decided_on_day.isoformat(),
                "effective_from_day": row.effective_from_day.isoformat(),
                **(extra or {}),
            },
            at=now,
        )

    @staticmethod
    def _threshold_proposal_rows(session: Session, run_id: str) -> list[ReviewThresholdProposalRow]:
        return list(
            session.scalars(
                select(ReviewThresholdProposalRow)
                .where(ReviewThresholdProposalRow.run_id == run_id)
                .order_by(
                    ReviewThresholdProposalRow.proposed_at,
                    ReviewThresholdProposalRow.proposal_id,
                )
            )
        )

    @staticmethod
    def _open_threshold_proposals(
        session: Session, run_id: str
    ) -> list[ReviewThresholdProposalRow]:
        """Proposed changes nobody has decided yet (a no-change or write-up is never open)."""
        decided = select(ReviewThresholdDecisionRow.proposal_id).where(
            ReviewThresholdDecisionRow.run_id == run_id,
            ReviewThresholdDecisionRow.proposal_id.is_not(None),
        )
        return list(
            session.scalars(
                select(ReviewThresholdProposalRow)
                .where(
                    ReviewThresholdProposalRow.run_id == run_id,
                    ReviewThresholdProposalRow.output_kind
                    == ReviewThresholdOutputKind.PROPOSAL.value,
                    ReviewThresholdProposalRow.proposal_id.not_in(decided),
                )
                .order_by(
                    ReviewThresholdProposalRow.proposed_at.desc(),
                    ReviewThresholdProposalRow.proposal_id.desc(),
                )
            )
        )

    @staticmethod
    def _proposals_this_week(session: Session, sub: str, now: datetime) -> int:
        """Calibrator and manual proposals this coordinator's reviews produced in the last seven
        wall-clock days, on active runs. The weekly cap is about a coordinator's workload, so it
        is counted in their time, not in any one senior's simulated days."""
        active_runs = select(ScenarioRunRow.run_id).where(ScenarioRunRow.active.is_(True))
        return int(
            session.scalar(
                select(func.count())
                .select_from(ReviewThresholdProposalRow)
                .where(
                    ReviewThresholdProposalRow.reported_by == sub,
                    ReviewThresholdProposalRow.output_kind
                    == ReviewThresholdOutputKind.PROPOSAL.value,
                    ReviewThresholdProposalRow.proposer
                    != ReviewThresholdProposer.STARTING_SETTING.value,
                    ReviewThresholdProposalRow.proposed_at >= now - timedelta(days=7),
                    ReviewThresholdProposalRow.run_id.in_(active_runs),
                )
            )
            or 0
        )

    @staticmethod
    def _threshold_known_evidence_ids(session: Session, run_id: str) -> set[str]:
        """Evidence that belongs to this person's run: its reviews, its decisions, its daily
        readings (what the calibration agent's `day:`, `context:` and `variability` aliases resolve
        to) and its own review-setting records (`threshold:` aliases)."""
        reviews = session.scalars(
            select(CaseReviewRow.review_id).where(CaseReviewRow.run_id == run_id)
        )
        decisions = session.scalars(
            select(DecisionEvidenceRow.evidence_id).where(DecisionEvidenceRow.run_id == run_id)
        )
        readings = session.scalars(
            select(DailyMetricRow.evidence_id).where(DailyMetricRow.run_id == run_id)
        )
        threshold_decisions = session.scalars(
            select(ReviewThresholdDecisionRow.decision_id).where(
                ReviewThresholdDecisionRow.run_id == run_id
            )
        )
        threshold_outputs = session.scalars(
            select(ReviewThresholdProposalRow.proposal_id).where(
                ReviewThresholdProposalRow.run_id == run_id
            )
        )
        return {*reviews, *decisions, *readings, *threshold_decisions, *threshold_outputs}

    def _threshold_snapshot(
        self, session: Session, run: ScenarioRunRow
    ) -> tuple[str | None, str | None, bool, date]:
        latest_proposal = session.scalar(
            select(ReviewThresholdProposalRow.proposal_id)
            .where(ReviewThresholdProposalRow.run_id == run.run_id)
            .order_by(
                ReviewThresholdProposalRow.proposed_at.desc(),
                ReviewThresholdProposalRow.proposal_id.desc(),
            )
            .limit(1)
        )
        latest_decision = session.scalar(
            select(ReviewThresholdDecisionRow.decision_id)
            .where(ReviewThresholdDecisionRow.run_id == run.run_id)
            .order_by(
                ReviewThresholdDecisionRow.decided_at.desc(),
                ReviewThresholdDecisionRow.decision_id.desc(),
            )
            .limit(1)
        )
        return (
            latest_proposal,
            latest_decision,
            self._consent_active(session, run.run_id),
            run.current_day,
        )

    def _end_threshold_approval(
        self,
        session: Session,
        run: ScenarioRunRow,
        *,
        kind: ReviewThresholdDecisionKind,
        ends_approval_id: str,
        previous: ReviewThreshold,
        after: ReviewThreshold,
        event_type: str,
        now: datetime,
        decided_on_day: date | None = None,
        effective_from_day: date | None = None,
        revert_trigger: ReviewThresholdRevertTrigger | None = None,
        trigger_case_id: str | None = None,
        trigger_review_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> ReviewThresholdDecisionRow | None:
        """Write a revert or expiry inside a savepoint.

        `ends_approval_id` is unique: if a concurrent writer ended the same approval first, the
        insert fails, the savepoint rolls back, and the approval is simply already ended -- the
        surrounding transaction (a decided day, a recorded review) carries on.
        """
        try:
            with session.begin_nested():
                row = self._add_threshold_decision(
                    session,
                    run,
                    kind=kind,
                    previous=previous,
                    after=after,
                    decided_by="system",
                    now=now,
                    decided_on_day=decided_on_day,
                    effective_from_day=effective_from_day,
                    ends_approval_id=ends_approval_id,
                    revert_trigger=revert_trigger,
                    trigger_case_id=trigger_case_id,
                    trigger_review_id=trigger_review_id,
                )
        except IntegrityError as error:
            if not _violates_unique(
                error, "uq_review_threshold_decisions_ends_approval", "ends_approval_id"
            ):
                raise
            return None
        session.add(self._threshold_decision_audit(run, event_type, "system", row, now, extra))
        return row

    def _supersede_stale_threshold_proposals(
        self,
        session: Session,
        run: ScenarioRunRow,
        day: date,
        now: datetime,
        *,
        target: ReviewThreshold,
        trigger_case_id: str | None = None,
        trigger_review_id: str | None = None,
    ) -> list[str]:
        """Reject, as `superseded`, every open proposal made against a value that will no longer be
        live tomorrow. A proposal is one step from the value it was made against; once a revert
        or an expiry moves that value, approving it would apply a step from the wrong place.

        A collision on the proposal's unique decision means a coordinator decided it in the same
        instant. If that was an approval, it is now pending for tomorrow, so the pending-approval
        check runs again against `target` before the remaining proposals are looked at.
        """
        rejected: list[str] = []
        handled: set[str] = set()
        while True:
            tomorrow = resolve_live_threshold(
                self._threshold_facts(session, run.run_id), day + timedelta(days=1)
            ).threshold
            stale = [
                proposal
                for proposal in self._open_threshold_proposals(session, run.run_id)
                if proposal.proposal_id not in handled
                and ReviewThreshold(
                    proposal.previous_severity_pct, proposal.previous_persistence_days
                )
                != tomorrow
            ]
            if not stale:
                return rejected
            proposal = stale[0]
            handled.add(proposal.proposal_id)
            try:
                with session.begin_nested():
                    row = self._add_threshold_decision(
                        session,
                        run,
                        kind=ReviewThresholdDecisionKind.REJECTED,
                        previous=ReviewThreshold(
                            proposal.previous_severity_pct, proposal.previous_persistence_days
                        ),
                        after=self._proposed_threshold(proposal),
                        decided_by="system",
                        now=now,
                        decided_on_day=day,
                        proposal_id=proposal.proposal_id,
                        rejection_reason=ReviewThresholdRejectionReason.SUPERSEDED,
                        # The event that moved the value (a late mark), when there is one; a
                        # daily check has none and keeps the proposal's own case.
                        trigger_case_id=trigger_case_id or proposal.trigger_case_id,
                        trigger_review_id=trigger_review_id,
                    )
            except IntegrityError as error:
                if not _violates_unique(
                    error, "uq_review_threshold_decisions_proposal", "proposal_id"
                ):
                    raise
                self._end_pending_looser_approvals(
                    session,
                    run,
                    target=target,
                    now=now,
                    trigger_case_id=trigger_case_id,
                    trigger_review_id=trigger_review_id,
                )
                continue
            session.add(
                self._threshold_decision_audit(run, "review_threshold_rejected", "system", row, now)
            )
            rejected.append(row.decision_id)

    def _lock_threshold_run(self, session: Session, run_id: str) -> ScenarioRunRow:
        """Lock the run row before anything else a review-setting writer does.

        Every writer -- a review, approve/reject/manual/reconfirm/confirm-starting, the
        calibrator's Transaction B, consent withdrawal and both phases of `advance()` -- calls this
        first, before inserting any row that references `scenario_runs`: such an insert takes a
        KEY SHARE lock on the run, and upgrading that to a row lock later is how two writers
        deadlock on PostgreSQL. `FOR NO KEY UPDATE` (`key_share=True`) still serialises the
        writers against each other while staying compatible with the KEY SHARE locks plain reads
        and inserts elsewhere take. `populate_existing` refreshes a run already in the session, so
        `current_day` and `active` are read as of the lock. A no-op on SQLite, which is
        single-writer.
        """
        run = session.scalar(
            select(ScenarioRunRow)
            .where(ScenarioRunRow.run_id == run_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if run is None:  # pragma: no cover - callers hold a run they just read
            raise RuntimeError(f"Scenario run {run_id!r} no longer exists.")
        return run

    def _lock_active_run(self, session: Session, run_id: str) -> ScenarioRunRow:
        """`_lock_threshold_run`, refusing a run a reset deactivated before the lock was taken."""
        run = self._lock_threshold_run(session, run_id)
        if not run.active:
            raise StaleRunConflict(
                "This person's demo story was reset while this request was waiting, so this "
                "request was not applied to the new story. Re-read the person before trying again."
            )
        return run

    @staticmethod
    def _threshold_clock(session: Session, run_id: str, now: datetime) -> datetime:
        """The timestamp every review-setting row of this transaction is stamped from.

        Taken after the run lock, then clamped past the newest decision already stored for the
        run, so a row written now always folds after anything a writer committed before this one
        took the lock -- even when that writer's wall clock ran ahead of this one's. The fold
        orders facts of the same effective day by `decided_at`, and a revert must never fold
        before an approval it was meant to end.
        """
        latest = session.scalar(
            select(func.max(ReviewThresholdDecisionRow.decided_at)).where(
                ReviewThresholdDecisionRow.run_id == run_id
            )
        )
        if latest is None:
            return now
        return max(now, _as_utc(latest) + timedelta(microseconds=1))

    def _end_pending_looser_approvals(
        self,
        session: Session,
        run: ScenarioRunRow,
        *,
        target: ReviewThreshold,
        now: datetime,
        trigger_case_id: str | None = None,
        trigger_review_id: str | None = None,
        trigger: ReviewThresholdRevertTrigger = ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
    ) -> list[str]:
        """End the approvals pending for tomorrow that would make Care+ ask later than
        `target` in either dimension.

        Walks tomorrow's stack from the top, down to the first approval whose ending restores a
        value that asks no later than `target`, and ends every approval on the way with its own
        row (top-down, the decisive one newest). Nothing qualifying -> nothing written.
        """
        today = run.current_day
        tomorrow = today + timedelta(days=1)
        facts = self._threshold_facts(session, run.run_id)
        ended = {fact.ends_approval_id for fact in facts if fact.ends_approval_id}
        pending = resolve_live_threshold(facts, tomorrow)
        if never_later(pending.threshold, target):
            return []
        visited: list[tuple[str, ReviewThreshold]] = []
        restored: ReviewThreshold | None = None
        candidate, held = pending.approval_id, pending.threshold
        while candidate is not None and candidate not in ended:
            if candidate in {approval for approval, _ in visited}:
                break
            visited.append((candidate, held))
            trial = resolve_live_threshold(
                [*facts, pending_revert_fact(candidate, held, today=today, decided_at=now)],
                tomorrow,
            )
            if never_later(trial.threshold, target):
                restored = trial.threshold
                break
            candidate, held = trial.approval_id, trial.threshold
        if restored is None:
            return []
        written: list[str] = []
        for index, (approval_id, value) in enumerate(visited):
            row = self._end_threshold_approval(
                session,
                run,
                kind=ReviewThresholdDecisionKind.REVERTED,
                ends_approval_id=approval_id,
                previous=value,
                after=restored,
                event_type="review_threshold_reverted",
                now=now + timedelta(microseconds=100 + index),
                revert_trigger=trigger,
                trigger_case_id=trigger_case_id,
                trigger_review_id=trigger_review_id,
            )
            if row is not None:
                written.append(row.decision_id)
        return written

    def _revert_never_later(
        self,
        session: Session,
        run: ScenarioRunRow,
        now: datetime,
        *,
        trigger: ReviewThresholdRevertTrigger,
        trigger_case_id: str | None,
        trigger_review_id: str | None,
    ) -> list[str]:
        """A revert that must never ask later -- `reached_too_late` ("this should have reached me
        sooner") or, stage 3, `far_more_severe`: from tomorrow Care+ must never ask later
        than it does today, or than tomorrow's already-decided value, and should ask sooner.

        1. `review_threshold.reached_too_late_revert` walks tomorrow's stack from the top and picks
           the first approval whose ending restores a value that asks no later than today's live
           value and tomorrow's pending value in both dimensions, and sooner than both in one (the
           starting setting only if it passes the same test). Every approval it removes -- a
           pending one included -- gets its own ending row, written top-down so the lowest
           (decisive) one is the latest. Nothing qualifies -> no revert, and
           `review_threshold_revert_skipped` is audited (`pending_change` when a change already
           decided for tomorrow asks sooner; a second mark the same day lands here).
        2. Any approval pending for tomorrow that would still ask later than that is ended too.
        3. Open proposals made against a value that will not be live tomorrow are superseded.
        """
        facts = self._threshold_facts(session, run.run_id)
        today = run.current_day
        live = resolve_live_threshold(facts, today)
        target = live.threshold
        written: list[str] = []
        outcome = reached_too_late_revert(facts, today=today, decided_at=now, trigger=trigger)
        if isinstance(outcome, RevertSkipped):
            session.add(
                self._audit_row(
                    run.run_id,
                    "review_threshold_revert_skipped",
                    "system",
                    person_id=run.person_id,
                    detail={
                        "reason": outcome.reason,
                        "revert_trigger": trigger.value,
                        "live_approval_id": live.approval_id,
                        "trigger_case_id": trigger_case_id,
                        "trigger_review_id": trigger_review_id,
                        "day": today.isoformat(),
                    },
                    at=now,
                )
            )
        elif outcome is not None:
            for index, (approval_id, held) in enumerate(outcome.ends):
                decisive = index == len(outcome.ends) - 1
                row = self._end_threshold_approval(
                    session,
                    run,
                    kind=ReviewThresholdDecisionKind.REVERTED,
                    ends_approval_id=approval_id,
                    # The decisive row records the change the person lives: today's value to the
                    # restored one. The rows above it record what each removed approval held.
                    previous=outcome.previous if decisive else held,
                    after=outcome.restored,
                    event_type="review_threshold_reverted",
                    # Strictly increasing, so the fold and the notice read them top-down.
                    now=now + timedelta(microseconds=index),
                    revert_trigger=trigger,
                    trigger_case_id=trigger_case_id,
                    trigger_review_id=trigger_review_id,
                )
                if row is not None:
                    written.append(row.decision_id)
            if written:
                target = outcome.restored
        written += self._end_pending_looser_approvals(
            session,
            run,
            target=target,
            now=now,
            trigger_case_id=trigger_case_id,
            trigger_review_id=trigger_review_id,
            trigger=trigger,
        )
        if written:
            self._supersede_stale_threshold_proposals(
                session,
                run,
                today,
                now,
                target=target,
                trigger_case_id=trigger_case_id,
                trigger_review_id=trigger_review_id,
            )
        return written

    def _threshold_episode_context(
        self,
        session: Session,
        run_id: str,
        *,
        trigger_case_id: str,
        trigger_review_ids: tuple[str, ...],
        reported_by: str | None,
        round_id: str | None,
        round_index: int,
    ) -> _ThresholdEpisode | None:
        run = session.get(ScenarioRunRow, run_id)
        case_row = session.get(ReviewCaseRow, trigger_case_id)
        review_row = (
            session.get(CaseReviewRow, trigger_review_ids[-1]) if trigger_review_ids else None
        )
        if run is None or not run.active or case_row is None or review_row is None:
            return None
        facts = self._threshold_facts(session, run.run_id)
        live = resolve_live_threshold(facts, run.current_day)
        # False alarms count toward loosening only from the day the live value took effect: an
        # alarm raised under a setting that has since changed (approved, reverted or expired) says
        # nothing about the current one. `None` while nothing has ever changed.
        counted_from = live.effective_from_day
        reviews = session.execute(
            select(CaseReviewRow, ReviewCaseRow)
            .join(ReviewCaseRow, ReviewCaseRow.case_id == CaseReviewRow.case_id)
            .where(CaseReviewRow.run_id == run.run_id)
            .order_by(CaseReviewRow.recorded_at, CaseReviewRow.review_id)
        ).all()
        alarms: list[FalseAlarmRef] = []
        for review, case in reviews:
            if case.opened_day is None:
                continue
            if not is_false_alarm(review.status, review.human_action, review.override_reason):
                continue
            if review.override_reason != OverrideReason.NOT_A_CONCERN.value:
                continue
            if counted_from is not None and case.opened_day < counted_from:
                continue
            alarms.append(
                FalseAlarmRef(
                    review_id=review.review_id,
                    opened_day=case.opened_day,
                    evidence_ids=(case.decision_evidence_id,),
                )
            )
        trigger = FalseAlarmRef(
            review_id=review_row.review_id,
            opened_day=case_row.opened_day or run.current_day,
            evidence_ids=(case_row.decision_evidence_id,),
        )
        return _ThresholdEpisode(
            run_id=run.run_id,
            person_id=run.person_id,
            current_day=run.current_day,
            live=live.threshold,
            trigger_reason=(
                OverrideReason(review_row.override_reason) if review_row.override_reason else None
            ),
            trigger=next(
                (alarm for alarm in alarms if alarm.review_id == trigger.review_id), trigger
            ),
            trigger_case_id=case_row.case_id,
            trigger_review_ids=trigger_review_ids,
            not_a_concern_alarms=tuple(alarms),
            blocked_values=blocked_threshold_values(facts),
            reported_by=reported_by,
            round_id=round_id or _id("threshold_round"),
            round_index=round_index,
            snapshot=self._threshold_snapshot(session, run),
            trigger_predates_live=self._trigger_predates_live(case_row.opened_day, live),
        )

    @staticmethod
    def _trigger_predates_live(opened_day: date | None, live: LiveReviewThreshold) -> bool:
        """Whether a false alarm's case opened before the live setting took effect."""
        return (
            opened_day is not None
            and live.effective_from_day is not None
            and opened_day < live.effective_from_day
        )

    def _fixed_rule_run_record(
        self,
        now: datetime,
        *,
        violations: tuple[str, ...] = (),
        cause: ReviewThresholdCause | None = None,
        task: ThresholdPlannerTask = "calibrate",
    ) -> dict[str, object]:
        """Which proposer ran, in the shape `ActivityPlanRun.as_evidence` records a planner run.

        Used when no calibration-agent run record was handed in -- with `LLM_ENABLED=false`, the
        offline path, where every output is the deterministic fixed rule's, recorded as
        `fallback_disabled` so the Care Team card can say so plainly. With the LLM on,
        `_calibrate_review_threshold` always hands in a `ThresholdPlanRun` record instead.
        """
        write_up = task == "write_up"
        supplied = (
            "the fixed write-up template was used"
            if write_up
            else "the deterministic fixed rule proposed"
        )
        reason = (
            f"LLM_ENABLED is false, so {supplied}."
            if not self.settings.llm_enabled
            else f"The agent was not consulted, so {supplied}."
        )
        label = "Fixed write-up template used" if write_up else "Fixed rule used"
        usage = AgentUsage()
        return {
            "agent_evidence_id": _id("threshold_agent"),
            "agent_version": THRESHOLD_CALIBRATOR_VERSION,
            "task": task,
            "mode": "fallback_disabled",
            "trace_detail": f"{label} (fallback_disabled); {reason}",
            "model": None,
            "provider": None,
            "transport": None,
            "started_at": now.isoformat(),
            "latency_ms": 0,
            "iterations": 0,
            "max_iterations": 0,
            "tool_calls": [],
            "guardrail_rejections": list(violations),
            "guardrail_violation_count": len(violations),
            "rejected_proposal_count": 0,
            "fallback_reason": reason,
            "usage": usage.model_dump(),
            "total_tokens": usage.total_tokens,
            "agent_reasoning": None,
            "cause": cause.value if cause else None,
            "boundary": (
                WRITE_UP_BOUNDARY
                if write_up
                else (
                    "The fixed rule proposes at most one step inside the allowed range. It cannot "
                    "change a baseline, consent, data quality or the contact cap. It cannot stop "
                    "a drop of 60% or more for 3 low days from asking, it cannot delay a review "
                    "more than 3 days past the starting setting, and nothing it proposes applies "
                    "until a coordinator approves it."
                )
            ),
        }

    def _run_threshold_follow_ups(self, follow_ups: Sequence[_ThresholdFollowUp]) -> None:
        """Run what a committed review or advance left to do, write-ups first (a calibration reads
        the history they add). Each is independently safe: a failure is audited, never raised."""
        for follow_up in sorted(follow_ups, key=lambda item: item.kind != "write_up"):
            if follow_up.kind == "write_up" and follow_up.decision_id is not None:
                self._write_up_safely(follow_up.run_id, follow_up.decision_id)
            elif follow_up.kind in ("calibrate", "tighten") and follow_up.trigger_case_id:
                self._calibrate_safely(
                    follow_up.run_id,
                    trigger_case_id=follow_up.trigger_case_id,
                    trigger_review_ids=follow_up.trigger_review_ids,
                    reported_by=follow_up.reported_by,
                    task=follow_up.kind,
                )

    @staticmethod
    def _write_up_targets(session: Session, decision_ids: Sequence[str]) -> list[str]:
        """The reverts among `decision_ids` that ended an approval an agent or the fixed rule
        proposed -- the ones that owe the coordinator a write-up."""
        targets: list[str] = []
        calibrators = {
            ReviewThresholdProposer.AGENT.value,
            ReviewThresholdProposer.FIXED_RULE.value,
        }
        for decision_id in decision_ids:
            revert = session.get(ReviewThresholdDecisionRow, decision_id)
            if revert is None or revert.kind != ReviewThresholdDecisionKind.REVERTED.value:
                continue
            approval = (
                session.get(ReviewThresholdDecisionRow, revert.ends_approval_id)
                if revert.ends_approval_id
                else None
            )
            proposal = (
                session.get(ReviewThresholdProposalRow, approval.proposal_id)
                if approval is not None and approval.proposal_id
                else None
            )
            if proposal is not None and proposal.proposer in calibrators:
                targets.append(decision_id)
        return targets

    def _owed_write_ups(self, session: Session, run_id: str) -> list[str]:
        """Reverts of this run that owe a write-up (an agent or fixed-rule approval ended) and
        have none yet, oldest first. Read-only; the caller runs them after its commit."""
        reverts = list(
            session.scalars(
                select(ReviewThresholdDecisionRow.decision_id)
                .where(
                    ReviewThresholdDecisionRow.run_id == run_id,
                    ReviewThresholdDecisionRow.kind == ReviewThresholdDecisionKind.REVERTED.value,
                )
                .order_by(
                    ReviewThresholdDecisionRow.decided_at, ReviewThresholdDecisionRow.decision_id
                )
            )
        )
        written = set(
            session.scalars(
                select(ReviewThresholdProposalRow.write_up_for_decision_id).where(
                    ReviewThresholdProposalRow.run_id == run_id,
                    ReviewThresholdProposalRow.write_up_for_decision_id.is_not(None),
                )
            )
        )
        return [
            decision_id
            for decision_id in self._write_up_targets(
                session, [decision_id for decision_id in reverts if decision_id not in written]
            )
            if not self._write_up_attempts(session, run_id, decision_id)[1]
        ]

    @staticmethod
    def _write_up_attempts(session: Session, run_id: str, decision_id: str) -> tuple[int, bool]:
        """`(discarded, abandoned)` for one revert's write-up, read from the audit trail."""
        discarded, abandoned = 0, False
        for event in session.scalars(
            select(AuditEventRow).where(
                AuditEventRow.run_id == run_id,
                AuditEventRow.event_type.in_(
                    ("review_threshold_write_up_discarded", "review_threshold_write_up_abandoned")
                ),
            )
        ):
            if (event.detail_json or {}).get("write_up_for_decision_id") != decision_id:
                continue
            if event.event_type == "review_threshold_write_up_abandoned":
                abandoned = True
            else:
                discarded += 1
        return discarded, abandoned

    def _write_up_safely(self, run_id: str, decision_id: str) -> None:
        """`_write_up_revert`, after the revert it describes has committed. Never raises.

        At most `WRITE_UP_MAX_ATTEMPTS` failed attempts per revert, each audited as discarded;
        after the last, `review_threshold_write_up_abandoned` is audited once and no catch-up
        tries again.
        """
        with self.sessions() as session:
            _, abandoned = self._write_up_attempts(session, run_id, decision_id)
        if abandoned:
            return
        try:
            self._write_up_revert(run_id, decision_id)
        except Exception as error:
            agent_logger().warning(
                "threshold_write_up_failed",
                extra={
                    "structured_fields": {
                        "request_id": request_id_var.get(),
                        "loop": "review_threshold",
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                },
            )
            try:
                with self.sessions.begin() as session:
                    if session.get(ScenarioRunRow, run_id) is None:
                        return
                    # Locked so two follow-ups for one revert can't both count three discards.
                    run = self._lock_threshold_run(session, run_id)
                    session.add(
                        self._audit_row(
                            run.run_id,
                            "review_threshold_write_up_discarded",
                            "system",
                            person_id=run.person_id,
                            detail={
                                "reason": "error",
                                "error_type": type(error).__name__,
                                "write_up_for_decision_id": decision_id,
                            },
                        )
                    )
                    session.flush()
                    discarded, abandoned = self._write_up_attempts(session, run_id, decision_id)
                    if discarded >= WRITE_UP_MAX_ATTEMPTS and not abandoned:
                        session.add(
                            self._audit_row(
                                run.run_id,
                                "review_threshold_write_up_abandoned",
                                "system",
                                person_id=run.person_id,
                                detail={
                                    "reason": "attempts_exhausted",
                                    "attempts": discarded,
                                    "write_up_for_decision_id": decision_id,
                                },
                            )
                        )
            except Exception:  # pragma: no cover - the log line above already carries the failure
                agent_logger().exception("threshold_write_up_discard_audit_failed")

    def _write_up_revert(self, run_id: str, decision_id: str) -> None:
        """One write-up per revert: read in a session, write with none open, store once.

        The fixed template (`review_threshold.fixed_write_up_text`) is the answer whenever the
        agent is off, cannot be consulted, fails, or is refused on storing. Idempotent:
        `write_up_for_decision_id` is unique, and an existing write-up is never replaced.
        """
        agent_enabled = self.settings.llm_enabled
        context: ThresholdEpisodeContext | None = None
        with self.sessions() as session:
            run = session.get(ScenarioRunRow, run_id)
            revert = session.get(ReviewThresholdDecisionRow, decision_id)
            if (
                run is None
                or not run.active
                or revert is None
                or revert.run_id != run_id
                or revert.kind != ReviewThresholdDecisionKind.REVERTED.value
                or revert.severity_pct is None
                or revert.persistence_days is None
                or revert.revert_trigger is None
            ):
                return
            if session.scalar(
                select(ReviewThresholdProposalRow.proposal_id).where(
                    ReviewThresholdProposalRow.write_up_for_decision_id == decision_id
                )
            ):
                return
            approval = (
                session.get(ReviewThresholdDecisionRow, revert.ends_approval_id)
                if revert.ends_approval_id
                else None
            )
            proposal = (
                session.get(ReviewThresholdProposalRow, approval.proposal_id)
                if approval is not None and approval.proposal_id
                else None
            )
            previous = ReviewThreshold(
                revert.previous_severity_pct, revert.previous_persistence_days
            )
            restored = ReviewThreshold(revert.severity_pct, revert.persistence_days)
            trigger = ReviewThresholdRevertTrigger(revert.revert_trigger)
            fallback_text = fixed_write_up_text(
                trigger=trigger, previous=previous, restored=restored
            )
            fallback_cited = [revert.decision_id] + ([approval.decision_id] if approval else [])
            if agent_enabled:
                try:
                    facts = self._threshold_facts(session, run.run_id)
                    context = self._threshold_context_for(
                        session,
                        run,
                        today=run.current_day,
                        live=resolve_live_threshold(facts, run.current_day).threshold,
                        trigger_review_id=revert.trigger_review_id,
                        coordinator_reason=(
                            OverrideReason(proposal.coordinator_reason)
                            if proposal is not None and proposal.coordinator_reason
                            else None
                        ),
                        blocked_values=blocked_threshold_values(facts),
                        reversal=ReversalInput(
                            revert_decision_id=revert.decision_id,
                            approval_decision_id=approval.decision_id if approval else None,
                            trigger=trigger.value,
                            previous=previous,
                            restored=restored,
                            approved_proposer=proposal.proposer if proposal else None,
                        ),
                    )
                except Exception as error:  # noqa: BLE001 - the template still answers
                    agent_logger().warning(
                        "threshold_agent_context_unavailable",
                        extra={
                            "structured_fields": {
                                "request_id": request_id_var.get(),
                                "loop": "review_threshold",
                                "error_class": type(error).__name__,
                                "error": str(error),
                            }
                        },
                    )
        # No database session is open from here until the write.
        fallback = ThresholdAgentProposal(
            reasoning=fallback_text, cited_evidence_ids=fallback_cited
        )
        run_record: ThresholdPlanRun | None = None
        if agent_enabled:
            if context is None:
                run_record = threshold_fallback_run(
                    settings=self.settings,
                    task="write_up",
                    mode="fallback_error",
                    reason=AGENT_CONTEXT_UNAVAILABLE,
                    fallback=fallback,
                )
            else:
                run_record = self._plan_write_up_safely(context, fallback=fallback)
        by_agent = run_record is not None and run_record.mode == "agent"
        chosen = run_record.proposal if by_agent and run_record is not None else None
        self._store_write_up(
            run_id,
            decision_id,
            text=chosen.reasoning if chosen is not None else fallback_text,
            cited=list(chosen.cited_evidence_ids) if chosen is not None else fallback_cited,
            proposer=ReviewThresholdProposer.AGENT
            if by_agent
            else ReviewThresholdProposer.FIXED_RULE,
            agent_run=run_record.as_evidence() if run_record is not None else None,
            fallback_text=fallback_text,
            fallback_cited=fallback_cited,
        )

    def _plan_write_up_safely(
        self, context: ThresholdEpisodeContext, *, fallback: ThresholdAgentProposal
    ) -> ThresholdPlanRun:
        injected = (
            {"client_factory": self._threshold_client_factory}
            if self._threshold_client_factory is not None
            else {}
        )
        try:
            return write_up_reversal(
                context,
                settings=self.settings,
                fallback_text=fallback.reasoning,
                fallback_cited=fallback.cited_evidence_ids,
                **injected,
            )
        except Exception as error:  # noqa: BLE001 - must degrade to the template
            return threshold_fallback_run(
                settings=self.settings,
                task="write_up",
                mode="fallback_error",
                reason=run_failure_reason(error),
                fallback=fallback,
                client_requested=True,
            )

    def _store_write_up(
        self,
        run_id: str,
        decision_id: str,
        *,
        text: str,
        cited: list[str],
        proposer: ReviewThresholdProposer,
        agent_run: dict[str, object] | None,
        fallback_text: str,
        fallback_cited: list[str],
    ) -> None:
        """Store one `write_up` output. An agent's text is re-checked here (wording and citations
        on fresh evidence ids); refused, the template is stored instead and the record says so
        (`fallback_error`, `AGENT_OUTPUT_REFUSED <violations>`)."""
        with self.sessions.begin() as session:
            run = self._lock_threshold_run(session, run_id)
            now = self._threshold_clock(session, run.run_id, _utcnow())
            revert = session.get(ReviewThresholdDecisionRow, decision_id)
            if revert is None or not run.active:
                return
            if session.scalar(
                select(ReviewThresholdProposalRow.proposal_id).where(
                    ReviewThresholdProposalRow.write_up_for_decision_id == decision_id
                )
            ):
                return
            record = dict(agent_run) if agent_run is not None else None
            if proposer is ReviewThresholdProposer.AGENT:
                known = self._threshold_known_evidence_ids(session, run.run_id)
                violations = reasoning_violations(text)
                if not cited or any(evidence_id not in known for evidence_id in cited):
                    violations.append(VIOLATION_CITATIONS)
                if violations:
                    reason = " ".join((AGENT_OUTPUT_REFUSED, *violations))
                    earlier = (record or {}).get("guardrail_rejections")
                    rejections = [*(earlier if isinstance(earlier, list) else []), *violations]
                    record = {
                        **(record or {}),
                        "mode": "fallback_error",
                        "trace_detail": f"Fixed write-up template used (fallback_error); {reason}",
                        "guardrail_rejections": rejections,
                        "guardrail_violation_count": len(rejections),
                        "fallback_reason": reason,
                        "agent_reasoning": None,
                    }
                    text, cited, proposer = (
                        fallback_text,
                        fallback_cited,
                        ReviewThresholdProposer.FIXED_RULE,
                    )
            if record is None:
                record = self._fixed_rule_run_record(now, task="write_up")
            record = {**record, "cause": None}
            row = ReviewThresholdProposalRow(
                proposal_id=_id("threshold_proposal"),
                run_id=run.run_id,
                person_id=run.person_id,
                output_kind=ReviewThresholdOutputKind.WRITE_UP.value,
                proposer=proposer.value,
                round_id=None,
                round_index=None,
                previous_severity_pct=revert.previous_severity_pct,
                previous_persistence_days=revert.previous_persistence_days,
                proposed_severity_pct=None,
                proposed_persistence_days=None,
                cause=None,
                reasoning=text,
                cited_evidence_ids=list(cited),
                trigger_case_id=revert.trigger_case_id,
                trigger_review_ids=[revert.trigger_review_id] if revert.trigger_review_id else [],
                reported_by=None,
                coordinator_reason=None,
                write_up_for_decision_id=decision_id,
                agent_run_json=record,
                proposed_on_day=run.current_day,
                proposed_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError as error:
                if not _violates_unique(
                    error,
                    "uq_review_threshold_proposals_write_up_for",
                    "write_up_for_decision_id",
                ):
                    raise
                return
            session.add(
                self._threshold_proposal_audit(
                    run, row, now, event_type="review_threshold_write_up_recorded"
                )
            )

    def _calibrate_safely(self, run_id: str, **arguments: Any) -> None:
        """`_calibrate_review_threshold`, after the review or rejection it follows has committed.

        A failure here must never turn a recorded human decision into a 500: it is logged for an
        operator and recorded as a discarded calibration (ids and the exception class only).
        """
        try:
            self._calibrate_review_threshold(run_id, **arguments)
        except Exception as error:
            agent_logger().warning(
                "threshold_calibration_failed",
                extra={
                    "structured_fields": {
                        "request_id": request_id_var.get(),
                        "loop": "review_threshold",
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                },
            )
            try:
                with self.sessions.begin() as session:
                    run = session.get(ScenarioRunRow, run_id)
                    if run is None:
                        return
                    session.add(
                        self._audit_row(
                            run.run_id,
                            "review_threshold_calibration_discarded",
                            "system",
                            person_id=run.person_id,
                            detail={
                                "reason": "error",
                                "error_type": type(error).__name__,
                                "trigger_case_id": arguments.get("trigger_case_id"),
                                "trigger_review_ids": list(arguments.get("trigger_review_ids", ())),
                            },
                        )
                    )
            except Exception:  # pragma: no cover - the log line above already carries the failure
                agent_logger().exception("threshold_calibration_discard_audit_failed")

    def _calibrate_review_threshold(
        self,
        run_id: str,
        *,
        trigger_case_id: str,
        trigger_review_ids: tuple[str, ...],
        reported_by: str | None,
        round_id: str | None = None,
        round_index: int = 1,
        round_rejection: ReviewThresholdRejectionReason | None = None,
        rejected_proposal: ReviewThreshold | None = None,
        task: Literal["calibrate", "tighten"] = "calibrate",
    ) -> None:
        """Read in its own session, propose with none open, store in a fresh transaction.

        With `LLM_ENABLED=false` this is exactly stage 1: the fixed rule proposes. With it on, the
        calibration agent runs in the no-session phase with the fixed rule's output as its
        fallback, and whichever proposer's output results is stored with the agent's run record.
        A retry after a rejection for any reason but `prefer_other_change` ends the round with the
        fixed rule's no-change and never consults the model: nothing new has been learned that a
        second loosening attempt could rest on.

        `task="tighten"` (stage 3) follows "this should have reached me sooner" with nothing
        loosened live: the fixed rule proposes one step sooner (`fixed_rule_tightening`, no cause),
        the agent's `tighten` task may propose that or no change, and approval is the normal flow.
        """
        agent_enabled = self.settings.llm_enabled
        agent_context: ThresholdEpisodeContext | None = None
        not_consulted: str | None = None
        with self.sessions() as session:
            episode = self._threshold_episode_context(
                session,
                run_id,
                trigger_case_id=trigger_case_id,
                trigger_review_ids=trigger_review_ids,
                reported_by=reported_by,
                round_id=round_id,
                round_index=round_index,
            )
            if episode is not None and agent_enabled:
                if task == "calibrate" and round_rejection not in (
                    None,
                    ReviewThresholdRejectionReason.PREFER_OTHER_CHANGE,
                ):
                    not_consulted = AGENT_NOT_CONSULTED_AFTER_REJECTION
                elif (
                    task == "calibrate"
                    and episode.trigger_predates_live
                    and episode.trigger_reason is OverrideReason.NOT_A_CONCERN
                ):
                    # The counting rule is about loosening, which only `not_a_concern` can
                    # support; any other reason is still classified by the agent, and Transaction
                    # B refuses a loosening on a stale trigger whatever the reason.
                    not_consulted = AGENT_NOT_CONSULTED_STALE_TRIGGER
                else:
                    try:
                        agent_context = self._threshold_agent_context(
                            session,
                            episode,
                            round_rejection=round_rejection,
                            rejected_proposal=rejected_proposal,
                        )
                    except Exception as error:  # noqa: BLE001 - the fixed rule still answers
                        # Not a provider failure: nothing was asked of a model. The operator log
                        # gets the text; the run record gets a code.
                        agent_logger().warning(
                            "threshold_agent_context_unavailable",
                            extra={
                                "structured_fields": {
                                    "request_id": request_id_var.get(),
                                    "loop": "review_threshold",
                                    "error_class": type(error).__name__,
                                    "error": str(error),
                                }
                            },
                        )
                        not_consulted = AGENT_CONTEXT_UNAVAILABLE
        if episode is None:
            return
        # No database session is open from here until Transaction B.
        output = (
            fixed_rule_tightening(live=episode.live, trigger=episode.trigger)
            if task == "tighten"
            else fixed_rule_output(
                live=episode.live,
                trigger_reason=episode.trigger_reason,
                trigger=episode.trigger,
                not_a_concern_alarms=episode.not_a_concern_alarms,
                today=episode.current_day,
                blocked_values=episode.blocked_values,
                round_rejection=round_rejection,
                rejected_proposal=rejected_proposal,
            )
        )
        if not agent_enabled:
            self._store_threshold_output(episode, output, task=task)
            return
        fallback = ThresholdAgentProposal.from_candidate(
            proposed=output.proposed,
            cause=output.cause,
            reasoning=output.reasoning,
            cited=output.cited,
        )
        if agent_context is None:
            run = threshold_fallback_run(
                settings=self.settings,
                task=task,
                mode=(
                    "fallback_error"
                    if not_consulted == AGENT_CONTEXT_UNAVAILABLE
                    else "fallback_disabled"
                ),
                reason=not_consulted or AGENT_CONTEXT_UNAVAILABLE,
                fallback=fallback,
            )
        else:
            run = self._plan_threshold_safely(agent_context, fallback=fallback, task=task)
        if run.mode == "agent" and run.proposal is not None:
            self._store_threshold_output(
                episode,
                run.proposal,
                proposer=ReviewThresholdProposer.AGENT,
                agent_run=run.as_evidence(),
                mode=run.mode,
                fallback_output=output,
                task=task,
            )
            return
        self._store_threshold_output(
            episode,
            output,
            proposer=ReviewThresholdProposer.FIXED_RULE,
            agent_run=run.as_evidence(),
            mode=run.mode,
            task=task,
        )

    def _plan_threshold_safely(
        self,
        context: ThresholdEpisodeContext,
        *,
        fallback: ThresholdAgentProposal,
        task: Literal["calibrate", "tighten"] = "calibrate",
    ) -> ThresholdPlanRun:
        """Run the calibration agent, and always return a run record.

        `plan_threshold_calibration` degrades every failure it anticipates; anything else (a
        transport raising outside `messages.create`, a factory that throws) is the same documented
        outcome -- the fixed rule's output, recorded as `fallback_error` with the exception's class
        for a provider or transport failure and `AGENT_RUN_FAILED` for anything else
        (`run_failure_reason`); the text goes only to the operator log.
        """
        injected = (
            {"client_factory": self._threshold_client_factory}
            if self._threshold_client_factory is not None
            else {}
        )
        planner = plan_threshold_tightening if task == "tighten" else plan_threshold_calibration
        try:
            return planner(context, settings=self.settings, fallback=fallback, **injected)
        except Exception as error:  # noqa: BLE001 - must degrade, never lose the review
            return threshold_fallback_run(
                settings=self.settings,
                task=task,
                mode="fallback_error",
                reason=run_failure_reason(error),
                fallback=fallback,
                client_requested=True,
            )

    def _threshold_agent_context(
        self,
        session: Session,
        episode: _ThresholdEpisode,
        *,
        round_rejection: ReviewThresholdRejectionReason | None,
        rejected_proposal: ReviewThreshold | None,
    ) -> ThresholdEpisodeContext:
        """Gather one person's calibration inputs in the read session and alias them."""
        run = session.get(ScenarioRunRow, episode.run_id)
        if run is None:  # pragma: no cover - `_threshold_episode_context` already checked
            raise KeyError(episode.run_id)
        return self._threshold_context_for(
            session,
            run,
            today=episode.current_day,
            live=episode.live,
            trigger_review_id=episode.trigger_review_ids[-1],
            coordinator_reason=episode.trigger_reason,
            blocked_values=episode.blocked_values,
            round_rejection=round_rejection,
            rejected_proposal=rejected_proposal,
        )

    def _threshold_context_for(
        self,
        session: Session,
        run: ScenarioRunRow,
        *,
        today: date,
        live: ReviewThreshold,
        trigger_review_id: str | None,
        coordinator_reason: OverrideReason | None,
        blocked_values: frozenset[ReviewThreshold],
        round_rejection: ReviewThresholdRejectionReason | None = None,
        rejected_proposal: ReviewThreshold | None = None,
        reversal: ReversalInput | None = None,
    ) -> ThresholdEpisodeContext:
        """One person's agent inputs, gathered in a read session and aliased (every task).

        Everything is scoped to the run, so no alias can name another person's evidence. Stated
        explanations, context answers and day disputes are never read here (see
        `agent.threshold_tools`).
        """
        facts = self._threshold_facts(session, run.run_id)
        signals = self._threshold_day_signals(
            session, run, last_n=REPLAY_WINDOW_DAYS, include_self_reports=False
        )
        readings = (
            {
                row.day: row
                for row in session.scalars(
                    select(DailyMetricRow).where(
                        DailyMetricRow.run_id == run.run_id,
                        DailyMetricRow.day >= signals[0].day,
                    )
                )
            }
            if signals
            else {}
        )
        days: list[EpisodeDayInput] = []
        for entry in signals:
            reading = readings[entry.day]
            context = ContextSignal.model_validate(reading.context_json)
            days.append(
                EpisodeDayInput(
                    day=entry.day,
                    evidence_id=reading.evidence_id,
                    steps=entry.signal.current_steps,
                    interpretable=entry.signal.quality.safe_to_interpret,
                    percent_below_baseline=round(abs(min(0.0, entry.signal.delta_percent)), 1),
                    sustained_low_days=entry.signal.sustained_low_days,
                    live_setting_asks=review_fires(entry.signal, live),
                    rainy=context.rainy,
                    holiday=context.holiday,
                )
            )
        # Ordered by what happened, never by uuid: a replay of the same flow must number its
        # aliases identically (recorded requests are keyed on the exact prompt).
        review_rows = sorted(
            session.execute(
                select(CaseReviewRow, ReviewCaseRow)
                .join(ReviewCaseRow, ReviewCaseRow.case_id == CaseReviewRow.case_id)
                .where(CaseReviewRow.run_id == run.run_id)
            ).all(),
            key=lambda pair: (
                _as_utc(pair[0].recorded_at),
                pair[1].opened_day or date.min,
                pair[0].status,
                pair[0].human_action or "",
                pair[0].override_reason or "",
                pair[0].reviewer,
                pair[0].note,
            ),
        )
        reviews = [
            ReviewInput(
                review_id=review.review_id,
                case_id=case.case_id,
                case_evidence_id=case.decision_evidence_id,
                case_opened_day=case.opened_day,
                status=review.status,
                by_system=review.reviewer == "system",
                by_demo_script=review.reviewer == "demo-script",
                human_action=review.human_action,
                override_reason=review.override_reason,
                reached_too_late=review.reached_too_late,
                note=review.note,
                is_trigger=review.review_id == trigger_review_id,
            )
            for review, case in review_rows
        ]
        decision_rows = self._threshold_decision_rows(session, run.run_id)
        approvals = {
            fact.decision_id: fact
            for fact in facts
            if fact.kind is ReviewThresholdDecisionKind.APPROVED and fact.after is not None
        }
        reverted_from: dict[str, tuple[ReviewThreshold, ...]] = {}
        for fact in facts:
            if fact.kind is not ReviewThresholdDecisionKind.REVERTED:
                continue
            # What this revert went back from: the value live before it, and the value of the
            # approval it ended (the same two `reverted_away_values` blocks, per revert).
            away = [fact.previous]
            ended = approvals.get(fact.ends_approval_id or "")
            if ended is not None and ended.after is not None and ended.after not in away:
                away.append(ended.after)
            reverted_from[fact.decision_id] = tuple(away)
        proposal_rows = self._threshold_proposal_rows(session, run.run_id)
        round_of = {row.proposal_id: row.round_index or 0 for row in proposal_rows}
        timeline: list[tuple[tuple[Any, ...], ThresholdHistoryInput]] = []

        def value_key(severity: int | None, persistence: int | None) -> tuple[int, int]:
            return (severity if severity is not None else -1, persistence or -1)

        for row in decision_rows:
            timeline.append(
                (
                    (
                        row.decided_on_day,
                        _as_utc(row.decided_at),
                        _HISTORY_KIND_ORDER.get(row.kind, len(_HISTORY_KIND_ORDER)),
                        round_of.get(row.proposal_id or "", 0),
                        row.kind,
                        value_key(row.previous_severity_pct, row.previous_persistence_days),
                        value_key(row.severity_pct, row.persistence_days),
                        row.revert_trigger or "",
                        row.rejection_reason or "",
                    ),
                    ThresholdHistoryInput(
                        evidence_id=row.decision_id,
                        record="decision",
                        kind=row.kind,
                        day=row.decided_on_day,
                        previous=ReviewThreshold(
                            row.previous_severity_pct, row.previous_persistence_days
                        ),
                        after=(
                            ReviewThreshold(row.severity_pct, row.persistence_days)
                            if row.severity_pct is not None and row.persistence_days is not None
                            else None
                        ),
                        revert_trigger=row.revert_trigger,
                        rejection_reason=row.rejection_reason,
                        note=row.note,
                        reverted_away_from=reverted_from.get(row.decision_id, ()),
                    ),
                )
            )
        for row in proposal_rows:
            timeline.append(
                (
                    (
                        row.proposed_on_day,
                        _as_utc(row.proposed_at),
                        _HISTORY_KIND_ORDER.get(row.output_kind, len(_HISTORY_KIND_ORDER)),
                        row.round_index or 0,
                        row.output_kind,
                        value_key(row.previous_severity_pct, row.previous_persistence_days),
                        value_key(row.proposed_severity_pct, row.proposed_persistence_days),
                        row.proposer,
                        row.cause or "",
                    ),
                    ThresholdHistoryInput(
                        evidence_id=row.proposal_id,
                        record="output",
                        kind=row.output_kind,
                        day=row.proposed_on_day,
                        previous=ReviewThreshold(
                            row.previous_severity_pct, row.previous_persistence_days
                        ),
                        after=self._proposed_threshold(row),
                        proposer=row.proposer,
                        cause=row.cause,
                        write_up=(
                            row.reasoning
                            if row.output_kind == ReviewThresholdOutputKind.WRITE_UP.value
                            else None
                        ),
                        reasoning=(
                            row.reasoning
                            if row.output_kind != ReviewThresholdOutputKind.WRITE_UP.value
                            else None
                        ),
                    ),
                )
            )
        timeline.sort(key=lambda item: item[0])
        window = [entry.day for entry in signals]
        variability_ids = (
            [readings[window[0]].evidence_id, readings[window[-1]].evidence_id] if window else []
        )
        return build_threshold_episode_context(
            today=today,
            live=live,
            coordinator_reason=coordinator_reason,
            days=days,
            variability=variability_summary(signals),
            variability_evidence_ids=variability_ids,
            reviews=reviews,
            history=[item[1] for item in timeline],
            facts=facts,
            blocked_values=blocked_values,
            cooldown_until_day=cooldown_until(facts),
            round_rejection=round_rejection,
            rejected_proposal=rejected_proposal,
            reversal=reversal,
        )

    def _store_threshold_output(
        self,
        episode: _ThresholdEpisode,
        output: _ThresholdCandidate,
        *,
        proposer: ReviewThresholdProposer = ReviewThresholdProposer.FIXED_RULE,
        agent_run: dict[str, object] | None = None,
        mode: str = "fallback_disabled",
        fallback_output: _ThresholdCandidate | None = None,
        task: Literal["calibrate", "tighten"] = "calibrate",
    ) -> None:
        """Transaction B: re-check, re-run the guardrail on fresh facts, store one output row.

        `proposer`, `agent_run` and `mode` describe whichever calibrator produced `output`; with
        none given it is the fixed rule, recorded as `fallback_disabled`.

        An agent's output must come with `fallback_output`, the fixed rule's output for the same
        episode. If the guardrail refuses the agent's output here, the fixed rule's is judged and
        stored instead (`proposer=fixed_rule`), and the run record says so: `mode=fallback_error`,
        `fallback_reason="AGENT_OUTPUT_REFUSED <violations>"`. No agent row is ever stored without
        a cause.

        A loosening whose trigger case opened before the live setting took effect is refused
        whoever proposed it (`VIOLATION_STALE_TRIGGER`).
        """
        if proposer is ReviewThresholdProposer.AGENT and fallback_output is None:
            raise ValueError(
                "An agent output is stored only with the fixed rule's as its fallback."
            )
        with self.sessions.begin() as session:
            # Locked like every review-setting writer: two calibrations for the same run
            # serialise here on PostgreSQL, so the snapshot below is read by one writer at a
            # time. The lock is per run, so the weekly cap is not airtight: one coordinator's
            # concurrent reviews of *different* seniors can each read the count before the other
            # commits and exceed the cap by a proposal or two on PostgreSQL. Accepted for the
            # proof of concept; a per-coordinator lock would close it. A no-op on SQLite.
            run = self._lock_threshold_run(session, episode.run_id)
            now = self._threshold_clock(session, run.run_id, _utcnow())

            def discard(reason: str) -> None:
                # Something moved between the read and this write -- a decision, another
                # proposal, consent, the simulated day, or the reporter's weekly cap. The output
                # was computed against a state that no longer holds, so it is dropped, on record.
                session.add(
                    self._audit_row(
                        run.run_id,
                        "review_threshold_calibration_discarded",
                        "system",
                        person_id=run.person_id,
                        detail={
                            "reason": reason,
                            "mode": mode,
                            "proposer": proposer.value,
                            "trigger_case_id": episode.trigger_case_id,
                            "trigger_review_ids": list(episode.trigger_review_ids),
                        },
                        at=now,
                    )
                )

            if not run.active:
                discard("run_inactive")
                return
            if self._threshold_snapshot(session, run) != episode.snapshot:
                discard("state_changed")
                return
            facts = self._threshold_facts(session, run.run_id)
            live_state = resolve_live_threshold(facts, run.current_day)
            live = live_state.threshold
            known_ids = self._threshold_known_evidence_ids(session, run.run_id)
            trigger_case = session.get(ReviewCaseRow, episode.trigger_case_id)
            trigger_predates_live = self._trigger_predates_live(
                trigger_case.opened_day if trigger_case is not None else None, live_state
            )

            def judge(candidate: _ThresholdCandidate, *, by_agent: bool) -> ThresholdVerdict:
                loosening = candidate.proposed is not None and candidate.proposed.looser_than(live)
                structure: dict[str, Any] = {
                    "live": live,
                    "proposed": candidate.proposed,
                    "cause": candidate.cause,
                    "cited_evidence_ids": candidate.cited,
                    "known_evidence_ids": known_ids,
                    "coordinator_reason": episode.trigger_reason,
                    "facts": facts,
                    "today": run.current_day,
                    # The fixed rule's cause-less outputs ("waits for a second") are legitimate;
                    # any other proposer, and any loosening, must name a cause.
                    "require_cause": loosening or by_agent,
                }
                # An agent's reasoning is model-written, coordinator-facing prose, so it is held to
                # the wording rule (9) here as well as inside the loop. The fixed rule's reasoning
                # is fixed templates and stays on the structural rules exactly as in stage 1.
                verdict = (
                    validate_threshold_output(reasoning=candidate.reasoning, **structure)
                    if by_agent
                    else validate_threshold_structure(**structure)
                )
                if loosening and trigger_predates_live:
                    verdict = ThresholdVerdict(
                        approved=False, violations=(*verdict.violations, VIOLATION_STALE_TRIGGER)
                    )
                return verdict

            by_agent = proposer is ReviewThresholdProposer.AGENT
            verdict = judge(output, by_agent=by_agent)
            record = agent_run
            if by_agent and not verdict.approved and fallback_output is not None:
                # The agent's output no longer passes on fresh facts: the fixed rule answers.
                refused = verdict.violations
                output = fallback_output
                proposer = ReviewThresholdProposer.FIXED_RULE
                mode = "fallback_error"
                verdict = judge(output, by_agent=False)
                reason = " ".join((AGENT_OUTPUT_REFUSED, *refused))
                prior = dict(agent_run or {})
                earlier = prior.get("guardrail_rejections")
                rejections = [*(earlier if isinstance(earlier, list) else []), *refused]
                record = {
                    **prior,
                    "mode": mode,
                    "trace_detail": f"Fixed rule used ({mode}); {reason}",
                    "guardrail_rejections": rejections,
                    "guardrail_violation_count": len(rejections),
                    "fallback_reason": reason,
                    "agent_reasoning": None,
                }
            output_kind = output.output_kind
            proposed = output.proposed
            cause = output.cause
            reasoning = output.reasoning
            if not verdict.approved and proposed is not None:
                # The candidate has to pass the same gate whoever proposed it. A refused candidate
                # is kept as a considered no-change, so the card can say why nothing was proposed.
                output_kind = ReviewThresholdOutputKind.NO_CHANGE
                proposed = None
                cause = None
                reasoning = FIXED_RULE_REFUSED + " " + " ".join(verdict.violations)
            if (
                output_kind is ReviewThresholdOutputKind.PROPOSAL
                and episode.reported_by is not None
                and self._proposals_this_week(session, episode.reported_by, now)
                >= WEEKLY_PROPOSAL_CAP
            ):
                discard("weekly_cap")
                return
            if record is None:
                record = self._fixed_rule_run_record(now, violations=verdict.violations, task=task)
            elif not verdict.approved:
                # The fixed rule's output was itself refused here while a calibration-agent record
                # exists: its violations join the record's, so the card counts every refusal.
                earlier = record.get("guardrail_rejections")
                rejections = [*(earlier if isinstance(earlier, list) else []), *verdict.violations]
                record = {
                    **record,
                    "guardrail_rejections": rejections,
                    "guardrail_violation_count": len(rejections),
                }
            # Whatever produced the record, its `cause` is the stored row's.
            record = {**record, "cause": cause.value if cause else None}
            row = ReviewThresholdProposalRow(
                proposal_id=_id("threshold_proposal"),
                run_id=run.run_id,
                person_id=run.person_id,
                output_kind=output_kind.value,
                proposer=proposer.value,
                round_id=episode.round_id,
                round_index=episode.round_index,
                previous_severity_pct=live.severity_pct,
                previous_persistence_days=live.persistence_days,
                proposed_severity_pct=proposed.severity_pct if proposed else None,
                proposed_persistence_days=proposed.persistence_days if proposed else None,
                cause=cause.value if cause else None,
                reasoning=reasoning,
                cited_evidence_ids=list(output.cited),
                trigger_case_id=episode.trigger_case_id,
                trigger_review_ids=list(episode.trigger_review_ids),
                reported_by=episode.reported_by,
                coordinator_reason=episode.trigger_reason.value if episode.trigger_reason else None,
                write_up_for_decision_id=None,
                agent_run_json=record,
                proposed_on_day=run.current_day,
                proposed_at=now,
            )
            session.add(row)
            session.flush()
            session.add(self._threshold_proposal_audit(run, row, now))

    def _threshold_proposal_audit(
        self,
        run: ScenarioRunRow,
        row: ReviewThresholdProposalRow,
        now: datetime,
        event_type: str = "review_threshold_proposed",
    ) -> AuditEventRow:
        """Ids, kinds and values. Never the reasoning (coordinator-facing, on the row only)."""
        agent_run = row.agent_run_json or {}
        actor = (
            row.reported_by or "coordinator"
            if row.proposer == ReviewThresholdProposer.COORDINATOR.value
            else "system"
        )
        return self._audit_row(
            run.run_id,
            event_type,
            actor,
            person_id=run.person_id,
            detail={
                "proposal_id": row.proposal_id,
                "output_kind": row.output_kind,
                "proposer": row.proposer,
                "cause": row.cause,
                "previous": {
                    "severity_pct": row.previous_severity_pct,
                    "persistence_days": row.previous_persistence_days,
                },
                "proposed": (
                    {
                        "severity_pct": row.proposed_severity_pct,
                        "persistence_days": row.proposed_persistence_days,
                    }
                    if row.proposed_severity_pct is not None
                    else None
                ),
                "round_id": row.round_id,
                "round_index": row.round_index,
                "trigger_case_id": row.trigger_case_id,
                "trigger_review_ids": list(row.trigger_review_ids),
                "cited_evidence_ids": list(row.cited_evidence_ids),
                "write_up_for_decision_id": row.write_up_for_decision_id,
                "agent_evidence_id": agent_run.get("agent_evidence_id"),
                "mode": agent_run.get("mode"),
                "guardrail_violation_count": agent_run.get("guardrail_violation_count", 0),
            },
            at=now,
        )

    def _reject_open_threshold_proposals_for_consent(
        self, session: Session, run: ScenarioRunRow, day: date, now: datetime
    ) -> list[str]:
        """Close every open review-setting proposal once the person withdraws consent."""
        rejected: list[str] = []
        for proposal in self._open_threshold_proposals(session, run.run_id):
            row = self._add_threshold_decision(
                session,
                run,
                kind=ReviewThresholdDecisionKind.REJECTED,
                previous=ReviewThreshold(
                    proposal.previous_severity_pct, proposal.previous_persistence_days
                ),
                after=self._proposed_threshold(proposal),
                decided_by="system",
                now=now,
                decided_on_day=day,
                proposal_id=proposal.proposal_id,
                rejection_reason=ReviewThresholdRejectionReason.CONSENT_WITHDRAWN,
                trigger_case_id=proposal.trigger_case_id,
            )
            session.add(
                self._threshold_decision_audit(run, "review_threshold_rejected", "system", row, now)
            )
            rejected.append(row.decision_id)
        return rejected

    def _apply_review_threshold_daily_checks(
        self,
        session: Session,
        run: ScenarioRunRow,
        state: PersonState,
        now: datetime,
        *,
        created_case: ReviewCase | None = None,
    ) -> list[str]:
        """The review-setting facts only `advance()`'s write phase records.

        - A looser setting whose 60 days ran out: expiry already applied statelessly in the fold,
          so this writes the `expired` row that day, for the audit trail and the notice -- only
          when the fold really moved off that approval today (a reconfirmation keeps it).
        - A shadow-check review: revert to the starting setting from the next simulated day,
          ending every approval on the stack with its own row, so each value counts as reverted
          away from.
        - A case created today, within `CHECKING_PERIOD_DAYS` of the live loosening taking
          effect, that opened `FAR_MORE_SEVERE_PCT` or more below baseline or through the floor:
          revert by the never-ask-later walk (`far_more_severe`), from the next simulated day --
          unless the shadow check already cleared the day, which wins (it restores the starting
          setting); that is audited as `review_threshold_far_more_severe_superseded`.
        - Any revert or expiry: open proposals made against a value that will not be live
          tomorrow are rejected as `superseded`.
        - The first day a still-live loosening is live on or after its checking period's end
          (the end day itself, or later when a looser approval covered it and was then reverted):
          `check_confirmed` with no false alarms on cases opened in its own period and no trigger
          fired, else `check_unresolved`. Changes nothing about the live value.

        Idempotent per day: the day's advance is single-winner, and `ends_approval_id` is unique
        (a lost race is a savepoint rollback, not a failed day).
        """
        facts = self._threshold_facts(session, run.run_id)
        if not facts:
            return []
        # The run row is already locked: `advance()`'s write phase takes the lock before any insert.
        today = state.current_day
        ended = {fact.ends_approval_id for fact in facts if fact.ends_approval_id}
        written: list[str] = []

        yesterday = resolve_live_threshold(facts, today - timedelta(days=1))
        live_today = resolve_live_threshold(facts, today)
        if (
            yesterday.approval_id is not None
            and yesterday.loosened
            and yesterday.expires_on_day is not None
            and today >= yesterday.expires_on_day
            and live_today.approval_id != yesterday.approval_id
            and yesterday.approval_id not in ended
        ):
            # The fold's stateless expiry never lands on a value that asks later than the one that
            # lapsed (it keeps popping; pinned by the random-stack property test). This row only
            # records what already happened.
            row = self._end_threshold_approval(
                session,
                run,
                kind=ReviewThresholdDecisionKind.EXPIRED,
                ends_approval_id=yesterday.approval_id,
                previous=yesterday.threshold,
                after=live_today.threshold,
                event_type="review_threshold_expired",
                now=now,
                decided_on_day=today,
                effective_from_day=yesterday.expires_on_day,
                extra={
                    "lapsed_approval_ids": self._lapsed_approval_ids(
                        facts, yesterday, live_today, today, now
                    )
                },
            )
            if row is not None:
                facts.append(self._threshold_fact(row))
                ended.add(yesterday.approval_id)
                written.append(row.decision_id)

        # Decided against the facts as they stand before either revert of the day. The shadow
        # check runs first and wins: it clears to the starting setting, which asks no later than
        # anything the far-more-severe walk could restore.
        far_more_severe_approval: str | None = None
        if created_case is not None:
            live = resolve_live_threshold(facts, today)
            approval = next((fact for fact in facts if fact.decision_id == live.approval_id), None)
            if (
                approval is not None
                and live.loosened
                and approval.decision_id not in ended
                and within_checking_period(approval, today)
                and far_more_severe(
                    state.signal.delta_percent,
                    reached_floor=state.decided_by_gate == PolicyGate.REVIEW_FLOOR,
                )
            ):
                far_more_severe_approval = approval.decision_id

        shadow_written: list[str] = []
        if (
            state.decided_by_gate == PolicyGate.SHADOW_CHECK
            and state.last_decision == Decision.COORDINATOR_REVIEW
        ):
            live = resolve_live_threshold(facts, today)
            # Tomorrow's stack, not today's: an approval decided for tomorrow while this advance
            # was in its planner window is cleared too, and an approval already ended for tomorrow
            # is not ended twice. Every approval still on it gets its own ending row (top first;
            # the last, decisive row records the change the person lives), so every value it held
            # counts as reverted away from and every calibrator approval is owed a write-up.
            stack = approval_stack(facts, today=today + timedelta(days=1), decided_at=now)
            # The shadow check only runs for a setting looser than the starting setting, and with no
            # mixed settings the starting setting then asks no later in either dimension. Checked
            # for every value anyway: a revert that would ask later is never written.
            skip_reason = (
                "nothing_to_clear"
                if not stack
                else None
                if all(never_later(DEFAULT_REVIEW_THRESHOLD, held) for _, held in stack)
                else "starting_setting_asks_later"
            )
            if skip_reason is not None:
                session.add(
                    self._audit_row(
                        run.run_id,
                        "review_threshold_revert_skipped",
                        "system",
                        person_id=run.person_id,
                        detail={
                            "reason": skip_reason,
                            "revert_trigger": ReviewThresholdRevertTrigger.SHADOW_CHECK.value,
                            "live_approval_id": live.approval_id,
                            "day": today.isoformat(),
                        },
                        at=now,
                    )
                )
            else:
                open_case_id = session.scalar(
                    select(ReviewCaseRow.case_id)
                    .where(
                        ReviewCaseRow.run_id == run.run_id,
                        ReviewCaseRow.status != CaseStatus.RESOLVED.value,
                    )
                    .order_by(ReviewCaseRow.opened_at.desc(), ReviewCaseRow.case_id.desc())
                    .limit(1)
                )
                for index, (approval_id, held) in enumerate(stack):
                    decisive = index == len(stack) - 1
                    row = self._end_threshold_approval(
                        session,
                        run,
                        kind=ReviewThresholdDecisionKind.REVERTED,
                        ends_approval_id=approval_id,
                        previous=live.threshold if decisive else held,
                        after=DEFAULT_REVIEW_THRESHOLD,
                        event_type="review_threshold_reverted",
                        now=now + timedelta(microseconds=20 + index),
                        decided_on_day=today,
                        revert_trigger=ReviewThresholdRevertTrigger.SHADOW_CHECK,
                        trigger_case_id=open_case_id,
                    )
                    if row is not None:
                        shadow_written.append(row.decision_id)
                written.extend(shadow_written)

        if far_more_severe_approval is not None and created_case is not None:
            if shadow_written:
                session.add(
                    self._audit_row(
                        run.run_id,
                        "review_threshold_far_more_severe_superseded",
                        "system",
                        person_id=run.person_id,
                        detail={
                            "reason": "shadow_check_cleared",
                            "live_approval_id": far_more_severe_approval,
                            "trigger_case_id": created_case.case_id,
                            "shadow_revert_ids": list(shadow_written),
                        },
                        at=now,
                    )
                )
            else:
                written.extend(
                    self._revert_never_later(
                        session,
                        run,
                        now + timedelta(microseconds=10),
                        trigger=ReviewThresholdRevertTrigger.FAR_MORE_SEVERE,
                        trigger_case_id=created_case.case_id,
                        trigger_review_id=None,
                    )
                )
        closed = self._close_checking_period(session, run, today, now)
        if written:
            self._supersede_stale_threshold_proposals(
                session,
                run,
                today,
                now,
                target=resolve_live_threshold(
                    self._threshold_facts(session, run.run_id), today + timedelta(days=1)
                ).threshold,
            )
        return written + closed

    def _close_checking_period(
        self, session: Session, run: ScenarioRunRow, today: date, now: datetime
    ) -> list[str]:
        """`check_confirmed` / `check_unresolved` for a loosening still live, and not ending,
        on the first advance on or after its checking period's end, counted over its own period
        (`[effective_from_day, checking_until)`), frozen in the `review_threshold_check_closed`
        audit detail. Written once: never twice for one approval."""
        facts = self._threshold_facts(session, run.run_id)
        live = resolve_live_threshold(facts, today)
        tomorrow = resolve_live_threshold(facts, today + timedelta(days=1))
        approval = next((fact for fact in facts if fact.decision_id == live.approval_id), None)
        if (
            approval is None
            or approval.after is None
            or not live.loosened
            or tomorrow.approval_id != approval.decision_id
            or today < checking_until(approval)
            or any(
                fact.kind
                in (
                    ReviewThresholdDecisionKind.CHECK_CONFIRMED,
                    ReviewThresholdDecisionKind.CHECK_UNRESOLVED,
                )
                and fact.affects_decision_id == approval.decision_id
                for fact in facts
            )
        ):
            return []
        # Over the period itself, `[effective_from_day, checking_until)`: a case opened on the close
        # day belongs to after it. The counted result is frozen in the close audit and read back.
        last_day = checking_until(approval) - timedelta(days=1)
        false_alarms = self._false_alarms_since(session, run, approval.effective_from_day, last_day)
        fired = self._checking_triggers_fired(session, run, approval, last_day)
        kind = (
            ReviewThresholdDecisionKind.CHECK_CONFIRMED
            if false_alarms == 0 and not fired
            else ReviewThresholdDecisionKind.CHECK_UNRESOLVED
        )
        row = self._add_threshold_decision(
            session,
            run,
            kind=kind,
            previous=approval.previous,
            after=approval.after,
            decided_by="system",
            now=now + timedelta(microseconds=40),
            decided_on_day=today,
            affects_decision_id=approval.decision_id,
        )
        session.add(
            self._threshold_decision_audit(
                run,
                "review_threshold_check_closed",
                "system",
                row,
                now,
                {"false_alarms_since": false_alarms, "trigger_fired": fired},
            )
        )
        return [row.decision_id]

    @staticmethod
    def _false_alarms_since(session: Session, run: ScenarioRunRow, since: date, until: date) -> int:
        """False-alarm reviews on this run's cases opened within `[since, until]`."""
        return sum(
            1
            for review, case in session.execute(
                select(CaseReviewRow, ReviewCaseRow)
                .join(ReviewCaseRow, ReviewCaseRow.case_id == CaseReviewRow.case_id)
                .where(CaseReviewRow.run_id == run.run_id)
            ).all()
            if case.opened_day is not None
            and since <= case.opened_day <= until
            and is_false_alarm(review.status, review.human_action, review.override_reason)
        )

    @staticmethod
    def _checking_triggers_fired(
        session: Session, run: ScenarioRunRow, approval: ThresholdDecisionFact, until: date
    ) -> bool:
        """Whether anything that reverts a loosening fired during `[effective_from_day, until]`
        without reverting it: a "should have reached me sooner" mark on a case opened in that span,
        or an audited revert skip for that approval decided on a day in it."""
        marked = any(
            case.opened_day is not None
            and approval.effective_from_day <= case.opened_day <= until
            and bool(review.reached_too_late)
            for review, case in session.execute(
                select(CaseReviewRow, ReviewCaseRow)
                .join(ReviewCaseRow, ReviewCaseRow.case_id == CaseReviewRow.case_id)
                .where(CaseReviewRow.run_id == run.run_id)
            ).all()
        )
        if marked:
            return True

        def in_span(detail: dict[str, Any]) -> bool:
            day = detail.get("day")
            if not isinstance(day, str):
                return False
            return approval.effective_from_day <= date.fromisoformat(day) <= until

        return any(
            (event.detail_json or {}).get("live_approval_id") == approval.decision_id
            and in_span(event.detail_json or {})
            for event in session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id == run.run_id,
                    AuditEventRow.event_type == "review_threshold_revert_skipped",
                )
            )
        )

    @staticmethod
    def _lapsed_approval_ids(
        facts: list[ThresholdDecisionFact],
        yesterday: LiveReviewThreshold,
        live_today: LiveReviewThreshold,
        today: date,
        now: datetime,
    ) -> list[str]:
        """Every approval whose clock ran out by `today`, top first -- more than one when a looser
        setting beneath the one that lapsed had also run out (stateless expiry pops them all)."""
        lapsed: list[str] = []
        cursor = list(facts)
        current = yesterday
        while (
            current.approval_id is not None
            and current.approval_id != live_today.approval_id
            and current.approval_id not in lapsed
            and current.loosened
            and current.expires_on_day is not None
            and today >= current.expires_on_day
        ):
            lapsed.append(current.approval_id)
            cursor.append(
                ThresholdDecisionFact(
                    decision_id=f"lapsed_{current.approval_id}",
                    kind=ReviewThresholdDecisionKind.EXPIRED,
                    previous=current.threshold,
                    after=None,
                    decided_on_day=today - timedelta(days=1),
                    effective_from_day=today - timedelta(days=1),
                    decided_at=now,
                    ends_approval_id=current.approval_id,
                )
            )
            current = resolve_live_threshold(cursor, today - timedelta(days=1))
        return lapsed

    @staticmethod
    def _proposed_threshold(row: ReviewThresholdProposalRow) -> ReviewThreshold | None:
        if row.proposed_severity_pct is None or row.proposed_persistence_days is None:
            return None
        return ReviewThreshold(row.proposed_severity_pct, row.proposed_persistence_days)

    def lookup_person_for_sub(self, sub: str) -> str | None:
        with self.sessions() as session:
            row = session.scalar(
                select(AuthUserPersonLinkRow).where(AuthUserPersonLinkRow.sub == sub)
            )
            return row.person_id if row else None

    def upsert_person_link(self, sub: str, person_id: str, created_by: str) -> None:
        now = _utcnow()
        try:
            with self.sessions.begin() as session:
                existing = session.scalar(
                    select(AuthUserPersonLinkRow).where(AuthUserPersonLinkRow.sub == sub)
                )
                if existing is None:
                    session.add(
                        AuthUserPersonLinkRow(
                            sub=sub,
                            person_id=person_id,
                            created_at=now,
                            created_by=created_by,
                        )
                    )
        except IntegrityError:
            pass  # Concurrent insert for the same sub; the link already exists

    @staticmethod
    def _planner_observability(
        session: Session,
        run_id: str,
        *,
        interventions: Sequence[InterventionRow] | None = None,
    ) -> dict[str, object]:
        """Aggregate what the outreach planner already recorded on every intervention.

        `_finalize_intervention` stores the deterministic ranker's choice (`deterministic_
        candidate_key`) alongside the one actually sent (`candidate_key`), plus the planner's own
        `agent` record. None of it has ever been read back. Counting the agreement between those
        two keys is an agent-versus-baseline comparison over live data, and the guardrail
        counters turn "the safety rules work" into a number.

        Interventions created before the planner existed carry no `agent` block and are simply
        not counted, so the denominator is always "runs where a planner decision was possible".

        `interventions`, the run's rows when the caller already read them, saves reading them again.
        """
        rows = (
            list(interventions)
            if interventions is not None
            else session.scalars(
                select(InterventionRow).where(InterventionRow.run_id == run_id)
            ).all()
        )
        runs = 0
        agent_selected = 0
        agreed = 0
        modes: dict[str, int] = {}
        rejections = 0
        violations = 0
        contested = 0
        for row in rows:
            evidence = row.evidence_json or {}
            agent = evidence.get("agent")
            if not isinstance(agent, dict):
                continue
            runs += 1
            mode = str(agent.get("mode", "unknown"))
            modes[mode] = modes.get(mode, 0) + 1
            rejections += int(agent.get("rejected_proposal_count") or 0)
            violations += int(agent.get("guardrail_violation_count") or 0)
            if mode != "agent":
                continue
            agent_selected += 1
            ranking = evidence.get("candidate_ranking")
            if isinstance(ranking, list) and len(ranking) >= 2:
                contested += 1
            deterministic = evidence.get("deterministic_candidate_key")
            if deterministic is not None and deterministic == evidence.get("candidate_key"):
                agreed += 1
        return {
            "planner_runs": runs,
            "planner_agent_selected": agent_selected,
            "planner_contested_runs": contested,
            "planner_agreed_with_ranker": agreed,
            "planner_fallback_modes": modes,
            "planner_guardrail_rejections": rejections,
            "planner_guardrail_violations": violations,
        }

    @staticmethod
    def _llm_cost_observability(
        session: Session,
        run_id: str,
        *,
        interventions: Sequence[InterventionRow] | None = None,
        search_events: Sequence[AuditEventRow] | None = None,
    ) -> dict[str, object]:
        """What the model actually cost this run, across all three LLM entry points.

        `_planner_observability` above answers "did the planner agree with the ranker"; this
        answers "how often was a model consulted, for how long, for how many tokens, and where
        did it fall back". Both read evidence that is already written and was never read back:
        the outreach planner's `agent` block on `InterventionRow`, and the activity-search audit
        detail's own `agent` and `intent` blocks.

        Three deliberate choices:

        * `llm_calls` counts *runs that reached a model*, not iterations and not opportunities.
          A `fallback_disabled` run never reached one and is not counted, which keeps the
          denominator of every cost number honest under `LLM_ENABLED=false` -- where all of
          these are zero, and should be.
        * `llm_fallbacks_by_mode` counts every run by its mode, including `agent`, so the modes
          sum to the number of runs and a reader can never quote a fallback count without its
          denominator.
        * `guardrail_rejections_by_rule` classifies the recorded violation prose through
          `agent.guardrail_rules`; an unrecognised violation lands under `other` rather than
          being dropped.

        Counts and sums only. No rates, no prices -- per docs/observability.md.

        `interventions` and `search_events`, the run's rows when the caller already read them, save
        reading them again.
        """
        calls = 0
        latency_ms_total = 0
        tokens_total = 0
        modes: dict[str, int] = {}
        rejections_by_rule: dict[str, int] = {}

        def absorb_agent_block(agent: object) -> None:
            nonlocal calls, latency_ms_total, tokens_total
            if not isinstance(agent, dict):
                return
            mode = str(agent.get("mode", "unknown"))
            modes[mode] = modes.get(mode, 0) + 1
            for rule, count in count_violations_by_rule(agent.get("guardrail_rejections")).items():
                rejections_by_rule[rule] = rejections_by_rule.get(rule, 0) + count
            if mode == "fallback_disabled":
                # No client was ever built, so no call was made and no time was spent waiting on
                # one; counting it would inflate every per-call number with runs that never ran.
                return
            calls += 1
            latency_ms_total += int(agent.get("latency_ms") or 0)
            tokens_total += int(agent.get("total_tokens") or 0)

        for intervention in (
            interventions
            if interventions is not None
            else session.scalars(
                select(InterventionRow).where(InterventionRow.run_id == run_id)
            ).all()
        ):
            absorb_agent_block((intervention.evidence_json or {}).get("agent"))

        for event in (
            search_events
            if search_events is not None
            else session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id == run_id,
                    AuditEventRow.event_type == "activity_search",
                )
            ).all()
        ):
            detail = event.detail_json or {}
            absorb_agent_block(detail.get("agent"))
            intent = detail.get("intent")
            if not isinstance(intent, dict):
                continue
            mode = str(intent.get("mode", "unknown"))
            if mode == "chips":
                # The chip path ran no parser at all. Counting it here would put a non-LLM mode
                # in an LLM histogram.
                continue
            # Prefixed, because `fallback_error` on the intent parse and `fallback_error` on the
            # ranking loop are different failures with different fixes.
            modes[f"intent:{mode}"] = modes.get(f"intent:{mode}", 0) + 1
            if intent.get("attempted"):
                # The intent parse is a single call with no loop and no guardrail, so it
                # contributes to the call, latency and token totals and to nothing else.
                calls += 1
                latency_ms_total += int(intent.get("latency_ms") or 0)
                tokens_total += int(intent.get("total_tokens") or 0)

        return {
            "llm_calls": calls,
            "llm_latency_ms_total": latency_ms_total,
            "llm_tokens_total": tokens_total,
            "llm_fallbacks_by_mode": modes,
            "guardrail_rejections_by_rule": rejections_by_rule,
        }

    @staticmethod
    def _activity_loop_observability(
        search_events: Sequence[AuditEventRow],
        offers: Sequence[ActivityOfferResponseRow],
        counts: dict[str, Any],
    ) -> dict[str, object]:
        """The user-initiated loop's funnel for this run: searches -> shown -> answered ->
        planned -> reported -> went -> enjoyed. Counts only; every rate a surface shows is built
        from two of these with the denominator printed beside it.

        Pure: the run's search events and search-card answers, and the counts `_run_counts` reads
        in its single query, are passed in."""
        reasons: dict[str, int] = {}
        for offer in offers:
            if offer.reason:
                reasons[offer.reason] = reasons.get(offer.reason, 0) + 1
        return {
            "activity_searches": len(search_events),
            "activity_results_shown": sum(
                int(event.detail_json.get("result_count") or 0) for event in search_events
            ),
            "activity_interested": sum(
                1 for o in offers if o.response == ActivityOfferResponse.INTERESTED.value
            ),
            "activity_not_for_me": sum(
                1 for o in offers if o.response == ActivityOfferResponse.NOT_FOR_ME.value
            ),
            "activity_decline_reasons": reasons,
            "activities_planned": counts["activities_planned"],
            # A replaced plan is not due a report -- nobody will ever be asked about it -- so
            # counting it would inflate the denominator every report rate is read against.
            "plans_due": counts["plans_due"],
            "activity_reports": counts["activity_reports"],
            "activity_went": counts["activity_went"],
            "activity_enjoyed": counts["activity_enjoyed"],
            # Replanning, counted from the offers themselves rather than from the audit trail:
            # one row per offer, resolved in place, so these cannot double-count a retry.
            "replans_offered": counts["replans_offered"],
            "replans_accepted": counts["replans_accepted"],
            "replans_declined": counts["replans_declined"],
        }

    @staticmethod
    def _run_counts(session: Session, run_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Every per-run count the operational metrics report, for every run in one query.

        Each count is its own correlated subquery with exactly the filter the separate
        `count()` query it replaces had, so one round trip answers what used to take sixteen.
        `people` is the whole `people` table, as before; `last_decision`/`last_observed_at` are
        the run's most recently recorded decision.
        """
        if not run_ids:
            return {}
        run_id = ScenarioRunRow.run_id

        def count(model: Any, *conditions: ColumnElement[bool]) -> Any:
            return (
                select(func.count())
                .select_from(model)
                .where(model.run_id == run_id, *conditions)
                .correlate(ScenarioRunRow)
                .scalar_subquery()
            )

        def latest_decision(column: Any) -> Any:
            return (
                select(column)
                .where(DecisionEvidenceRow.run_id == run_id)
                .order_by(
                    DecisionEvidenceRow.recorded_at.desc(), DecisionEvidenceRow.evidence_id.desc()
                )
                .limit(1)
                .correlate(ScenarioRunRow)
                .scalar_subquery()
            )

        columns: dict[str, Any] = {
            "people": select(func.count()).select_from(PersonRow).scalar_subquery(),
            "audit_events": count(AuditEventRow),
            "decision_evidence": count(DecisionEvidenceRow),
            "interventions": count(InterventionRow),
            "outcomes": count(InterventionOutcomeRow),
            "open_cases": count(ReviewCaseRow, ReviewCaseRow.status == CaseStatus.OPEN.value),
            "no_action_decisions": count(
                DecisionEvidenceRow, DecisionEvidenceRow.decision == Decision.NO_ACTION.value
            ),
            "coordinator_reviews": count(CaseReviewRow, CaseReviewRow.human_action.is_not(None)),
            "device_suspected_days": count(
                DailyMetricRow, DailyMetricRow.wear_hours < MINIMUM_WEAR_HOURS
            ),
            "coordinator_overrides": count(
                CaseReviewRow, CaseReviewRow.human_action == HumanAction.OVERRIDE.value
            ),
            "day_disputes": count(DayDisputeRow),
            "activities_planned": count(WeekPlanEntryRow),
            "plans_due": count(
                WeekPlanEntryRow,
                WeekPlanEntryRow.day < ScenarioRunRow.current_day,
                WeekPlanEntryRow.replaced_reason.is_(None),
            ),
            "activity_reports": count(PlanFollowThroughRow),
            "activity_went": count(
                PlanFollowThroughRow,
                PlanFollowThroughRow.follow_through == PlannedFollowThrough.WENT.value,
            ),
            "activity_enjoyed": count(
                PlanEnjoymentRow, PlanEnjoymentRow.enjoyment == Enjoyment.ENJOYED.value
            ),
            "replans_offered": count(ReplanOfferRow),
            "replans_accepted": count(
                ReplanOfferRow, ReplanOfferRow.resolution == ReplanResolution.ACCEPTED.value
            ),
            "replans_declined": count(
                ReplanOfferRow, ReplanOfferRow.resolution == ReplanResolution.DECLINED.value
            ),
            "last_decision": latest_decision(DecisionEvidenceRow.decision),
            "last_observed_at": latest_decision(DecisionEvidenceRow.observed_at),
        }
        names = list(columns)
        counts: dict[str, dict[str, Any]] = {}
        for row in session.execute(
            select(run_id, *(column.label(name) for name, column in columns.items())).where(
                run_id.in_(run_ids)
            )
        ):
            values = dict(zip(["run_id", *names], row, strict=True))
            key = values.pop("run_id")
            counts[key] = {
                name: (value if name in {"last_decision", "last_observed_at"} else int(value or 0))
                for name, value in values.items()
            }
        return counts

    @staticmethod
    def _search_events_for(
        session: Session, run_ids: Sequence[str]
    ) -> dict[str, list[AuditEventRow]]:
        """Each run's `activity_search` audit events, in one query."""
        events: dict[str, list[AuditEventRow]] = {run_id: [] for run_id in run_ids}
        if run_ids:
            for event in session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id.in_(run_ids),
                    AuditEventRow.event_type == "activity_search",
                )
            ):
                if event.run_id is not None:
                    events[event.run_id].append(event)
        return events

    @staticmethod
    def _typical_response_hour(session: Session, run_id: str) -> tuple[int | None, list[int]]:
        """The hour of day this person tends to answer at, on the clock they actually read
        (`local_hour`, Singapore local -- never the raw UTC hour a naive `.hour` would give),
        from response timestamps that were already on record. Median rather than mean, and
        honest about its limits: it does not wrap around midnight and it is not a claim about
        anybody's routine. Only the person's own answers count -- the response clock's `system`
        rows say nothing about when they reply."""
        response_hours = [
            local_hour(row.recorded_at)
            for row in session.scalars(
                select(InterventionOutcomeRow).where(
                    InterventionOutcomeRow.run_id == run_id,
                    InterventionOutcomeRow.actor != "system",
                )
            )
        ]
        return SqlAlchemyRepository._typical_hour_of(response_hours)

    @staticmethod
    def _typical_response_hour_from(
        outcomes: Iterable[InterventionOutcomeRow], run_id: str
    ) -> tuple[int | None, list[int]]:
        """`_typical_response_hour`, over outcome rows already loaded for the run (`_RunReads`)."""
        return SqlAlchemyRepository._typical_hour_of(
            [
                local_hour(row.recorded_at)
                for row in outcomes
                if row.run_id == run_id and row.actor != "system"
            ]
        )

    @staticmethod
    def _typical_hour_of(response_hours: list[int]) -> tuple[int | None, list[int]]:
        typical_hour = (
            int(round(median(response_hours)))
            if len(response_hours) >= MINIMUM_RESPONSE_HOUR_SAMPLE
            else None
        )
        return typical_hour, response_hours

    def _follow_through_observability(
        self,
        reads: _RunReads,
        *,
        counts: dict[str, Any],
        search_events: Sequence[AuditEventRow],
        offers: Sequence[ActivityOfferResponseRow],
        suppressed_candidates: int,
    ) -> dict[str, object]:
        """The counters that say whether outreach lands or is merely acknowledged.

        `candidate_accepted_counts` (elsewhere) counts taps. Everything here counts what happened
        afterwards, and the gap between the two is the honest read on whether any of this helps.

        `follow_up_returned_toward_usual` is a count of observations, never a rate and never a
        causal claim: it is reported next to its own denominator so it cannot be quoted without
        one, and a person returns to their usual week for every reason there is.

        Pure over rows already read: the run's interventions with their follow-through reports,
        readings and outcomes (`_load_run_reads`), and its counts (`_run_counts`). A follow-through
        report and an outcome carry their intervention's own `run_id` (every writer copies it), so
        reading them through the intervention is reading them by run.
        """
        followed_counts: dict[str, int] = {}
        completed_counts: dict[str, int] = {}
        for intervention in reads.interventions:
            reported = reads.follow_through.get(intervention.intervention_id)
            if reported is None:
                continue
            key = self._candidate_key_of(intervention)
            followed_counts[key] = followed_counts.get(key, 0) + 1
            if reported == FollowThrough.COMPLETED.value:
                completed_counts[key] = completed_counts.get(key, 0) + 1

        history = [self._to_metric(row) for row in reads.metric_rows]
        reference_steps = calculate_reference(history)[0]
        observations = [
            observe_effect(
                intervention_id=row.intervention_id,
                outreach_day=reads.outreach_day(row),
                history=history,
                reference_steps=reference_steps,
            )
            for row in reads.interventions
        ]
        available = [observation for observation in observations if observation.available]

        typical_hour, response_hours = self._typical_response_hour_from(
            reads.outcomes, reads.run_id
        )
        return {
            "candidate_followed_counts": followed_counts,
            "candidate_completed_counts": completed_counts,
            "follow_through_reported": len(reads.follow_through),
            "follow_through_completed": sum(
                1
                for report in reads.follow_through.values()
                if report == FollowThrough.COMPLETED.value
            ),
            "follow_up_observations": len(available),
            "follow_up_returned_toward_usual": sum(
                1 for observation in available if observation.returned_toward_usual
            ),
            "suppressed_candidates": suppressed_candidates,
            "day_disputes": counts["day_disputes"],
            "typical_response_hour": typical_hour,
            "typical_response_hour_sample": len(response_hours),
            **self._activity_loop_observability(search_events, offers, counts),
            # The response clock, as two honest counts rather than one difference.
            "awaiting_reply": reads.awaiting_reply_count(),
            "no_reply_recorded": reads.no_reply_recorded_count(),
        }

    def metrics(self, *, person_id: str = DEMO_PERSON_ID) -> OperationalMetrics:
        """One person's operational counters, read in one session with a fixed number of queries:
        the decision-path inputs once (`_load_run_reads`), every count in one query (`_run_counts`),
        and the world model's quality built from the same rows."""
        with self.sessions() as session:
            run = self._active_run(session, person_id)
            reads = self._run_reads(session, run)
            preference_rows = self._preference_rows(session, person_id)
            decision_learner, candidate_learner = self._learners_from(preference_rows)
            candidate_titles = self._candidate_catalogue(session)
            candidate_keys = set(candidate_titles)
            candidate_outcome_counts = self._outcome_counts_from(
                (intervention, outcome) for intervention, outcome, _, _, _ in preference_rows
            )
            source_counts: dict[str, int] = {}
            for metric_row in reads.metric_rows:
                source_counts[metric_row.fixture_classification] = (
                    source_counts.get(metric_row.fixture_classification, 0) + 1
                )
            counts = self._run_counts(session, [run.run_id])[run.run_id]
            search_events = self._search_events_for(session, [run.run_id])[run.run_id]
            offers = list(
                session.scalars(
                    select(ActivityOfferResponseRow).where(
                        ActivityOfferResponseRow.run_id == run.run_id
                    )
                )
            )
            candidate_preference_rows = self._candidate_preference_rows(session, [person_id])
            planner = self._planner_observability(
                session, run.run_id, interventions=reads.interventions
            )
            llm_cost = self._llm_cost_observability(
                session,
                run.run_id,
                interventions=reads.interventions,
                search_events=search_events,
            )
            follow_through = self._follow_through_observability(
                reads,
                counts=counts,
                search_events=search_events,
                offers=offers,
                suppressed_candidates=len(
                    {
                        row.candidate_key
                        for row in candidate_preference_rows[person_id]
                        if row.suppressed is True
                    }
                ),
            )
            # Counts only reach the coordinator surface; the facts themselves stay on the senior's.
            quality = self._world_models(
                session,
                [run],
                {run.run_id: reads},
                catalogue=candidate_titles,
                preference_rows=candidate_preference_rows,
            )[run.run_id].quality
            last_decision = counts["last_decision"]
            last_observed_at = counts["last_observed_at"]
            return OperationalMetrics(
                **planner,
                **llm_cost,
                **follow_through,
                world_model_quality=quality,
                people=counts["people"],
                scenario_run_id=run.run_id,
                audit_events=counts["audit_events"],
                decision_evidence=counts["decision_evidence"],
                interventions=counts["interventions"],
                outcomes=counts["outcomes"],
                open_cases=counts["open_cases"],
                no_action_decisions=counts["no_action_decisions"],
                # The denominator, and only reviews where a human actually recorded a choice. The
                # system writes its own closures for recovery and consent withdrawal; counting
                # those would make Care+ look more agreed-with the more cases resolved
                # themselves, which is the opposite of what this number is for.
                coordinator_reviews=counts["coordinator_reviews"],
                # Counted off the stored readings with the same threshold
                # `quality.assess_data_quality` applies, rather than re-deriving "did not sync"
                # from the decision rows -- a NO_ACTION can be reached by five other rungs, so
                # counting NO_ACTION days here would quietly count rainy ones too.
                device_suspected_days=counts["device_suspected_days"],
                coordinator_overrides=counts["coordinator_overrides"],
                consent_active=reads.consent_active,
                last_decision=Decision(last_decision) if last_decision is not None else None,
                last_observed_at=(
                    _as_utc(last_observed_at) if last_observed_at is not None else None
                ),
                source_classification_counts=dict(sorted(source_counts.items())),
                preference_scores=decision_learner.snapshot(
                    [decision.value for decision in Decision]
                ),
                candidate_preference_scores=candidate_learner.snapshot(sorted(candidate_keys)),
                candidate_labels={
                    key: candidate_titles.get(key, _readable_candidate_label(key))
                    for key in candidate_keys
                },
                candidate_offer_counts={
                    key: candidate_outcome_counts[key][1]
                    for key in candidate_keys
                    if key in candidate_outcome_counts
                },
                candidate_accepted_counts={
                    key: candidate_outcome_counts[key][0]
                    for key in candidate_keys
                    if key in candidate_outcome_counts
                },
                policy_version=POLICY_VERSION,
                persistence=self.engine.url.get_backend_name(),
                offline_ready=True,
            )
