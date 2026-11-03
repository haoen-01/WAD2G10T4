import type {
  AppointmentDraft,
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
  CatchUp,
  MyDay,
  CheckInRequest,
  CreateGroupRequest,
  DailyMetric,
  DeclineReason,
  FamilyActivityEntry,
  FamilyActivityPage,
  FamilyCalendar,
  HelperAsk,
  HelperAskList,
  HelperAskRequest,
  Intervention,
  LinkSeniorRequest,
  MeResponse,
  MyGroup,
  NotificationPage,
  NotificationReadRequest,
  OutcomeKind,
  PersonState,
  PinResponse,
  SeniorNameRequest,
  Task,
  TaskList,
  TaskRequest,
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

/** Senior only: a 10-minute, single-use PIN that lets a family member link them to a group. */
export async function getSeniorLinkPin(): Promise<PinResponse> {
  const response = await http.post<PinResponse>('/v1/me/link-pin');
  return response.data;
}

/**
 * Create a family group. With only the senior's name it starts with no senior linked; with the PIN
 * on the senior's screen the senior is linked at once. At least one of the two.
 */
export async function createGroup(
  relationship: string,
  senior: { seniorName?: string; seniorPin?: string },
): Promise<CareGroup> {
  const body: CreateGroupRequest = {
    relationship,
    senior_name: senior.seniorName ?? null,
    senior_pin: senior.seniorPin ?? null,
  };
  const response = await http.post<CareGroup>('/v1/groups', body);
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

/** Link the senior to a group that has none yet, with the PIN on the senior's screen. */
export async function linkSenior(groupId: string, seniorPin: string): Promise<CareGroup> {
  const body: LinkSeniorRequest = { senior_pin: seniorPin };
  const response = await http.post<CareGroup>(`/v1/groups/${groupId}/link-senior`, body);
  return response.data;
}

/** Fix the senior's name while they are not linked yet (afterwards it comes from their account). */
export async function renameSenior(groupId: string, seniorName: string): Promise<CareGroup> {
  const body: SeniorNameRequest = { senior_name: seniorName };
  const response = await http.put<CareGroup>(`/v1/groups/${groupId}/senior-name`, body);
  return response.data;
}

// ── Family calendar ──────────────────────────────────────────────────────────

/** The senior's appointments (each day of a repeating one), the family's availability and helpers. */
export async function getCalendar(personId: string): Promise<FamilyCalendar> {
  const response = await http.get<FamilyCalendar>(`/v1/people/${personId}/calendar`);
  return response.data;
}

/** The family group's calendar, also before its senior is linked (`person_id` is then null). */
export async function getGroupCalendar(groupId: string): Promise<FamilyCalendar> {
  const response = await http.get<FamilyCalendar>(`/v1/groups/${groupId}/calendar`);
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
/** Fill in the appointment form from what was typed. Saves nothing; `createAppointment` does. */
export async function draftAppointment(groupId: string, text: string): Promise<AppointmentDraft> {
  const response = await http.post<AppointmentDraft>(`/v1/groups/${groupId}/appointments/draft`, {
    text,
  });
  return response.data;
}

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

// ── Tasks ────────────────────────────────────────────────────────────────────

/** The family group's tasks and the days ticked off, also before its senior is linked. */
export async function getGroupTasks(groupId: string): Promise<TaskList> {
  const response = await http.get<TaskList>(`/v1/groups/${groupId}/tasks`);
  return response.data;
}

/** The senior's tasks: what the senior's own screen reads. */
export async function getPersonTasks(personId: string): Promise<TaskList> {
  const response = await http.get<TaskList>(`/v1/people/${personId}/tasks`);
  return response.data;
}

export async function createTask(groupId: string, task: TaskRequest): Promise<Task> {
  const response = await http.post<Task>(`/v1/groups/${groupId}/tasks`, task);
  return response.data;
}

/** Changes a task (every day of it, if it repeats). Days already ticked off stay ticked off. */
export async function updateTask(
  groupId: string,
  taskId: string,
  task: TaskRequest,
): Promise<Task> {
  const response = await http.put<Task>(`/v1/groups/${groupId}/tasks/${taskId}`, task);
  return response.data;
}

/** Removes the task, every day of it, and its ticks. */
export async function deleteTask(groupId: string, taskId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/tasks/${taskId}/delete`);
}

/** A family member ticks one day of a task done (or not): today or a past day. */
export async function setGroupTaskDay(
  groupId: string,
  taskId: string,
  day: string,
  done: boolean,
): Promise<void> {
  await http.put(`/v1/groups/${groupId}/tasks/${taskId}/days/${day}`, { done });
}

/** The senior ticks one of today's tasks done (or not). */
export async function setPersonTaskDay(
  personId: string,
  taskId: string,
  day: string,
  done: boolean,
): Promise<void> {
  await http.put(`/v1/people/${personId}/tasks/${taskId}/days/${day}`, { done });
}

/** The senior's watch: connected or not, last sync and battery. Simulated until a real device. */
export async function getWearable(personId: string): Promise<WearableStatus> {
  const response = await http.get<WearableStatus>(`/v1/people/${personId}/wearable`);
  return response.data;
}

/** "Read my day": a short script of the senior's day, for the browser to read aloud. */
export async function getMyDay(personId: string): Promise<MyDay> {
  const response = await http.get<MyDay>(`/v1/people/${personId}/my-day`);
  return response.data;
}

// ── Family activity feed ─────────────────────────────────────────────────────

/** "Since you last visited": what changed after `since`, what needs someone, today's tasks. */
export async function getCatchUp(groupId: string, since: string | null): Promise<CatchUp> {
  const response = await http.get<CatchUp>(`/v1/groups/${groupId}/catch-up`, {
    params: since ? { since } : {},
  });
  return response.data;
}

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

// ── Asks (one member asking another to take a day) and the bell's notifications ──

/**
 * Asks a named active member to take one day that needs a helper. 409 while someone is already
 * asked for that day; 422 for yourself, a current helper, a day that has started or is covered.
 */
export async function createAsk(
  groupId: string,
  occurrenceId: string,
  askedMemberId: string,
): Promise<HelperAsk> {
  const body: HelperAskRequest = { occurrence_id: occurrenceId, asked_member_id: askedMemberId };
  const response = await http.post<HelperAsk>(`/v1/groups/${groupId}/asks`, body);
  return response.data;
}

/** The group's open asks, oldest first (each says whether you can answer or withdraw it). */
export async function getOpenAsks(groupId: string): Promise<HelperAsk[]> {
  const response = await http.get<HelperAskList>(`/v1/groups/${groupId}/asks`, {
    params: { state: 'open' },
  });
  return response.data.asks;
}

/** The asked member says yes, and so becomes the helper. 409 once the ask has ended. */
export async function acceptAsk(groupId: string, askId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/asks/${askId}/accept`);
}

/** The asked member says no; the day needs a helper again. */
export async function declineAsk(groupId: string, askId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/asks/${askId}/decline`);
}

/** The asker takes the ask back. */
export async function withdrawAsk(groupId: string, askId: string): Promise<void> {
  await http.post(`/v1/groups/${groupId}/asks/${askId}/withdraw`);
}

/** Your notifications across all your family groups, newest first, with the unread count. */
export async function getNotifications(
  options: { limit?: number; before?: string } = {},
): Promise<NotificationPage> {
  const response = await http.get<NotificationPage>('/v1/me/notifications', {
    params: { limit: options.limit, before: options.before },
  });
  return response.data;
}

/** Marks some of your notifications read, or all of them. Ids that are not yours are ignored. */
export async function markNotificationsRead(which: string[] | 'all'): Promise<void> {
  const body: NotificationReadRequest =
    which === 'all' ? { all: true } : { notification_ids: which };
  await http.post('/v1/me/notifications/read', body);
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
