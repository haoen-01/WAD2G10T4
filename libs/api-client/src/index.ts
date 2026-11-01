import { createClient } from './generated/client';
import {
  personWorldModelV1PeoplePersonIdWorldModelGet,
  plannedEnjoymentV1PeoplePersonIdWeekPlanIdEnjoymentPost,
  plannedFollowThroughV1PeoplePersonIdWeekPlanIdFollowThroughPost,
  respondToActivityV1ActivitiesActivityIdResponsePost,
  stateActivityPreferenceV1PeoplePersonIdActivityPreferencesDimensionValuePut,
  activityDetailV1ActivitiesActivityIdGet,
  advanceV1SimulationAdvancePost,
  approveThresholdProposalV1CoordinatorPeoplePersonIdReviewThresholdProposalsProposalIdApprovePost,
  confirmStartingThresholdV1CoordinatorPeoplePersonIdReviewThresholdConfirmStartingPost,
  answerContextQuestionV1PeoplePersonIdContextAnswerPost,
  coordinatorActivityRelativeV1CoordinatorPeoplePersonIdActivityRelativeGet,
  coordinatorOutreachHistoryV1CoordinatorPeoplePersonIdOutreachHistoryGet,
  coordinatorMetricsV1CoordinatorMetricsGet,
  coordinatorPeopleV1CoordinatorPeopleGet,
  coordinatorPrioritiesV1CoordinatorPrioritiesGet,
  coordinatorQueueV1CoordinatorQueueGet,
  getCaseV1CasesCaseIdGet,
  decideBaselineConfirmationV1PeoplePersonIdBaselineConfirmationPost,
  decideProposedMemoryV1PeoplePersonIdProposedMemoriesProposalIdPost,
  declineReplanOfferV1PeoplePersonIdReplanOffersOfferIdDeclinePost,
  disputeDayV1PeoplePersonIdDayDisputePost,
  eventsV1SimulationEventsGet,
  healthHealthGet,
  inspectRankerV1EvaluatorRankerInspectPost,
  interventionDetailV1InterventionsInterventionIdDetailGet,
  interventionEnjoymentV1InterventionsInterventionIdEnjoymentPost,
  interventionFollowThroughV1InterventionsInterventionIdFollowThroughPost,
  interventionFollowUpV1InterventionsInterventionIdFollowUpGet,
  interventionHistoryV1InterventionsHistoryGet,
  interventionOutcomeV1InterventionsInterventionIdOutcomePost,
  interventionsV1InterventionsGet,
  listActivitiesV1ActivitiesGet,
  latestAdvanceV1SimulationLatestGet,
  meV1AuthMeGet,
  metricsV1MetricsGet,
  personActivityPreferencesV1PeoplePersonIdActivityPreferencesGet,
  personGoalsV1PeoplePersonIdGoalsGet,
  personMetricsV1PeoplePersonIdMetricsGet,
  personPreferencesV1PeoplePersonIdPreferencesGet,
  personProposedMemoriesV1PeoplePersonIdProposedMemoriesGet,
  personReplanNoticesV1PeoplePersonIdReplanNoticesGet,
  personStateV1PeoplePersonIdStateGet,
  personWeekV1PeoplePersonIdWeekGet,
  planActivityV1PeoplePersonIdWeekPost,
  programmesV1ProgrammesGet,
  rankerPresetsV1EvaluatorRankerPresetsGet,
  readinessReadyGet,
  reconfirmThresholdV1CoordinatorPeoplePersonIdReviewThresholdDecisionsDecisionIdReconfirmPost,
  rejectThresholdProposalV1CoordinatorPeoplePersonIdReviewThresholdProposalsProposalIdRejectPost,
  replacePlannedActivityV1PeoplePersonIdWeekPlanIdReplacePost,
  resetDemoV1DemoResetPost,
  reviewCaseV1CasesCaseIdReviewPost,
  reviewThresholdReplayV1CoordinatorPeoplePersonIdReviewThresholdReplayGet,
  reviewThresholdStateV1CoordinatorPeoplePersonIdReviewThresholdGet,
  searchActivitiesV1ActivitiesSearchPost,
  seniorHomePreviewV1EvaluatorPeoplePersonIdSeniorHomeGet,
  setPersonGoalV1PeoplePersonIdGoalsPost,
  setPersonPreferenceV1PeoplePersonIdPreferencesCandidateKeyPost,
  setThresholdManuallyV1CoordinatorPeoplePersonIdReviewThresholdManualPost,
  simulationHistoryV1SimulationHistoryGet,
  updateConsentV1PeoplePersonIdConsentPost,
} from './generated/sdk.gen';

