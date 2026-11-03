/**
 * The rules behind the calendar's direct-manipulation features. Pure and free of Vue, so
 * `lib/planner.test.ts` can run it under Node's type stripping.
 *
 * - Painting availability: a week of hour slots a family member drags across, turned into the
 *   same availability windows the rest of the app (and the API) already uses.
 * - Who is free: how many of the family can go to an appointment on a given day and time, which
 *   the calendar shows as a heatmap while choosing a day or dragging an appointment.
 */
import { DAY_PARTS, dayPartOf, statusFor } from './family';
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

/** The first and last hour the painter covers: 08:00 and 21:00. */
export const PAINT_START = PAINT_SLOTS[0].start;
export const PAINT_END = PAINT_SLOTS[PAINT_SLOTS.length - 1].end;

/** A person's own windows on a day: the "free on Friday afternoon" kind, not appointment answers. */
export function ownWindowsOn(
  availability: readonly AvailabilityEntry[],
  memberId: string,
  day: string,
) {
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
  const windows = ownWindowsOn(availability, memberId, day);
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

type NewWindow = { date: string; start: string; end: string; status: AvailabilityStatus };

/**
 * What saving a painted day means: which of the person's windows on that day to remove and which
 * to add. Nothing at all when the painting matches what is already saved.
 *
 * The painter only covers 8 am to 9 pm. So only windows that reach into those hours are replaced,
 * and the parts of them outside the painter (an "All day" window's 00:00 to 08:00 and 21:00 to
 * 23:59) are put back with the same status. Windows wholly outside those hours, and answers to
 * appointments, are left alone.
 */
export function paintChanges(
  availability: readonly AvailabilityEntry[],
  memberId: string,
  day: string,
  painted: readonly SlotStatus[],
) {
  const before = slotStatuses(availability, memberId, day);
  if (before.every((status, index) => status === painted[index])) {
    return { remove: [] as string[], add: [] as NewWindow[] };
  }
  const covered = ownWindowsOn(availability, memberId, day).filter(
    (entry) => entry.start < PAINT_END && entry.end > PAINT_START,
  );
  const edges: NewWindow[] = [];
  for (const entry of covered) {
    if (entry.start < PAINT_START) {
      edges.push({ date: day, start: entry.start, end: PAINT_START, status: entry.status });
    }
    if (entry.end > PAINT_END) {
      edges.push({ date: day, start: PAINT_END, end: entry.end, status: entry.status });
    }
  }
  return {
    remove: covered.map((entry) => entry.id),
    add: [...edges, ...windowsFromSlots(day, painted)],
  };
}

/** One of the quick picks: "all-day", "morning", "afternoon" or "evening" (`DAY_PARTS`). */
export type DayPartKey = (typeof DAY_PARTS)[number]['key'];

/**
 * The quick picks that are on for a person's day: a part is on only when a "free" window matches
 * it exactly, so an hour-by-hour window never lights up a quick pick it only overlaps.
 */
export function activeDayParts(
  availability: readonly AvailabilityEntry[],
  memberId: string,
  day: string,
): Set<DayPartKey> {
  const on = new Set<DayPartKey>();
  for (const entry of ownWindowsOn(availability, memberId, day)) {
    const part = entry.status === 'available' ? dayPartOf(entry) : null;
    if (part) on.add(part.key);
  }
  return on;
}

/**
 * What tapping one quick pick means, as removals and additions through the same API calls as the
 * painter:
 * - a part that is already on (an exact match) turns off;
 * - "All day" replaces the person's other "free" windows that day with one 00:00 to 23:59 window;
 * - any other part adds its window;
 * - "busy" windows are never touched, and neither are answers to appointments.
 */
export function quickPickChanges(
  availability: readonly AvailabilityEntry[],
  memberId: string,
  day: string,
  partKey: DayPartKey,
): { remove: string[]; add: NewWindow[] } {
  const part = DAY_PARTS.find((candidate) => candidate.key === partKey);
  if (!part) return { remove: [], add: [] };
  const free = ownWindowsOn(availability, memberId, day).filter(
    (entry) => entry.status === 'available',
  );
  const exact = free.filter((entry) => dayPartOf(entry)?.key === partKey);
  if (exact.length) return { remove: exact.map((entry) => entry.id), add: [] };
  const window: NewWindow = { date: day, start: part.start, end: part.end, status: 'available' };
  if (partKey === 'all-day') return { remove: free.map((entry) => entry.id), add: [window] };
  return { remove: [], add: [window] };
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
