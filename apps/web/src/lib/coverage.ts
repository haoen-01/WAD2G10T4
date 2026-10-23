/**
 * Who is covering what: the counts behind the "needs a helper" reminders and the family's share of
 * the care. Pure and free of Vue, so `lib/coverage.test.ts` can run it under Node's type stripping.
 * It only reads the family state; `lib/family.ts` still owns every rule that changes it.
 */
import { addDays } from './calendar';
import type { Appointment, Assignment, FamilyMember } from './family';

/** Appointments from `today` up to and including `days` days later, in calendar order. */
export function upcomingWithin(
  appointments: readonly Appointment[],
  today: string,
  days: number,
): Appointment[] {
  const last = addDays(today, days);
  return appointments.filter(
    (appointment) => appointment.date >= today && appointment.date <= last,
  );
}

export function hasHelper(assignments: readonly Assignment[], appointmentId: string): boolean {
  return assignments.some((assignment) => assignment.appointmentId === appointmentId);
}

/**
 * "Not every event needs a helper": an appointment can say nobody needs to go along (a phone
 * check-in, something the senior does alone). Those never count as "needs a helper" anywhere.
 *
 * The flag is `needsHelper: false` on an appointment. The API does not send it yet, so today every
 * appointment needs a helper and nothing changes. Once the backend adds `needs_helper` and
 * `fromCalendar` (`lib/family.ts`) copies it across, this starts working on every screen that
 * uses these functions (Calendar, Home, Family) with no other change.
 */
export function needsHelper(appointment: Appointment): boolean {
  return (appointment as Appointment & { needsHelper?: boolean }).needsHelper !== false;
}

/**
 * Whether the API saves `needs_helper`. While it is `false`, the add/edit form hides its "Someone
 * needs to go along" tick box, because a choice that is not saved would be lost on reload. Set it
 * to `true` once the backend field exists.
 */
export const NEEDS_HELPER_SAVED = false;

/** Whether an appointment still needs someone: it needs a helper and nobody has taken it. */
export function stillNeedsHelper(
  assignments: readonly Assignment[],
  appointment: Appointment,
): boolean {
  return needsHelper(appointment) && !hasHelper(assignments, appointment.id);
}

/** The appointments that need a helper and nobody has taken yet. */
export function needingHelp(
  appointments: readonly Appointment[],
  assignments: readonly Assignment[],
): Appointment[] {
  return appointments.filter((appointment) => stillNeedsHelper(assignments, appointment));
}

export interface Coverage {
  total: number;
  covered: number;
  /** 0 to 1. An empty list counts as fully covered: there is nothing left to do. */
  ratio: number;
}

/** How many of the appointments that need a helper have one. The others are left out. */
export function coverageOf(
  appointments: readonly Appointment[],
  assignments: readonly Assignment[],
): Coverage {
  const counted = appointments.filter(needsHelper);
  const total = counted.length;
  const covered = counted.filter((a) => hasHelper(assignments, a.id)).length;
  return { total, covered, ratio: total === 0 ? 1 : covered / total };
}

export interface HelperLoad {
  member: FamilyMember;
  count: number;
}

/**
 * How many of the given appointments each member is helping with, busiest first, then by name. Used
 * to show whether one person is carrying most of the care.
 */
export function helperLoad(
  members: readonly FamilyMember[],
  assignments: readonly Assignment[],
  appointments: readonly Appointment[],
): HelperLoad[] {
  const ids = new Set(appointments.map((appointment) => appointment.id));
  return members
    .map((member) => ({
      member,
      count: assignments.filter((a) => a.memberId === member.id && ids.has(a.appointmentId)).length,
    }))
    .sort((a, b) => b.count - a.count || a.member.name.localeCompare(b.member.name));
}

/**
 * A one-line reading of the share of care, or `null` when it is fair enough to say nothing. It
 * speaks up only when one person has more than half of the taken appointments and at least three.
 */
export function loadWarning(loads: readonly HelperLoad[]): string | null {
  const taken = loads.reduce((sum, load) => sum + load.count, 0);
  const busiest = loads[0];
  if (!busiest || busiest.count < 3 || busiest.count * 2 <= taken) return null;
  return `${busiest.member.name} is helping with ${busiest.count} of ${taken}. Could someone else take one?`;
}