import type {
  ActivityIntent,
  ActivityOfferResponse,
  ClarificationScope,
  ContextAnswerValue,
  ContextGapCategory,
  PlannedFollowThrough,
  PreferenceDimension,
  PreferenceStance,
  BaselineConfirmationDecision,
  CaseStatus,
  DeclineReason,
  Enjoyment,
  FollowThrough,
  GoalKind,
  HumanAction,
  LikedAspect,
  MemoryDecision,
  OutcomeKind,
  OverrideReason,
  RankerInspectRequest,
  ReviewThresholdRejectionReason,
  ServerErrorCode,
} from './generated/types.gen';

export type {
  ActivityAvailability,
  ActivityPosition,
  ActivityRelativeDay,
  ActivityRelativeToUsual,
  ActivityBooking,
  ActivityGoal,
  ActivityGoalRequest,
  ActivityCandidate,
  ActivityEnvironment,
  ActivityIntensity,
  ActivityIntent,
  ActivityLocation,
  ActivityPreferences,
  ActivityQueryRequest,
  ActivityQueryResponse,
  ActivityOfferResponse,
  ActivityResponseRequest,
  ActivityResponseResponse,
  ActivityFamily,
  ActivityReason,
  ActivitySource,
  ActivityType,
  AdvanceRequest,
  AdvanceResponse,
  AttentionBand,
  AuditEvent,
  AuthRole,
  BaselineConfirmationDecision,
  BaselineConfirmationQuestion,
  BaselineConfirmationRequest,
  BaselineConfirmationResponse,
  BaselineSummary,
  CandidatePreference,
  CandidatePreferenceRequest,
  CandidatePreferenceResponse,
  CareNote,
  CareNoteKind,
  CarePriorityBoard,
  CarePriorityRow,
  CareTeamGroup,
  CareTeamGroupReason,
  CaseResolution,
  CaseStatus,
  CaseReviewResponse,
  ClarificationScope,
  ConsentRequest,
  ConsentResponse,
  ContextSignal,
  CoordinatorFleetMetrics,
  CoordinatorPersonRow,
  CurrentUser,
  // Accounts and family groups
  AccountRole,
  CareGroup,
  CreateGroupRequest,
  GroupMember,
  GroupRole,
  JoinGroupRequest,
  LinkSeniorRequest,
  MemberStatus,
  MeResponse,
  MyGroup,
  OnboardRequest,
  PinResponse,
  SeniorNameRequest,
  // Family calendar
  Appointment as CalendarAppointment,
  AppointmentKind,
  AppointmentNote,
  AppointmentNoteRequest,
  AppointmentOccurrence,
  AppointmentRequest,
  AvailabilityEntryOut,
  AvailabilityRequest,
  AvailabilityStatus,
  CalendarMember,
  CheckInKind,
  CheckInRequest,
  FamilyActivityEntry,
  FamilyActivityKind,
  FamilyActivityPage,
  FamilyCalendar,
  HelperAssignment,
  OccurrenceAnswerRequest,
  OccurrenceRequest,
  RepeatRule,
  // Tasks
  Task,
  TaskDayRequest,
  TaskKind,
  TaskList,
  TaskRepeat,
  TaskRequest,
  TaskTick,
  // The senior's watch
  WearableStatus,
  // The Care+ assistant
  AssistantChatRequest,
  AssistantMessage,
  AssistantReply,
  FollowUpWindow,
  PriorityHold,
  ThresholdReference,
  DailyMetric,
  DataQualityAssessment,
  Decision,
  DayDisputeRequest,
  DayDisputeResponse,
  DeclineReason,
  DecisionTraceStep,
  ContextAnswerOption,
  ContextAnswerRequest,
  ContextAnswerResponse,
  ContextAnswerValue,
  ContextQuestion,
  DimensionPreference,
  PlannedEnjoymentRequest,
  PlannedEnjoymentResponse,
  PlannedFollowThrough,
  PlannedFollowThroughRequest,
  PlannedFollowThroughResponse,
  PreferenceStance,
  PreferenceStatementRequest,
  PreferenceStatementResponse,
  Enjoyment,
  EnjoymentRequest,
  EnjoymentResponse,
  GoalKind,
  FilterOutcome,
  DemoResetResponse,
  DistanceBasis,
  FollowThrough,
  FollowThroughRequest,
  FollowThroughResponse,
  FollowUpObservation,
  Format,
  HealthResponse,
  HumanAction,
  Intervention,
  OperationalMetrics,
  OutcomeRequest,
  OutcomeResponse,
  IndoorOutdoor,
  LikedAspect,
  MemoryDecision,
  MemoryDecisionRequest,
  MemoryDecisionResponse,
  IntegrationStatus,
  IntentParser,
  OutcomeKind,
  OutreachDetail,
  OutreachStep,
  OutreachSummary,
  OverrideReason,
  PersonFact,
  PersonState,
  PersonWorldModel,
  WorldModelQuality,
  FactCategory,
  FactConfidence,
  FactSourceType,
  PlanActivityRequest,
  PlannedActivity,
  PolicyGate,
  PreferenceDimension,
  PriorOutreach,
  ProposedMemory,
  Programme,
  RankedActivity,
  ReasonBasis,
  ReplacePlannedActivityRequest,
  ReplanNotice,
  ReplanOffer,
  ReplanReason,
  ReplanResolution,
  ResolvedPreference,
  SocialPreference,
  TimeWindow,
  WeekPlan,
  ReadinessResponse,
  ReviewCase,
  ReviewAction,
  ReviewRequest,
  ServerErrorBody,
  ServerErrorCode,
  SignalSummary,
  SimulationHistoryEntry,
  SinceLastReview,
  SinceLastReviewAnchorKind,
  SinceLastReviewItem,
  SinceLastReviewKind,
  SourceTier,
  TraceStatus,
  // Evaluator-only: the Activity Ranker Inspector (`/v1/evaluator/ranker/*`). Never on a
  // senior or coordinator payload.
  ActivityRankingTrace,
  CandidateIntegrity,
  CandidateTrace,
  IntegrityFinding,
  RankChange,
  RankerCounterfactual,
  RankerCounterfactualControls,
  RankerFeedbackKind,
  RankerFeedbackPreview,
  RankerHistoryPreset,
  RankerInspectRequest,
  RankerInspectResponse,
  RankerPresetEvent,
  RankerPresetsResponse,
  RankerRequestCounterfactual,
  ReviewThresholdApproveRequest,
  ReviewThresholdBounds,
  ReviewThresholdCause,
  ReviewThresholdCheck,
  ReviewThresholdDecisionKind,
  ReviewThresholdDecisionRecord,
  ReviewThresholdDecisionResponse,
  ReviewThresholdFloor,
  ReviewThresholdManualSetRequest,
  ReviewThresholdNotice,
  ReviewThresholdNoticeKind,
  ReviewThresholdOutputKind,
  ReviewThresholdProposal,
  ReviewThresholdProposer,
  ReviewThresholdRejectRequest,
  ReviewThresholdRejectionReason,
  ReviewThresholdReplay,
  ReviewThresholdReplayEpisode,
  ReviewThresholdRevertTrigger,
  ReviewThresholdShownRequest,
  ReviewThresholdState,
  ReviewThresholdValue,
  // Calibration trust: what each review teaches, the review-setting receipt and the context-gap
  // tally. Coordinator-only.
  ContextGapCategory,
  ContextGapCount,
  ContextGapTally,
  ReviewLesson,
  ReviewLessonKind,
  ReviewLessonReason,
  ReviewReceiptEntry,
  ReviewReceiptExclusion,
  ReviewReceiptStatus,
  ReviewSettingReceipt,
  SeniorHomePreview,
  RankerWorldCounterfactual,
  RankerWorldModelCounterfactual,
  ReasonWithoutPositiveFactor,
  ScoreFactor,
  TraceApplied,
  TraceCatalogueUnknown,
  TraceEngagement,
  TraceEngagementCounts,
  TraceFact,
  TraceFilterOutcome,
  TraceFiltering,
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
} from './generated/types.gen';

