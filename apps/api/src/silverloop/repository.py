from __future__ import annotations

from datetime import date
from typing import Protocol

from silverloop.analytics import ACTIVITY_RELATIVE_DEFAULT_DAYS
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    ActivityCandidate,
    ActivityGoal,
    ActivityIntent,
    ActivityOfferResponse,
    ActivityPreferences,
    ActivityQueryResponse,
    ActivityRelativeToUsual,
    ActivityResponseResponse,
    AdvanceResponse,
    AuditEvent,
    BaselineConfirmationDecision,
    BaselineConfirmationResponse,
    CandidatePreference,
    CandidatePreferenceResponse,
    CarePriorityBoard,
    CaseReviewResponse,
    CaseStatus,
    ClarificationScope,
    ConsentResponse,
    ContextAnswerResponse,
    ContextGapCategory,
    CoordinatorFleetMetrics,
    CoordinatorPersonRow,
    DailyMetric,
    DayDisputeResponse,
    DeclineReason,
    DemoResetResponse,
    Enjoyment,
    EnjoymentResponse,
    FollowThrough,
    FollowThroughResponse,
    FollowUpObservation,
    GoalKind,
    HumanAction,
    Intervention,
    LikedAspect,
    MemoryDecision,
    MemoryDecisionResponse,
    OperationalMetrics,
    OutcomeKind,
    OutcomeResponse,
    OutreachDetail,
    OutreachSummary,
    OverrideReason,
    PersonState,
    PersonWorldModel,
    PlannedEnjoymentResponse,
    PlannedFollowThrough,
    PlannedFollowThroughResponse,
    PreferenceDimension,
    PreferenceStance,
    PreferenceStatementResponse,
    Programme,
    ProposedMemory,
    RankerInspectRequest,
    RankerInspectResponse,
    RankerPresetsResponse,
    ReadinessResponse,
    ReplanNotice,
    ReplanOffer,
    ReviewCase,
    ReviewThresholdDecisionResponse,
    ReviewThresholdRejectionReason,
    ReviewThresholdReplay,
    ReviewThresholdState,
    ReviewThresholdValue,
    SimulationHistoryEntry,
    WeekPlan,
)


