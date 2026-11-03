/**
 * The rules behind the calendar's direct-manipulation features. Pure and free of Vue, so
 * `lib/planner.test.ts` can run it under Node's type stripping.
 *
 * - Painting availability: a week of hour slots a family member drags across, turned into the
 *   same availability windows the rest of the app (and the API) already uses.
 * - Who is free: how many of the family can go to an appointment on a given day and time, which
 *   the calendar shows as a heatmap while choosing a day or dragging an appointment.
 */
import { statusFor } from './family';
import type { Appointment, AvailabilityEntry, AvailabilityStatus, FamilyMember } from './family';

/** A painted slot: free, busy, or not said. */
export type SlotStatus = AvailabilityStatus | null;

/** The hours a family member can paint: 8 am to 9 pm, one slot per hour. */
export const PAINT_SLOTS = Array.from({ length: 13 }, (_, index) => {
  const hour = 8 + index;
  const clock = (h: number) => `${String(h).padStart(2, '0')}:00`;
  return {
    start: clock(hour),
    end: clock(hour + 1),
    label: hour === 12 ? '12 pm' : hour > 12 ? `${hour - 12} pm` : `${hour} am`,
  };
});

/** A person's own windows on a day: the "free on Friday afternoon" kind, not appointment answers. */
function windowsOn(availability: readonly AvailabilityEntry[], memberId: string, day: string) {
  return availability.filter(
    (entry) => entry.memberId === memberId && entry.date === day && !entry.appointmentId,
  );
}

/**
 * What one person has said about each hour slot of a day. A slot any "busy" window touches is
 * busy (the same rule as `statusFor`); otherwise any "free" window touching it makes it free.
 */
export function slotStatuses(
  availability: readonly AvailabilityEntry[],
  memberId: string,
  day: string,
): SlotStatus[] {
  const windows = windowsOn(availability, memberId, day);
  return PAINT_SLOTS.map((slot) => {
    const touching = windows.filter((w) => w.start < slot.end && w.end > slot.start);
    if (touching.some((w) => w.status === 'unavailable')) return 'unavailable';
    return touching.length ? 'available' : null;
  });
}

/** Painted slots back into windows: each run of the same status becomes one window. */
export function windowsFromSlots(
  day: string,
  slots: readonly SlotStatus[],
): { date: string; start: string; end: string; status: AvailabilityStatus }[] {
  const windows: { date: string; start: string; end: string; status: AvailabilityStatus }[] = [];
  slots.forEach((status, index) => {
    if (!status) return;
    const last = windows.at(-1);
    if (last && last.status === status && last.end === PAINT_SLOTS[index].start) {
      last.end = PAINT_SLOTS[index].end;
    } else {
      const { start, end } = PAINT_SLOTS[index];
      windows.push({ date: day, start, end, status });
    }
  });
  return windows;
}

/**
 * What saving a painted day means: which of the person's windows on that day to remove and which
 * to add. Nothing at all when the painting matches what is already saved.
 */
export function paintChanges(
  availability: readonly AvailabilityEntry[],
  memberId: string,
  day: string,
  painted: readonly SlotStatus[],
) {
  const before = slotStatuses(availability, memberId, day);
  if (before.every((status, index) => status === painted[index])) {
    return { remove: [] as string[], add: [] as ReturnType<typeof windowsFromSlots> };
  }
  return {
    remove: windowsOn(availability, memberId, day).map((entry) => entry.id),
    add: windowsFromSlots(day, painted),
  };
}

/** The family members who can go to something on `day` from `start` to `end`. */
export function freeMembers(
  availability: readonly AvailabilityEntry[],
  members: readonly FamilyMember[],
  day: string,
  start: string,
  end: string,
): FamilyMember[] {
  const probe: Appointment = { id: '', title: '', kind: 'activity', date: day, start, end };
  return members.filter((member) => statusFor(availability, member.id, probe) === 'available');
}

/** Who is free on each of the days, for the same times: the calendar's heatmap. */
export function heatFor(
  availability: readonly AvailabilityEntry[],
  members: readonly FamilyMember[],
  days: readonly string[],
  start: string,
  end: string,
): Record<string, FamilyMember[]> {
  return Object.fromEntries(
    days.map((day) => [day, freeMembers(availability, members, day, start, end)]),
  );
}