/**
 * Thrown by every `SilverLoopClient` method on a failed request. The generated
 * SDK only throws the parsed response body (a string, a `{ detail }` object, or
 * a network `Error`), with no HTTP status — so callers cannot tell an expired
 * session (401) apart from a missing role (403) or a genuine network outage.
 * This wraps that failure in a real `Error` and attaches `status` (`0` when no
 * HTTP response was ever produced, e.g. the network is unreachable) so callers
 * can branch on it directly instead of guessing from provider-specific text.
 *
 * `code` is the machine-readable classification the API puts on server-side failures
 * (`ServerErrorBody`: `{ code, message, detail }`), and `undefined` for every response that
 * carries none or carries a code this client does not know.
 */
export class ApiHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: ServerErrorCode,
  ) {
    super(message);
    this.name = 'ApiHttpError';
  }
}

/** Every `ServerErrorCode`, checked against the generated type in both directions. */
const SERVER_ERROR_CODES: Record<ServerErrorCode, true> = {
  stored_state_incompatible: true,
  internal_error: true,
};

function isServerErrorCode(value: unknown): value is ServerErrorCode {
  return typeof value === 'string' && Object.hasOwn(SERVER_ERROR_CODES, value);
}

/** The API's error classification code, when the failed response body carries a known one. */
function errorCode(error: unknown): ServerErrorCode | undefined {
  if (error && typeof error === 'object' && 'code' in error) {
    const code = (error as { code?: unknown }).code;
    if (isServerErrorCode(code)) return code;
  }
  return undefined;
}

/** Best-effort human-readable message from whatever the generated client throws. */
function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return 'Unknown API error';
  }
}

