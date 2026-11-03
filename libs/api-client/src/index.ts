import { createClient } from './generated/client';
import {
  advanceV1SimulationAdvancePost,
  healthHealthGet,
  interventionOutcomeV1InterventionsInterventionIdOutcomePost,
  interventionsV1InterventionsGet,
  meV1AuthMeGet,
  personMetricsV1PeoplePersonIdMetricsGet,
  personStateV1PeoplePersonIdStateGet,
  readinessReadyGet,
  resetDemoV1DemoResetPost,
  updateConsentV1PeoplePersonIdConsentPost,
} from './generated/sdk.gen';

import type { DeclineReason, OutcomeKind, ServerErrorCode } from './generated/types.gen';

export type {
  AdvanceRequest,
  AdvanceResponse,
  AttentionBand,
  AuditEvent,
  AuthRole,
  BaselineConfirmationQuestion,
  BaselineSummary,
  CaseResolution,
  CaseStatus,
  AgentStep,
  CatchUp,
  MyDay,
  SpeechRequest,
  SpeechVoice,
  ConsentRequest,
  ConsentResponse,
  ContextSignal,
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
  AppointmentDraft,
  AppointmentDraftRequest,
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
  // Asks and notifications
  HelperAsk,
  HelperAskList,
  HelperAskRequest,
  HelperAskState,
  NotificationItem,
  NotificationKind,
  NotificationPage,
  NotificationReadRequest,
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
  DailyMetric,
  DataQualityAssessment,
  Decision,
  DeclineReason,
  DecisionTraceStep,
  ContextAnswerOption,
  ContextAnswerValue,
  ContextQuestion,
  DemoResetResponse,
  HealthResponse,
  HumanAction,
  Intervention,
  OutcomeRequest,
  OutcomeResponse,
  OutcomeKind,
  OverrideReason,
  PersonState,
  PolicyGate,
  PriorOutreach,
  ReadinessResponse,
  ReviewCase,
  ReviewAction,
  ServerErrorBody,
  ServerErrorCode,
  SignalSummary,
  TraceStatus,
  ReviewThresholdNotice,
  ReviewThresholdNoticeKind,
  ContextGapCategory,
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
}