class SilverLoopRepository(Protocol):
    """Application-facing persistence boundary owned by FastAPI."""

    def ensure_active_run(self, *, person_id: str = DEMO_PERSON_ID) -> None: ...

    def reset(
        self, *, person_id: str = DEMO_PERSON_ID, allow_new_person: bool = False
    ) -> DemoResetResponse: ...

    def person_state(self, *, person_id: str = DEMO_PERSON_ID) -> PersonState: ...

    def daily_metrics(
        self, *, person_id: str = DEMO_PERSON_ID, days: int = 14
    ) -> list[DailyMetric]: ...

    def advance(
        self,
        event_name: str,
        event_id: str | None = None,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> AdvanceResponse: ...

    def latest_advance(self, *, person_id: str = DEMO_PERSON_ID) -> AdvanceResponse | None: ...

    def simulation_history(
        self, *, person_id: str = DEMO_PERSON_ID, limit: int = 10
    ) -> list[SimulationHistoryEntry]: ...

    def list_events(self, *, person_id: str = DEMO_PERSON_ID) -> list[AuditEvent]: ...

    def list_interventions(self, *, person_id: str = DEMO_PERSON_ID) -> list[Intervention]: ...

    def record_outcome(
        self,
        intervention_id: str,
        outcome: OutcomeKind | str,
        actor: str,
        *,
        reason: DeclineReason | str | None = None,
        person_id: str | None = None,
    ) -> OutcomeResponse: ...

    # ── The follow-through loop ───────────────────────────────────────────────

    def outreach_detail(
        self, intervention_id: str, *, person_id: str | None = None
    ) -> OutreachDetail: ...

    def record_follow_through(
        self,
        intervention_id: str,
        follow_through: FollowThrough | str,
        actor: str,
        *,
        note: str | None = None,
        person_id: str | None = None,
    ) -> FollowThroughResponse: ...

    def follow_up_observation(
        self, intervention_id: str, *, person_id: str | None = None
    ) -> FollowUpObservation: ...

    def list_outreach_summaries(
        self, *, person_id: str = DEMO_PERSON_ID
    ) -> list[OutreachSummary]: ...

    def activity_relative_to_usual(
        self, *, person_id: str = DEMO_PERSON_ID, days: int = ACTIVITY_RELATIVE_DEFAULT_DAYS
    ) -> ActivityRelativeToUsual: ...

    def list_candidate_preferences(
        self, *, person_id: str = DEMO_PERSON_ID
    ) -> list[CandidatePreference]: ...

    def set_candidate_preference(
        self,
        candidate_key: str,
        suppressed: bool,
        reason: str | None,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> CandidatePreferenceResponse: ...

    def record_day_dispute(
        self,
        day: date,
        accurate: bool,
        note: str | None,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> DayDisputeResponse: ...

    def set_consent(
        self, active: bool, reason: str, actor: str, *, person_id: str = DEMO_PERSON_ID
    ) -> ConsentResponse: ...

    def list_programmes(self) -> list[Programme]: ...

    # ── The user-initiated loop ───────────────────────────────────────────────

    def search_activities(
        self,
        *,
        text: str | None,
        intent: ActivityIntent | None,
        person_id: str,
        actor: str,
    ) -> ActivityQueryResponse: ...

    def list_activities(self) -> list[ActivityCandidate]: ...

    def inspect_ranker(self, request: RankerInspectRequest) -> RankerInspectResponse:
        """Evaluator-only: trace one ranking execution (and a previewed variant). Never writes."""
        ...

    def ranker_presets(self) -> RankerPresetsResponse: ...

    def get_activity(self, activity_id: str) -> ActivityCandidate: ...

    def activity_preferences(self, *, person_id: str = DEMO_PERSON_ID) -> ActivityPreferences: ...

    def world_model(self, *, person_id: str = DEMO_PERSON_ID) -> PersonWorldModel: ...

    # ── Closing the loop, memory, goals and replanning ────────────────────────

    def record_enjoyment(
        self,
        intervention_id: str,
        enjoyment: Enjoyment | str,
        liked: list[LikedAspect],
        actor: str,
        *,
        person_id: str | None = None,
    ) -> EnjoymentResponse: ...

    def list_proposed_memories(
        self, *, person_id: str = DEMO_PERSON_ID
    ) -> list[ProposedMemory]: ...

    def decide_proposed_memory(
        self,
        proposal_id: str,
        decision: MemoryDecision | str,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> MemoryDecisionResponse: ...

    def answer_context_question(
        self,
        question_id: str,
        value: str,
        note: str | None,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> ContextAnswerResponse: ...

    def decide_baseline_confirmation(
        self,
        decision: BaselineConfirmationDecision | str,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> BaselineConfirmationResponse: ...

    def list_goals(self, *, person_id: str = DEMO_PERSON_ID) -> list[ActivityGoal]: ...

    def set_goal(
        self,
        kind: GoalKind | str,
        target_per_week: int | None,
        active: bool,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> ActivityGoal: ...

    def week_plan(self, *, person_id: str = DEMO_PERSON_ID) -> WeekPlan: ...

    def plan_activity(
        self,
        activity_id: str,
        day: date,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> WeekPlan: ...

    # ── The senior answers a search result ────────────────────────────────────

    def respond_to_activity(
        self,
        activity_id: str,
        response: ActivityOfferResponse | str,
        *,
        reason: DeclineReason | str | None = None,
        clarification: ClarificationScope | str | None = None,
        query_id: str | None = None,
        rank_shown: int | None = None,
        day: date | None = None,
        actor: str,
        person_id: str = DEMO_PERSON_ID,
    ) -> ActivityResponseResponse: ...

    def record_planned_follow_through(
        self,
        plan_id: str,
        follow_through: PlannedFollowThrough | str,
        note: str | None,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> PlannedFollowThroughResponse: ...

    def record_planned_enjoyment(
        self,
        plan_id: str,
        enjoyment: Enjoyment | str,
        liked: list[LikedAspect],
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> PlannedEnjoymentResponse: ...

    def state_preference(
        self,
        dimension: PreferenceDimension | str,
        value: str,
        stance: PreferenceStance | str,
        *,
        until: date | None = None,
        stated_text: str | None = None,
        actor: str,
        person_id: str = DEMO_PERSON_ID,
    ) -> PreferenceStatementResponse: ...

    def replan_notices(self, *, person_id: str = DEMO_PERSON_ID) -> list[ReplanNotice]: ...

    def replace_planned_activity(
        self,
        plan_id: str,
        activity_id: str,
        actor: str,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> WeekPlan: ...

    def decline_replan_offer(
        self, offer_id: str, actor: str, *, person_id: str = DEMO_PERSON_ID
    ) -> ReplanOffer: ...

    def list_coordinator_roster(self) -> list[CoordinatorPersonRow]: ...

    def care_priorities(
        self, *, top_k: int = ..., person_id: str | None = None
    ) -> CarePriorityBoard: ...

    def coordinator_metrics(self) -> CoordinatorFleetMetrics: ...

    def senior_home(self, *, person_id: str) -> tuple[PersonState, Intervention | None]: ...

    def list_cases(self, *, person_id: str | None = None) -> list[ReviewCase]: ...

    def get_case(self, case_id: str) -> ReviewCase: ...

    def review_case(
        self,
        case_id: str,
        status: CaseStatus,
        note: str,
        reviewer: str,
        *,
        human_action: HumanAction | None = None,
        override_reason: OverrideReason | None = None,
        reached_too_late: bool = False,
        context_gap_category: ContextGapCategory | None = None,
        recorded_by_demo_script: bool = False,
    ) -> CaseReviewResponse: ...

    # ── Review setting, person by person (ADR 0008) ───────────────────────────

    def review_threshold_state(
        self, person_id: str, *, viewer_sub: str
    ) -> ReviewThresholdState: ...

    def review_threshold_replay(
        self, person_id: str, candidate: ReviewThresholdValue
    ) -> ReviewThresholdReplay: ...

    def approve_threshold_proposal(
        self,
        person_id: str,
        proposal_id: str,
        *,
        cause_confirmed: bool,
        shown_on_day: date,
        note: str | None,
        actor: str,
        recorded_by_demo_script: bool = False,
    ) -> ReviewThresholdDecisionResponse: ...

    def reject_threshold_proposal(
        self,
        person_id: str,
        proposal_id: str,
        *,
        reason: ReviewThresholdRejectionReason,
        note: str | None,
        actor: str,
    ) -> ReviewThresholdDecisionResponse: ...

    def set_threshold_manually(
        self,
        person_id: str,
        *,
        threshold: ReviewThresholdValue,
        note: str,
        shown_on_day: date,
        actor: str,
    ) -> ReviewThresholdDecisionResponse: ...

    def confirm_starting_threshold(
        self, person_id: str, *, shown_on_day: date, actor: str
    ) -> ReviewThresholdDecisionResponse: ...

    def reconfirm_threshold(
        self, person_id: str, decision_id: str, *, shown_on_day: date, actor: str
    ) -> ReviewThresholdDecisionResponse: ...

    def metrics(self, *, person_id: str = DEMO_PERSON_ID) -> OperationalMetrics: ...

    def readiness(self, runtime_profile: str) -> ReadinessResponse: ...

    def lookup_person_for_sub(self, sub: str) -> str | None: ...

    def upsert_person_link(self, sub: str, person_id: str, created_by: str) -> None: ...