/** Convenience facade over the generated SDK; all model types come from OpenAPI. */
export class SilverLoopClient {
  private readonly client;

  /**
   * @param baseUrl - API base URL
   * @param tokenProvider - Optional async callback that returns a bearer token, or null when
   *   the user is not authenticated. Called before every request so refreshed tokens are
   *   used automatically without rebuilding the client.
   * @param onUnauthorized - Optional callback fired synchronously whenever any request made
   *   through this client instance fails with HTTP 401, in addition to the thrown
   *   `ApiHttpError`. Lets a caller (e.g. an auth provider) react to a session expiring —
   *   redirecting to sign-in — from one place, without every call site wiring it up.
   */
  constructor(
    baseUrl = 'http://127.0.0.1:8000',
    private readonly tokenProvider?: () => Promise<string | null>,
    private readonly onUnauthorized?: () => void,
  ) {
    this.client = createClient({ baseUrl, headers: { 'Cache-Control': 'no-store' } });
    if (tokenProvider) {
      this.client.interceptors.request.use(async (request) => {
        const token = await tokenProvider();
        if (token) {
          request.headers.set('Authorization', `Bearer ${token}`);
        }
        return request;
      });
    }
    // Every method below calls the generated SDK with `throwOnError: true`, so the
    // generated client only ever throws the parsed response body (see
    // `generated/client/client.gen.ts`), never the HTTP status. This interceptor runs
    // before that throw and swaps the error for `ApiHttpError`, so status is always
    // available to callers without touching generated code.
    this.client.interceptors.error.use((error, response) => {
      const status = response?.status ?? 0;
      if (status === 401) onUnauthorized?.();
      return new ApiHttpError(status, describeError(error), errorCode(error));
    });
  }

