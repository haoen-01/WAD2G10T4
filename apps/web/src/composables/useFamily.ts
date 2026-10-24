import type { AppointmentRequest, FamilyCalendar } from '@silverloop/api-client';
import { computed, reactive, ref, watch } from 'vue';

import { currentGroup, loadMe } from '@/composables/useMe';
import { showToast } from '@/composables/useToast';
import { DEMO_FAMILY_SUBS, setDemoMember, useViewMode } from '@/composables/useViewMode';
import { classifyApiError } from '@/lib/api-errors';
import { todayIso } from '@/lib/calendar';
import { AUTH_ENABLED } from '@/lib/config';
import {
  checkWindow,
  fromCalendar,
  helperIds,
  idToRemove,
  newId,
  respondTo,
  statusFor,
  stepBackFrom,
  swapEntryId,
  volunteerFor,
} from '@/lib/family';
import type { Appointment, AvailabilityStatus, FamilyState, MemberStatus } from '@/lib/family';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { paintChanges } from '@/lib/planner';
import type { SlotStatus } from '@/lib/planner';
import * as api from '@/services/careApi';

/**
 * The family calendar, shared by Home, Calendar, Family and the senior's own screen (a module
 * singleton, like `useAuth`, so they all read and change the same thing).
 *
 * The API stores it (`GET /v1/people/{id}/calendar`). Each screen that uses it reads it again when
 * it opens, and again when the family member picks another senior. A change shows at once (using
 * the same rules as the API, in `lib/family.ts`), is sent to the API, and the calendar is read back
 * once the changes in flight are saved, so the screen ends up showing exactly what is stored. A
 * change the API refuses is reported and undone by that read.
 */
const today = todayIso();
const appointments = reactive<Appointment[]>([]);
const state = reactive<FamilyState>({
  members: [],
  availability: [],
  assignments: [],
  currentMemberId: null,
});

/**
 * A tiny registry so other family-only code (the Home activity feed) can hear about changes made
 * here without this file importing it (the senior screen loads this file, and must not pull in
 * the feed or motion code). `saved`: the save queue drained. `viewer`: the demo switched member.
 */
