import type {
  AccountRole,
  AssistantChatRequest,
  AssistantReply,
  AppointmentNote,
  AppointmentNoteRequest,
  AppointmentRequest,
  AvailabilityEntryOut,
  AvailabilityRequest,
  AvailabilityStatus,
  CalendarAppointment,
  CareGroup,
  CheckInRequest,
  DailyMetric,
  DeclineReason,
  FamilyActivityEntry,
  FamilyActivityPage,
  FamilyCalendar,
  Intervention,
  MeResponse,
  MyGroup,
  OutcomeKind,
  PersonState,
  PinResponse,
  WearableStatus,
} from '@silverloop/api-client';

import { http } from './http';

/**
 * Every call the screens make to the Care+ API, as plain Axios requests. The response types come
 * from `@silverloop/api-client`, which is generated from the API's OpenAPI description, so a change
 * on the server shows up here as a type error instead of a surprise at runtime.
 */

/** A person's current status: today's steps, their usual day, consent and the latest decision. */
export async function getPersonState(personId: string): Promise<PersonState> {
  const response = await http.get<PersonState>(`/v1/people/${personId}/state`);
  return response.data;
}

/** One reading per day for the last `days` days, oldest first. */
export async function getPersonMetrics(personId: string, days = 14): Promise<DailyMetric[]> {
  const response = await http.get<DailyMetric[]>(`/v1/people/${personId}/metrics`, {
    params: { days },
  });
  return response.data;
}

/** Every suggestion Care+ has made, with its status (`proposed` means waiting for a reply). */
export async function getInterventions(): Promise<Intervention[]> {
  const response = await http.get<Intervention[]>('/v1/interventions');
  return response.data;
}

/** The senior's reply to a suggestion: accepted, deferred or declined. */
export async function recordOutcome(
  interventionId: string,
  outcome: OutcomeKind,
  reason?: DeclineReason,
): Promise<void> {
  await http.post(`/v1/interventions/${interventionId}/outcome`, {
    outcome,
    reason: reason ?? null,
  });
}

// ── Accounts and family groups ───────────────────────────────────────────────

/** Who is signed in, the seniors they care for, and whether they still have to choose a role. */
export async function getMe(): Promise<MeResponse> {
  const response = await http.get<MeResponse>('/v1/me');
  return response.data;
}

/** Choose once, right after signing up: senior or family. */
export async function onboard(role: AccountRole, displayName: string): Promise<MeResponse> {
  const response = await http.post<MeResponse>('/v1/me/onboard', {
    role,
    display_name: displayName,
  });
  return response.data;
}

/** Senior only: a 15-minute, single-use PIN that lets a family member create their group. */
export async function getSeniorLinkPin(): Promise<PinResponse> {
  const response = await http.post<PinResponse>('/v1/me/link-pin');
  return response.data;
}

/** Create a senior's family group with the PIN on the senior's screen. */
export async function createGroup(seniorPin: string, relationship: string): Promise<CareGroup> {
  const response = await http.post<CareGroup>('/v1/groups', {
    senior_pin: seniorPin,
    relationship,
  });
  return response.data;
}

/** Ask to join a group with its join PIN. The answer is `pending` until a member approves. */
export async function joinGroup(pin: string, relationship: string): Promise<MyGroup> {
  const response = await http.post<MyGroup>('/v1/groups/join', { pin, relationship });
  return response.data;
}

export async function getGroup(groupId: string): Promise<CareGroup> {
  const response = await http.get<CareGroup>(`/v1/groups/${groupId}`);
  return response.data;
}

/** A new 7-day join PIN for the group, replacing the previous one. */
export async function getJoinPin(groupId: string): Promise<PinResponse> {
  const response = await http.post<PinResponse>(`/v1/groups/${groupId}/join-pin`);
  return response.data;
}

export async function approveMember(groupId: string, memberId: string): Promise<CareGroup> {
  const response = await http.post<CareGroup>(`/v1/groups/${groupId}/members/${memberId}/approve`);
  return response.data;
}

export async function declineMember(groupId: string, memberId: string): Promise<CareGroup> {
  const response = await http.post<CareGroup>(`/v1/groups/${groupId}/members/${memberId}/decline`);
  return response.data;
}

// ── Family calendar ──────────────────────────────────────────────────────────

/** The senior's appointments (each day of a repeating one), the family's availability and helpers. */
export async function getCalendar(personId: string): Promise<FamilyCalendar> {
  const response = await http.get<FamilyCalendar>(`/v1/people/${personId}/calendar`);
  return response.data;
}

