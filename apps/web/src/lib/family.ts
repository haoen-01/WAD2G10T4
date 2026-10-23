/**
 * The family-coordination model and its rules: who is in the group, when each person can help, and
 * who has taken which appointment. Pure and free of Vue, so `lib/family.test.ts` can run it under
 * Node's type stripping; `composables/useFamily.ts` wraps it in reactive state.
 *
 * The API stores all of it (`GET /v1/people/{id}/calendar`, `silverloop/family_calendar.py`, which
 * follows the same answering and helping rules as `respondTo`, `volunteerFor` and `stepBackFrom`
 * here). `fromCalendar` turns the API's answer into these shapes.
 */
import type { FamilyCalendar, RepeatRule } from '@silverloop/api-client';

import { spansOverlap, timeToMinutes } from './calendar';
import { formatClockTime, parseIsoDay } from './format-date';
import type { Badge } from './labels';

export type AppointmentKind = 'medical' | 'therapy' | 'activity' | 'errand';

/** What each kind is called on screen. The colour that goes with it is `.kind-*` in `theme.css`. */
export const KIND_LABELS: Record<AppointmentKind, string> = {
  medical: 'Medical visit',
  therapy: 'Therapy',
  activity: 'Activity',
  errand: 'Errand',
};

export interface Appointment {
  /** One day of the appointment: `<seriesId>@<YYYY-MM-DD>`. */
  id: string;
  /** The stored appointment. A repeating one has one `seriesId` and a different `id` each day. */
  seriesId?: string;
  repeat?: RepeatRule;
  title: string;
  kind: AppointmentKind;
  /** `YYYY-MM-DD`. */
  date: string;
  /** `HH:MM`, 24-hour. */
  start: string;
  end: string;
  location?: string;
  notes?: string;
}

export interface FamilyMember {
  id: string;
  name: string;
  /** "Daughter", "Grandson", … in the person's own words. */
  relationship: string;
  /** Which of the avatar colours this person wears. Only ever paired with their name. */
  colour: number;
}

export type AvailabilityStatus = 'available' | 'unavailable';
/** What the group can tell about one person for one appointment. */
export type MemberStatus = AvailabilityStatus | 'unknown';

/**
 * One answer to "can you help?". Without `appointmentId` it is a window on a date ("free on Friday
 * afternoon"); with it, it is the person's answer for that one appointment, and beats any window.
 */
export interface AvailabilityEntry {
  id: string;
  memberId: string;
  date: string;
  start: string;
  end: string;
  status: AvailabilityStatus;
  appointmentId?: string;
}

/** A person who has taken an appointment. An appointment can have several. */
export interface Assignment {
  appointmentId: string;
  memberId: string;
}

/** Everything the family group owns, and everything worth saving. Appointments are separate. */
export interface FamilyState {
  members: FamilyMember[];
  availability: AvailabilityEntry[];
  assignments: Assignment[];
  /** Who is using this screen: the signed-in member (`null` for the senior, who is not one). */
  currentMemberId: string | null;
}

export const RELATIONSHIPS = [
  'Daughter',
  'Son',
  'Granddaughter',
  'Grandson',
  'Spouse',
  'Niece',
  'Nephew',
  'Other family',
] as const;

/** How many avatar colours there are (`MemberAvatar.vue`). */
export const AVATAR_COLOURS = 6;

/** The parts of a day a person can offer, so nobody has to type a time to say "afternoon". */
export const DAY_PARTS = [
  { key: 'all-day', label: 'All day', short: 'All day', start: '00:00', end: '23:59' },
  {
    key: 'morning',
    label: 'Morning (8 am to 12 pm)',
    short: 'Morning',
    start: '08:00',
    end: '12:00',
  },
  {
    key: 'afternoon',
    label: 'Afternoon (12 pm to 5 pm)',
    short: 'Afternoon',
    start: '12:00',
    end: '17:00',
  },
  {
    key: 'evening',
    label: 'Evening (5 pm to 9 pm)',
    short: 'Evening',
    start: '17:00',
    end: '21:00',
  },
] as const;

/** The preset a window is exactly equal to, if any ("Morning"), so a list can say it in one word. */
export function dayPartOf(window: { start: string; end: string }) {
  return DAY_PARTS.find((part) => part.start === window.start && part.end === window.end) ?? null;
}

/** A window in words: its part of the day ("Afternoon") or else its times ("9:00 am to 11:00 am"). */
export function describeWindow(window: { start: string; end: string }): string {
  return (
    dayPartOf(window)?.short ?? `${formatClockTime(window.start)} to ${formatClockTime(window.end)}`
  );
}

const AVAILABILITY_BADGES: Record<AvailabilityStatus, Badge> = {
  available: { label: 'Available', tone: 'info' },
  unavailable: { label: 'Not available', tone: 'secondary' },
};

export const HELPING_BADGE: Badge = { label: 'Helping', tone: 'success' };

export const availabilityBadge = (status: AvailabilityStatus): Badge => AVAILABILITY_BADGES[status];

/**
 * The badge for a person who is not (yet) helping, or `null` when they have not said. Not having
 * answered is not a status to colour: the row says it in plain words instead.
 */
export const statusBadge = (status: MemberStatus): Badge | null =>
  status === 'unknown' ? null : AVAILABILITY_BADGES[status];

/** A short unique id. Not `crypto.randomUUID`, which a page served over plain http (a LAN address) lacks. */
export function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export function compareAppointments(a: Appointment, b: Appointment): number {
  return (
    a.date.localeCompare(b.date) || a.start.localeCompare(b.start) || a.title.localeCompare(b.title)
  );
}