export type FamilyChange = 'saved' | 'viewer';
const listeners = new Set<(change: FamilyChange) => void>();
export function onFamilyChange(listener: (change: FamilyChange) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
function notify(change: FamilyChange): void {
  for (const listener of listeners) listener(change);
}

const elderName = ref('Your senior');
const groupId = ref<string | null>(null);
const personId = ref<string | null>(null);
const loading = ref(false);
const loaded = ref(false);
const error = ref<string | null>(null);

/** Whose calendar to show: the senior's own, else the senior the family member has picked. */
async function resolvePerson(): Promise<string> {
  const me = await loadMe().catch(() => null);
  if (me?.role === 'senior' && me.person_id) return me.person_id;
  return currentGroup.value?.person_id ?? DEMO_PERSON_ID;
}

function applyCalendar(calendar: FamilyCalendar): void {
  const next = fromCalendar(calendar);
  appointments.splice(0, appointments.length, ...next.appointments);
  Object.assign(state, next.state);
  elderName.value = calendar.senior_name;
  groupId.value = calendar.group_id;
  personId.value = calendar.person_id;
}

let reading: Promise<void> | null = null;

/** Reads the calendar again. Calls made while a read is in flight share it. */
function refresh(): Promise<void> {
  reading ??= (async () => {
    loading.value = true;
    try {
      applyCalendar(await api.getCalendar(await resolvePerson()));
      error.value = null;
      loaded.value = true;
    } catch (caught) {
      error.value = classifyApiError(caught).message;
    } finally {
      loading.value = false;
      reading = null;
    }
  })();
  return reading;
}

// Picking another senior in the navbar shows their calendar.
watch(
  () => currentGroup.value?.group_id,
  (next, previous) => {
    if (loaded.value && next !== previous) void refresh();
  },
);

// ---- Saving changes: one at a time, then one read once they are all saved ----
let saving: Promise<void> = Promise.resolve();
let inFlight = 0;

function save(work: (group: string) => Promise<unknown>): Promise<void> {
  const group = groupId.value;
  if (!group) {
    showToast('Only family members in the group can change the calendar.');
    return Promise.resolve();
  }
  inFlight += 1;
  saving = saving
    .then(() => work(group))
    .then(
      () => undefined,
      (caught: unknown) => {
        showToast(classifyApiError(caught).message);
      },
    )
    .finally(() => {
      inFlight -= 1;
      if (inFlight === 0) {
        // Queue drained: temp ids are gone after the refresh, so the map need not grow all session.
        savedIds.clear();
        void refresh();
        // The senior screen shares this queue, and the family routes refuse a senior.
        if (groupId.value && useViewMode().mode.value !== 'senior') notify('saved');
      }
    });
  return saving;
}

/**
 * An availability window shows at once under a temporary id and gets its real one when the API
 * has saved it. Removing it before then (a double tap) must remove the saved entry, so the save
 * queue (which runs one change at a time) looks the real id up when the removal runs.
 */
const savedIds = new Map<string, string>();

function saveWindow(
  tempId: string,
  window: { date: string; start: string; end: string; status: AvailabilityStatus },
): Promise<void> {
  return save(async (group) => {
    const saved = await api.addAvailability(group, window);
    savedIds.set(tempId, saved.entry_id);
    state.availability = swapEntryId(state.availability, tempId, saved.entry_id);
  });
}

function saveRemoval(id: string): Promise<void> {
  return save(async (group) => {
    try {
      const realId = idToRemove(id, savedIds);
      if (realId) await api.removeAvailability(group, realId);
    } finally {
      savedIds.delete(id);
    }
  });
}

const currentMember = computed(
  () => state.members.find((member) => member.id === state.currentMemberId) ?? null,
);

function appointmentById(id: string): Appointment | undefined {
  return appointments.find((appointment) => appointment.id === id);
}

/**
 * Sign-in off only (the demo's "Viewing as"): act as another of the demo family. With sign-in on
 * you are always yourself, so this does nothing.
 */
function setCurrentMember(id: string): void {
  if (AUTH_ENABLED) return;
  const member = state.members.find((m) => m.id === id);
  const sub = member ? DEMO_FAMILY_SUBS[member.name] : undefined;
  if (!sub) return;
  setDemoMember(sub);
  state.currentMemberId = id;
  notify('viewer');
  void refresh();
}

/** Saves a window ("free on Friday afternoon") for the current member. Returns an error, if any. */
function addAvailability(chosen: {
  date: string;
  start: string;
  end: string;
  status: AvailabilityStatus;
}): string | null {
  const member = currentMember.value;
  if (!member) return 'Only family members in the group can share when they are free.';
  const problem = checkWindow(chosen);
  if (problem) return problem;
  const tempId = newId('saving');
  state.availability.push({ id: tempId, memberId: member.id, ...chosen });
  void saveWindow(tempId, chosen);
  return null;
}

function removeAvailability(id: string): void {
  state.availability = state.availability.filter((entry) => entry.id !== id);
  void saveRemoval(id);
}

function apply(next: {
  availability: FamilyState['availability'];
  assignments: FamilyState['assignments'];
}) {
  state.availability = next.availability;
  state.assignments = next.assignments;
}

/** The current member's answer for one appointment: available or not available. */
function respond(appointmentId: string, status: AvailabilityStatus): void {
  const appointment = appointmentById(appointmentId);
  if (!appointment || !currentMember.value) return;
  apply(respondTo(state, appointment, currentMember.value.id, status, newId('saving')));
  void save((group) => api.answerOccurrence(group, appointmentId, status));
}

/** "I'll help": the current member takes the appointment. */
function volunteer(appointmentId: string): void {
  const appointment = appointmentById(appointmentId);
  if (!appointment || !currentMember.value) return;
  apply(volunteerFor(state, appointment, currentMember.value.id, newId('saving')));
  void save((group) => api.volunteerFor(group, appointmentId));
}

/** The current member steps back from an appointment they had taken. */
function stepBack(appointmentId: string): void {
  if (!currentMember.value) return;
  state.assignments = stepBackFrom(state.assignments, appointmentId, currentMember.value.id);
  void save((group) => api.stepBackFrom(group, appointmentId));
}

/** Adds an appointment (once or repeating). Resolves once it is saved and the calendar read back. */
function addAppointment(appointment: AppointmentRequest): Promise<void> {
  return save((group) => api.createAppointment(group, appointment));
}

/** What the API takes for an appointment, from one already on the calendar. */
function requestOf(appointment: Appointment): AppointmentRequest {
  return {
    title: appointment.title,
    kind: appointment.kind,
    date: appointment.date,
    start: appointment.start,
    end: appointment.end,
    location: appointment.location ?? null,
    notes: appointment.notes ?? null,
    repeat: appointment.repeat ?? 'none',
    repeat_until: null,
  };
}

/**
 * Changes a one-off appointment. A repeating one is not changed here: the calendar does not know
 * its last day, so saving it would quietly make it repeat forever.
 */
function updateAppointment(appointment: Appointment, next: AppointmentRequest): Promise<void> {
  if (!appointment.seriesId || (appointment.repeat && appointment.repeat !== 'none')) {
    return Promise.resolve();
  }
  const seriesId = appointment.seriesId;
  // Show it at once (helpers stay attached to the old day until the read-back moves them).
  const index = appointments.findIndex((a) => a.id === appointment.id);
  if (index >= 0) {
    appointments.splice(index, 1, {
      ...appointment,
      ...next,
      location: next.location ?? undefined,
      notes: next.notes ?? undefined,
    });
  }
  return save((group) => api.updateAppointment(group, seriesId, next));
}

/** Moves a one-off appointment to another day, keeping its times. */
function moveAppointment(appointment: Appointment, date: string): Promise<void> {
  return updateAppointment(appointment, { ...requestOf(appointment), date });
}

/**
 * Saves a painted day for the current member: their windows on that day are replaced by the
 * painted ones. Does nothing when the painting matches what is saved.
 */
function paintDay(day: string, painted: SlotStatus[]): boolean {
  const member = currentMember.value;
  if (!member) return false;
  const { remove, add } = paintChanges(state.availability, member.id, day, painted);
  if (!remove.length && !add.length) return false;
  const added = add.map((window) => ({ tempId: newId('saving'), window }));
  state.availability = [
    ...state.availability.filter((entry) => !remove.includes(entry.id)),
    ...added.map(({ tempId, window }) => ({ id: tempId, memberId: member.id, ...window })),
  ];
  for (const id of remove) void saveRemoval(id);
  for (const { tempId, window } of added) void saveWindow(tempId, window);
  return true;
}

/** Removes an appointment, every day of it if it repeats. */
function removeAppointment(seriesId: string): Promise<void> {
  const keep = appointments.filter((appointment) => appointment.seriesId !== seriesId);
  appointments.splice(0, appointments.length, ...keep);
  return save((group) => api.deleteAppointment(group, seriesId));
}

function statusOf(memberId: string, appointment: Appointment): MemberStatus {
  return statusFor(state.availability, memberId, appointment);
}

export function useFamily() {
  // Every screen that shows the calendar reads it fresh when it opens.
  void refresh();
  return {
    elderName,
    today,
    appointments,
    state,
    loading,
    loaded,
    error,
    groupId,
    personId,
    currentMember,
    /** Sign-in off only: the demo can switch between family members. */
    canViewAs: !AUTH_ENABLED,
    refresh,
    setCurrentMember,
    addAvailability,
    removeAvailability,
    respond,
    volunteer,
    stepBack,
    addAppointment,
    updateAppointment,
    moveAppointment,
    paintDay,
    removeAppointment,
    statusOf,
    helperIdsOf: (appointmentId: string) => helperIds(state.assignments, appointmentId),
  };
}