  async me() {
    const result = await meV1AuthMeGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  async state(personId = 'mdm-lim') {
    const result = await personStateV1PeoplePersonIdStateGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async personMetrics(personId = 'mdm-lim', days?: number) {
    const result = await personMetricsV1PeoplePersonIdMetricsGet<true>({
      client: this.client,
      path: { person_id: personId },
      query: { days },
      throwOnError: true,
    });
    return result.data;
  }

  /** Start one person's story over. Omitting `personId` resets the demo person (the API's
   *  default); an unknown id is a 422. Only that person's run is reset. */
  async reset(personId?: string) {
    const result = await resetDemoV1DemoResetPost<true>({
      client: this.client,
      query: personId ? { person_id: personId } : undefined,
      throwOnError: true,
    });
    return result.data;
  }

  async advance(event: string, eventId?: string, personId = 'mdm-lim') {
    const result = await advanceV1SimulationAdvancePost<true>({
      client: this.client,
      body: { event, event_id: eventId, person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async interventions() {
    const result = await interventionsV1InterventionsGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  async programmes() {
    const result = await programmesV1ProgrammesGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  /**
   * The care-team queue. Omitting `statuses` is not "everything": the API defaults to open and
   * acknowledged cases, so a resolved one never interleaves with an active one unless it was
   * asked for. Pass one or more `CaseStatus` values to widen or narrow that.
   */
  async queue(statuses?: readonly CaseStatus[]) {
    const result = await coordinatorQueueV1CoordinatorQueueGet<true>({
      client: this.client,
      query: statuses?.length ? { status: statuses.join(',') } : undefined,
      throwOnError: true,
    });
    return result.data;
  }

  /** One review case by id, whatever its status, with its server-produced "since your last
   *  review" delta. Rejects with a 404 `ApiHttpError` for an unknown case. */
  async getCase(caseId: string) {
    const result = await getCaseV1CasesCaseIdGet<true>({
      client: this.client,
      path: { case_id: caseId },
      throwOnError: true,
    });
    return result.data;
  }

  /** The care-team roster — everyone on the caseload, not only the people with a case open.
   *  Bands and standings; never a figure about anyone. */
  async coordinatorPeople() {
    const result = await coordinatorPeopleV1CoordinatorPeopleGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  /** Who to follow up with first. Follow-up windows are capped by the policy's own decision;
   *  read-only, and never a figure about anyone.
   *
   *  `personId` narrows the board to that person's row, unchanged: `position` is still their place
   *  in the whole caseload and `follow_up_first` holds the row only if the full board's `topK`
   *  does. `people` is empty for a person with no readings yet; an unknown person is a 404. */
  async coordinatorPriorities(topK?: number, personId?: string) {
    const result = await coordinatorPrioritiesV1CoordinatorPrioritiesGet<true>({
      client: this.client,
      query: { top_k: topK, person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  /** The caseload's operational totals in one read: the sum of `metrics(personId)` over everyone
   *  `coordinatorPeople()` lists. Counts only. */
  async coordinatorMetrics() {
    const result = await coordinatorMetricsV1CoordinatorMetricsGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  async events(personId?: string) {
    const result = await eventsV1SimulationEventsGet<true>({
      client: this.client,
      query: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  /**
   * Evaluator-only (demo operator): trace how the activity ranker got from one request to the
   * cards it would show. `baseline` is live state plus any history preset; a `variant` and
   * `changes` come back only for a counterfactual or feedback preview (or, with
   * `compare_preset_to_live`, for the preset against live state). Read-only on the server.
   */
  async inspectRanker(request: RankerInspectRequest) {
    const result = await inspectRankerV1EvaluatorRankerInspectPost<true>({
      client: this.client,
      body: request,
      throwOnError: true,
    });
    return result.data;
  }

  /** Evaluator-only: the scripted history presets and preview controls the inspector allows. */
  async rankerPresets() {
    const result = await rankerPresetsV1EvaluatorRankerPresetsGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  /** Evaluator-only (demo operator): one persona's senior home content for the Demo Tools
   *  senior-screen preview. Read-only; not the senior's own screen. 404 unknown, 409 unseeded. */
  async seniorHomePreview(personId: string) {
    const result = await seniorHomePreviewV1EvaluatorPeoplePersonIdSeniorHomeGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async latestAdvance(personId?: string) {
    const result = await latestAdvanceV1SimulationLatestGet<true>({
      client: this.client,
      query: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async simulationHistory(personId?: string, limit?: number) {
    const result = await simulationHistoryV1SimulationHistoryGet<true>({
      client: this.client,
      query: { person_id: personId, limit },
      throwOnError: true,
    });
    return result.data;
  }

  async metrics(personId?: string) {
    const result = await metricsV1MetricsGet<true>({
      client: this.client,
      query: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async readiness() {
    const result = await readinessReadyGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  /** Liveness only: `GET /health` answers without a session and without touching the database.
   *  Use `readiness()` for anything that has to be true before a request can succeed. */
  async health() {
    const result = await healthHealthGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  async updateConsent(active: boolean, reason: string, personId = 'mdm-lim') {
    const result = await updateConsentV1PeoplePersonIdConsentPost<true>({
      client: this.client,
      path: { person_id: personId },
      body: { active, reason },
      throwOnError: true,
    });
    return result.data;
  }

  async recordOutcome(interventionId: string, outcome: OutcomeKind, reason?: DeclineReason) {
    const result = await interventionOutcomeV1InterventionsInterventionIdOutcomePost<true>({
      client: this.client,
      path: { intervention_id: interventionId },
      body: { outcome, reason: reason ?? null },
      throwOnError: true,
    });
    return result.data;
  }

  /** What "tell me more" shows: the movement steps or the programme details, never generated. */
  async outreachDetail(interventionId: string) {
    const result = await interventionDetailV1InterventionsInterventionIdDetailGet<true>({
      client: this.client,
      path: { intervention_id: interventionId },
      throwOnError: true,
    });
    return result.data;
  }

  /** What the person actually did. Distinct from `recordOutcome`, which only records the tap. */
  async recordFollowThrough(interventionId: string, followThrough: FollowThrough, note?: string) {
    const result =
      await interventionFollowThroughV1InterventionsInterventionIdFollowThroughPost<true>({
        client: this.client,
        path: { intervention_id: interventionId },
        body: { follow_through: followThrough, note: note ?? null },
        throwOnError: true,
      });
    return result.data;
  }

  /** Always resolves; check `available` before reading any number off the result. */
  async followUp(interventionId: string) {
    const result = await interventionFollowUpV1InterventionsInterventionIdFollowUpGet<true>({
      client: this.client,
      path: { intervention_id: interventionId },
      throwOnError: true,
    });
    return result.data;
  }

  async outreachHistory() {
    const result = await interventionHistoryV1InterventionsHistoryGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  /** Coordinator-scoped twin of `outreachHistory`; a different door, not a widened scope. */
  async coordinatorOutreachHistory(personId: string) {
    const result =
      await coordinatorOutreachHistoryV1CoordinatorPeoplePersonIdOutreachHistoryGet<true>({
        client: this.client,
        path: { person_id: personId },
        throwOnError: true,
      });
    return result.data;
  }

  /**
   * Coordinator-scoped recent days against the person's own usual level, classified on the
   * server: usable or not, and lower than usual or not. No step counts, no cut-offs.
   */
  async coordinatorActivityRelative(personId: string, days?: number) {
    const result =
      await coordinatorActivityRelativeV1CoordinatorPeoplePersonIdActivityRelativeGet<true>({
        client: this.client,
        path: { person_id: personId },
        query: { days },
        throwOnError: true,
      });
    return result.data;
  }

  async candidatePreferences(personId = 'mdm-lim') {
    const result = await personPreferencesV1PeoplePersonIdPreferencesGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async setCandidatePreference(
    candidateKey: string,
    suppressed: boolean,
    reason?: string,
    personId = 'mdm-lim',
  ) {
    const result = await setPersonPreferenceV1PeoplePersonIdPreferencesCandidateKeyPost<true>({
      client: this.client,
      path: { person_id: personId, candidate_key: candidateKey },
      body: { suppressed, reason: reason ?? null },
      throwOnError: true,
    });
    return result.data;
  }

  async disputeDay(day: string, accurate: boolean, note?: string, personId = 'mdm-lim') {
    const result = await disputeDayV1PeoplePersonIdDayDisputePost<true>({
      client: this.client,
      path: { person_id: personId },
      body: { day, accurate, note: note ?? null },
      throwOnError: true,
    });
    return result.data;
  }

  /** A senior asking for something to do. Pass `text`, or an intent assembled from chips. */
  async searchActivities(query: { text?: string; intent?: ActivityIntent }) {
    const result = await searchActivitiesV1ActivitiesSearchPost<true>({
      client: this.client,
      body: { text: query.text ?? null, intent: query.intent ?? null },
      throwOnError: true,
    });
    return result.data;
  }

  /**
   * The senior answers a search result. `interested` plans it onto their week when the day is
   * inside the week being planned; `not_for_me` with a reason teaches the dimensional learner.
   */
  async respondToActivity(
    activityId: string,
    response: ActivityOfferResponse,
    options: {
      reason?: DeclineReason;
      /**
       * How far that reason reaches (`models.ClarificationScope`), when the person tapped a chip
       * saying so. Optional and skippable in its own right: without one the reason stays
       * item-level, which is the honest reading of a single tap.
       */
      clarification?: ClarificationScope;
      queryId?: string;
      rankShown?: number;
      day?: string;
    } = {},
  ) {
    const result = await respondToActivityV1ActivitiesActivityIdResponsePost<true>({
      client: this.client,
      path: { activity_id: activityId },
      body: {
        response,
        reason: options.reason ?? null,
        clarification: options.clarification ?? null,
        query_id: options.queryId ?? null,
        rank_shown: options.rankShown ?? null,
        day: options.day ?? null,
      },
      throwOnError: true,
    });
    return result.data;
  }

  async activities() {
    const result = await listActivitiesV1ActivitiesGet<true>({
      client: this.client,
      throwOnError: true,
    });
    return result.data;
  }

  async activity(activityId: string) {
    const result = await activityDetailV1ActivitiesActivityIdGet<true>({
      client: this.client,
      path: { activity_id: activityId },
      throwOnError: true,
    });
    return result.data;
  }

  /**
   * Everything Care+ knows about this person, each fact labelled with where it came from.
   * Senior-visible only; a coordinator surface gets counts through `metrics().world_model_quality`.
   */
  async worldModel(personId = 'mdm-lim') {
    const result = await personWorldModelV1PeoplePersonIdWorldModelGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  /** Senior-visible only. Never rendered on a coordinator surface. */
  async activityPreferences(personId = 'mdm-lim') {
    const result = await personActivityPreferencesV1PeoplePersonIdActivityPreferencesGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  /** Whether it was any good. Separate beat from `recordFollowThrough`, which asks only if it happened. */
  async recordEnjoyment(interventionId: string, enjoyment: Enjoyment, liked: LikedAspect[] = []) {
    const result = await interventionEnjoymentV1InterventionsInterventionIdEnjoymentPost<true>({
      client: this.client,
      path: { intervention_id: interventionId },
      body: { enjoyment, liked },
      throwOnError: true,
    });
    return result.data;
  }

  /** Beliefs Care+ is holding back until the person agrees to them. */
  async proposedMemories(personId = 'mdm-lim') {
    const result = await personProposedMemoriesV1PeoplePersonIdProposedMemoriesGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async decideProposedMemory(proposalId: string, decision: MemoryDecision, personId = 'mdm-lim') {
    const result = await decideProposedMemoryV1PeoplePersonIdProposedMemoriesProposalIdPost<true>({
      client: this.client,
      path: { person_id: personId, proposal_id: proposalId },
      body: { decision },
      throwOnError: true,
    });
    return result.data;
  }

  async answerContextQuestion(
    questionId: string,
    value: ContextAnswerValue,
    note?: string,
    personId = 'mdm-lim',
  ) {
    const result = await answerContextQuestionV1PeoplePersonIdContextAnswerPost<true>({
      client: this.client,
      path: { person_id: personId },
      body: { question_id: questionId, value, note: note ?? null },
      throwOnError: true,
    });
    return result.data;
  }

  /** "Is this your new normal?" -- only the senior may answer; nothing re-anchors unless they
   *  confirm it themselves. See `baseline_confirmation.py`. */
  async decideBaselineConfirmation(decision: BaselineConfirmationDecision, personId = 'mdm-lim') {
    const result = await decideBaselineConfirmationV1PeoplePersonIdBaselineConfirmationPost<true>({
      client: this.client,
      path: { person_id: personId },
      body: { decision },
      throwOnError: true,
    });
    return result.data;
  }

  async goals(personId = 'mdm-lim') {
    const result = await personGoalsV1PeoplePersonIdGoalsGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async setGoal(kind: GoalKind, targetPerWeek?: number, active = true, personId = 'mdm-lim') {
    const result = await setPersonGoalV1PeoplePersonIdGoalsPost<true>({
      client: this.client,
      path: { person_id: personId },
      body: { kind, target_per_week: targetPerWeek ?? null, active },
      throwOnError: true,
    });
    return result.data;
  }

  async week(personId = 'mdm-lim') {
    const result = await personWeekV1PeoplePersonIdWeekGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  async planActivity(activityId: string, day: string, personId = 'mdm-lim') {
    const result = await planActivityV1PeoplePersonIdWeekPost<true>({
      client: this.client,
      path: { person_id: personId },
      body: { activity_id: activityId, day },
      throwOnError: true,
    });
    return result.data;
  }

  /** What happened to a planned activity: went, did not go, or it was cancelled. */
  async recordPlannedFollowThrough(
    planId: string,
    followThrough: PlannedFollowThrough,
    note?: string,
    personId = 'mdm-lim',
  ) {
    const result = await plannedFollowThroughV1PeoplePersonIdWeekPlanIdFollowThroughPost<true>({
      client: this.client,
      path: { person_id: personId, plan_id: planId },
      body: { follow_through: followThrough, note: note ?? null },
      throwOnError: true,
    });
    return result.data;
  }

  /** Whether a planned activity was any good, once the person has said they went. */
  async recordPlannedEnjoyment(
    planId: string,
    enjoyment: Enjoyment,
    liked: LikedAspect[] = [],
    personId = 'mdm-lim',
  ) {
    const result = await plannedEnjoymentV1PeoplePersonIdWeekPlanIdEnjoymentPost<true>({
      client: this.client,
      path: { person_id: personId, plan_id: planId },
      body: { enjoyment, liked },
      throwOnError: true,
    });
    return result.data;
  }

  /**
   * The person's own control over a learned or stated preference: prefer, avoid (optionally
   * until a day) or forget. Senior-only; never rendered on a coordinator surface.
   */
  async stateActivityPreference(
    dimension: PreferenceDimension,
    value: string,
    stance: PreferenceStance,
    options: { until?: string; statedText?: string } = {},
    personId = 'mdm-lim',
  ) {
    const result =
      await stateActivityPreferenceV1PeoplePersonIdActivityPreferencesDimensionValuePut<true>({
        client: this.client,
        path: { person_id: personId, dimension, value },
        body: {
          stance,
          until: options.until ?? null,
          stated_text: options.statedText ?? null,
        },
        throwOnError: true,
      });
    return result.data;
  }

  /** Planned activities that can no longer happen. Proposals only -- nothing is ever swapped. */
  async replanNotices(personId = 'mdm-lim') {
    const result = await personReplanNoticesV1PeoplePersonIdReplanNoticesGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  /** The person's answer to a replan offer: this listing instead, on the same day. Returns the
   *  whole week back, because a swap moves more than the one row. */
  async replacePlannedActivity(planId: string, activityId: string, personId = 'mdm-lim') {
    const result = await replacePlannedActivityV1PeoplePersonIdWeekPlanIdReplacePost<true>({
      client: this.client,
      path: { person_id: personId, plan_id: planId },
      body: { activity_id: activityId },
      throwOnError: true,
    });
    return result.data;
  }

  /** "No thanks", recorded on the server so the same offer is not put again. The plan itself is
   *  untouched: declining a replacement is not declining the outing. */
  async declineReplanOffer(offerId: string, personId = 'mdm-lim') {
    const result = await declineReplanOfferV1PeoplePersonIdReplanOffersOfferIdDeclinePost<true>({
      client: this.client,
      path: { person_id: personId, offer_id: offerId },
      throwOnError: true,
    });
    return result.data;
  }

  /** `humanAction`/`overrideReason` are the override-memory record: what the coordinator chose
   *  to do about Care+'s recommendation, and — when they did not follow it — why. Both are
   *  optional on the contract so a caller recording only a status and a note records exactly
   *  that; the API rejects `override` with no reason. `contextGapCategory` is accepted only
   *  with `override` for `known_context` (422 otherwise); the response's `lesson` says what the
   *  review taught Care+. */
  async reviewCase(
    caseId: string,
    status: CaseStatus,
    reviewerNote: string,
    humanAction?: HumanAction,
    overrideReason?: OverrideReason,
    reachedTooLate?: boolean,
    contextGapCategory?: ContextGapCategory,
    // Sign-in off only: the API records the actor as "demo-script" and refuses it (403) otherwise.
    recordedByDemoScript?: boolean,
  ) {
    const result = await reviewCaseV1CasesCaseIdReviewPost<true>({
      client: this.client,
      path: { case_id: caseId },
      body: {
        status,
        reviewer_note: reviewerNote,
        human_action: humanAction,
        override_reason: overrideReason,
        reached_too_late: reachedTooLate,
        context_gap_category: contextGapCategory,
        recorded_by_demo_script: recordedByDemoScript,
      },
      throwOnError: true,
    });
    return result.data;
  }

  // ── Review setting, person by person (coordinator; ADR 0008) ───────────────
  //
  // Every change takes effect from the next simulated day. Errors arrive as `ApiHttpError`:
  // 404 unknown person/proposal/decision; 409 when the state moved on and the card should reload
  // (already decided, a stale `shownOnDay`, consent withdrawn, a cooldown, the weekly proposal
  // cap, manual set not yet allowed); 422 for a refused request (a looser setting approved without
  // confirming the cause, a manual value that breaks a rule, a system-only rejection reason).

  /** This person's live review setting, bounds, open proposal and history. Read-only. */
  async reviewThreshold(personId: string) {
    const result = await reviewThresholdStateV1CoordinatorPeoplePersonIdReviewThresholdGet<true>({
      client: this.client,
      path: { person_id: personId },
      throwOnError: true,
    });
    return result.data;
  }

  /** Code-computed replay of the live setting against a candidate over stored history. */
  async reviewThresholdReplay(personId: string, severityPct: number, persistenceDays: number) {
    const result =
      await reviewThresholdReplayV1CoordinatorPeoplePersonIdReviewThresholdReplayGet<true>({
        client: this.client,
        path: { person_id: personId },
        query: { severity_pct: severityPct, persistence_days: persistenceDays },
        throwOnError: true,
      });
    return result.data;
  }

  /** `shownOnDay` is the simulated day the coordinator was looking at (`state.current_day`). */
  async approveThresholdProposal(
    personId: string,
    proposalId: string,
    causeConfirmed: boolean,
    shownOnDay: string,
    note?: string,
    // Sign-in off only: the API records the actor as "demo-script" and refuses it (403) otherwise.
    recordedByDemoScript?: boolean,
  ) {
    const result =
      await approveThresholdProposalV1CoordinatorPeoplePersonIdReviewThresholdProposalsProposalIdApprovePost<true>(
        {
          client: this.client,
          path: { person_id: personId, proposal_id: proposalId },
          body: {
            cause_confirmed: causeConfirmed,
            shown_on_day: shownOnDay,
            note,
            recorded_by_demo_script: recordedByDemoScript,
          },
          throwOnError: true,
        },
      );
    return result.data;
  }

  async rejectThresholdProposal(
    personId: string,
    proposalId: string,
    reason: ReviewThresholdRejectionReason,
    note?: string,
  ) {
    const result =
      await rejectThresholdProposalV1CoordinatorPeoplePersonIdReviewThresholdProposalsProposalIdRejectPost<true>(
        {
          client: this.client,
          path: { person_id: personId, proposal_id: proposalId },
          body: { reason, note },
          throwOnError: true,
        },
      );
    return result.data;
  }

  /** Only once `state.manual_set_allowed`; otherwise 409. */
  async setThresholdManually(
    personId: string,
    severityPct: number,
    persistenceDays: number,
    note: string,
    shownOnDay: string,
  ) {
    const result =
      await setThresholdManuallyV1CoordinatorPeoplePersonIdReviewThresholdManualPost<true>({
        client: this.client,
        path: { person_id: personId },
        body: {
          threshold: { severity_pct: severityPct, persistence_days: persistenceDays },
          note,
          shown_on_day: shownOnDay,
        },
        throwOnError: true,
      });
    return result.data;
  }

  async confirmStartingThreshold(personId: string, shownOnDay: string) {
    const result =
      await confirmStartingThresholdV1CoordinatorPeoplePersonIdReviewThresholdConfirmStartingPost<true>(
        {
          client: this.client,
          path: { person_id: personId },
          body: { shown_on_day: shownOnDay },
          throwOnError: true,
        },
      );
    return result.data;
  }

  async reconfirmThreshold(personId: string, decisionId: string, shownOnDay: string) {
    const result =
      await reconfirmThresholdV1CoordinatorPeoplePersonIdReviewThresholdDecisionsDecisionIdReconfirmPost<true>(
        {
          client: this.client,
          path: { person_id: personId, decision_id: decisionId },
          body: { shown_on_day: shownOnDay },
          throwOnError: true,
        },
      );
    return result.data;
  }
}