/**
 * What one person has told the group about one appointment.
 *
 * Their own answer for that appointment wins. Otherwise their windows on that day decide: any
 * "not available" that shares time with the appointment means unavailable (someone busy for part of
 * it cannot do all of it), and "available" counts only when it covers the whole appointment.
 * Anything less certain than that is `unknown`, never a guess.
 */
export function statusFor(
  availability: readonly AvailabilityEntry[],
  memberId: string,
  appointment: Appointment,
): MemberStatus {
  const mine = availability.filter((entry) => entry.memberId === memberId);

  const direct = mine.find((entry) => entry.appointmentId === appointment.id);
  if (direct) return direct.status;

  const windows = mine.filter((entry) => !entry.appointmentId && entry.date === appointment.date);
  if (windows.some((w) => w.status === 'unavailable' && spansOverlap(w, appointment))) {
    return 'unavailable';
  }
  const covers = (w: AvailabilityEntry) =>
    timeToMinutes(w.start) <= timeToMinutes(appointment.start) &&
    timeToMinutes(appointment.end) <= timeToMinutes(w.end);
  return windows.some((w) => w.status === 'available' && covers(w)) ? 'available' : 'unknown';
}

/** The ids of the people who have taken an appointment, in the order they volunteered. */
export function helperIds(assignments: readonly Assignment[], appointmentId: string): string[] {
  return assignments.filter((a) => a.appointmentId === appointmentId).map((a) => a.memberId);
}

/** The slice of the state that answering and volunteering change. */
export interface Answers {
  availability: AvailabilityEntry[];
  assignments: Assignment[];
}

/**
 * "Available" or "Not available" for one appointment. Replaces the person's earlier answer for it,
 * and saying "not available" also takes them off the appointment: nobody helps with something they
 * cannot make.
 */
export function respondTo(
  answers: Answers,
  appointment: Appointment,
  memberId: string,
  status: AvailabilityStatus,
  entryId: string,
): Answers {
  const others = answers.availability.filter(
    (entry) => !(entry.memberId === memberId && entry.appointmentId === appointment.id),
  );
  const entry: AvailabilityEntry = {
    id: entryId,
    memberId,
    date: appointment.date,
    start: appointment.start,
    end: appointment.end,
    status,
    appointmentId: appointment.id,
  };
  return {
    availability: [...others, entry],
    assignments:
      status === 'unavailable'
        ? answers.assignments.filter(
            (a) => !(a.appointmentId === appointment.id && a.memberId === memberId),
          )
        : answers.assignments,
  };
}

/** "I'll help": takes the appointment, and so also says the person is available for it. */
export function volunteerFor(
  answers: Answers,
  appointment: Appointment,
  memberId: string,
  entryId: string,
): Answers {
  const answered = respondTo(answers, appointment, memberId, 'available', entryId);
  const already = answered.assignments.some(
    (a) => a.appointmentId === appointment.id && a.memberId === memberId,
  );
  return {
    availability: answered.availability,
    assignments: already
      ? answered.assignments
      : [...answered.assignments, { appointmentId: appointment.id, memberId }],
  };
}

/** "Step back": off the appointment, but the person's availability answer is left as it was. */
export function stepBackFrom(
  assignments: readonly Assignment[],
  appointmentId: string,
  memberId: string,
): Assignment[] {
  return assignments.filter((a) => !(a.appointmentId === appointmentId && a.memberId === memberId));
}

/** Whether an availability window can be saved: a real day, and a start that comes before the end. */
export function checkWindow(window: { date: string; start: string; end: string }): string | null {
  if (!parseIsoDay(window.date)) return 'Please choose a date.';
  if (!isClock(window.start) || !isClock(window.end)) return 'Please choose a start and end time.';
  if (timeToMinutes(window.start) >= timeToMinutes(window.end)) {
    return 'The end time needs to be after the start time.';
  }
  return null;
}

const isClock = (value: unknown): value is string =>
  typeof value === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value);

/** The API's calendar in the shapes the screens use. */
export function fromCalendar(calendar: FamilyCalendar): {
  appointments: Appointment[];
  state: FamilyState;
} {
  const appointments: Appointment[] = calendar.appointments.map((occurrence) => ({
    id: occurrence.occurrence_id,
    seriesId: occurrence.appointment_id,
    repeat: occurrence.repeat,
    title: occurrence.title,
    kind: occurrence.kind,
    date: occurrence.date,
    start: occurrence.start,
    end: occurrence.end,
    location: occurrence.location ?? undefined,
    notes: occurrence.notes ?? undefined,
  }));
  return {
    appointments: appointments.sort(compareAppointments),
    state: {
      members: calendar.members.map((member) => ({
        id: member.member_id,
        name: member.display_name,
        relationship: member.relationship,
        colour: member.colour,
      })),
      availability: calendar.availability.map((entry) => ({
        id: entry.entry_id,
        memberId: entry.member_id,
        date: entry.date,
        start: entry.start,
        end: entry.end,
        status: entry.status,
        ...(entry.occurrence_id ? { appointmentId: entry.occurrence_id } : {}),
      })),
      assignments: calendar.assignments.map((assignment) => ({
        appointmentId: assignment.occurrence_id,
        memberId: assignment.member_id,
      })),
      currentMemberId: calendar.members.find((member) => member.is_me)?.member_id ?? null,
    },
  };
}

/** How a repeating appointment is described next to its title. */
export const REPEAT_LABELS: Record<RepeatRule, string> = {
  none: 'Once',
  daily: 'Every day',
  weekly: 'Every week',
  monthly: 'Every month',
};