export async function createAppointment(
  groupId: string,
  appointment: AppointmentRequest,
): Promise<CalendarAppointment> {
  const response = await http.post<CalendarAppointment>(
    `/v1/groups/${groupId}/appointments`,
    appointment,
  );
  return response.data;
}

/** Changes an appointment (the whole series, if it repeats). */
export async function updateAppointment(
  groupId: string,
  appointmentId: string,
  appointment: AppointmentRequest,
): Promise<CalendarAppointment> {
  const response = await http.put<CalendarAppointment>(
    `/v1/groups/${groupId}/appointments/${appointmentId}`,
    appointment,
  );
  return response.data;
}

/** Removes the appointment, every day of it if it repeats. */
export async function deleteAppointment(groupId: string, appointmentId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/appointments/${appointmentId}/delete`);
}

export async function addAvailability(
  groupId: string,
  window: AvailabilityRequest,
): Promise<AvailabilityEntryOut> {
  const response = await http.post<AvailabilityEntryOut>(
    `/v1/groups/${groupId}/availability`,
    window,
  );
  return response.data;
}

export async function removeAvailability(groupId: string, entryId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/availability/${entryId}/delete`);
}

/** Available or not for one day of an appointment. */
export async function answerOccurrence(
  groupId: string,
  occurrenceId: string,
  status: AvailabilityStatus,
): Promise<void> {
  await http.post(`/v1/groups/${groupId}/answers`, { occurrence_id: occurrenceId, status });
}

/** "I'll help" with one day of an appointment. */
export async function volunteerFor(groupId: string, occurrenceId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/helpers`, { occurrence_id: occurrenceId });
}

export async function stepBackFrom(groupId: string, occurrenceId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/helpers/step-back`, { occurrence_id: occurrenceId });
}

/** The senior's watch: connected or not, last sync and battery. Simulated until a real device. */
export async function getWearable(personId: string): Promise<WearableStatus> {
  const response = await http.get<WearableStatus>(`/v1/people/${personId}/wearable`);
  return response.data;
}

// ── Family activity feed ─────────────────────────────────────────────────────

/** The group's feed, newest first. Pass the last page's `next_before` as `before` for older entries. */
export async function getGroupActivity(
  groupId: string,
  options: { limit?: number; before?: string } = {},
): Promise<FamilyActivityPage> {
  const response = await http.get<FamilyActivityPage>(`/v1/groups/${groupId}/activity`, {
    params: { limit: options.limit, before: options.before },
  });
  return response.data;
}

/** A family member tells the group they were in touch with the senior. Care+ sends nothing. */
export async function checkIn(groupId: string, body: CheckInRequest): Promise<FamilyActivityEntry> {
  const response = await http.post<FamilyActivityEntry>(`/v1/groups/${groupId}/check-ins`, body);
  return response.data;
}

// ── Appointment notes (one day of an appointment, for the family group only) ──

/** The day's notes, oldest first. `appointmentId` is the stored appointment (`seriesId`), not a day. */
export async function getAppointmentNotes(
  groupId: string,
  appointmentId: string,
  date: string,
): Promise<AppointmentNote[]> {
  const response = await http.get<AppointmentNote[]>(
    `/v1/groups/${groupId}/appointments/${appointmentId}/notes`,
    { params: { date } },
  );
  return response.data;
}

/** Adds a note (1 to 500 characters) to one day. A day that already holds 100 notes answers 409. */
export async function addAppointmentNote(
  groupId: string,
  appointmentId: string,
  note: AppointmentNoteRequest,
): Promise<AppointmentNote> {
  const response = await http.post<AppointmentNote>(
    `/v1/groups/${groupId}/appointments/${appointmentId}/notes`,
    note,
  );
  return response.data;
}

/** Removes your own note; another member's note answers 403. */
export async function deleteAppointmentNote(groupId: string, noteId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/notes/${noteId}/delete`);
}

/**
 * One answer from the Care+ assistant. The AI is called by the API with its own key (never from
 * here); emergencies and questions about medicines get a fixed answer. Too many questions in a
 * short time answers 429.
 */
export async function askAssistant(request: AssistantChatRequest): Promise<AssistantReply> {
  const response = await http.post<AssistantReply>('/v1/assistant/chat', request, {
    timeout: 30_000,
  });
  return response.data;
}
