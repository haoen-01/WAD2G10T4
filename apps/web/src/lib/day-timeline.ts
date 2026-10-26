/**
 * The rules behind Home's day timeline: one day of the senior's care laid out by the hour, so the
 * family sees at a glance what is on, what is done, who is helping and who has been in touch.
 * Today it is live: a "Now" line moves along, and anything before it counts as passed. For an
 * earlier day it is a record of what happened. Pure and relative-import only, so
 * `lib/day-timeline.test.ts` can run it under Node's type stripping.
 *
 * Only things with a real time are placed: appointments (their start and end), tasks (their
 * scheduled time) and family updates (when they were shared). Steps are a daily total in this app,
 * with no hour-by-hour readings, so the timeline never invents an hourly step line.
 */

/** Which lane a moment sits in. */
export type TimelineLane = 'appointment' | 'task' | 'family';

export interface TimelineMoment {
  id: string;
  lane: TimelineLane;
  /** Minutes after midnight, 0 to 1439. */
  start: number;
  /** Appointments only: when it ends, in minutes after midnight. */
  end?: number;
  title: string;
  /** A short second line: who is going, "Done", the family member's note. */
  detail: string;
  /** An icon name from `Icon.vue`. */
  icon: string;
  /** Appointments: the event type, for its colour (`kind-*`). */
  kind?: string;
  /** Tasks: ticked off that day. */
  done?: boolean;
  /** Appointments: still needs someone to go along. */
  open?: boolean;
  /** Appointments: the family members going. Family updates: the one who shared it. */
  people?: { id: string; name: string; colour: number }[];
  /** Appointments: the viewer is one of the people going. */
  mine?: boolean;
  /** Appointments: the calendar's own id, for "I'll go". */
  appointmentId?: string;
  /** Appointments: where it is. */
  place?: string;
  /** Tasks: the task list's own id, for ticking it off from here. */
  taskId?: string;
}

/** `HH:MM` as minutes after midnight, or `null` when it is not a clock time. */
export function clockToMinutes(value: string | null | undefined): number | null {
  const match = /^(\d{2}):(\d{2})$/.exec(value ?? '');
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

/** Minutes after midnight as "9:30 am". */
export function minutesToLabel(minutes: number): string {
  const clamped = Math.max(0, Math.min(1439, Math.round(minutes)));
  const hour = Math.floor(clamped / 60);
  const minute = String(clamped % 60).padStart(2, '0');
  return `${hour % 12 === 0 ? 12 : hour % 12}:${minute} ${hour < 12 ? 'am' : 'pm'}`;
}

/**
 * A timestamp's day and minute in a time zone (Singapore for this app), so a family update shared
 * at 23:30 UTC lands on the right Singapore day. `null` for an unreadable timestamp.
 */
export function momentInZone(
  value: string,
  timeZone: string,
): { day: string; minute: number } | null {
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return null;
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(moment);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? '';
  return {
    day: `${get('year')}-${get('month')}-${get('day')}`,
    minute: Number(get('hour')) * 60 + Number(get('minute')),
  };
}

/** The day's moments in time order (then appointments, tasks, family; then by title). */
export function sortMoments(moments: readonly TimelineMoment[]): TimelineMoment[] {
  const laneOrder: Record<TimelineLane, number> = { appointment: 0, task: 1, family: 2 };
  return [...moments].sort(
    (a, b) =>
      a.start - b.start || laneOrder[a.lane] - laneOrder[b.lane] || a.title.localeCompare(b.title),
  );
}

/**
 * The stretch of the day to draw, in minutes: 7 am to 10 pm, widened to the hour around anything
 * earlier or later, so nothing falls off the ends.
 */
export function dayWindow(moments: readonly TimelineMoment[]): { from: number; to: number } {
  let from = 7 * 60;
  let to = 22 * 60;
  for (const moment of moments) {
    from = Math.min(from, Math.floor(moment.start / 60) * 60);
    to = Math.max(to, Math.ceil((moment.end ?? moment.start + 1) / 60) * 60);
  }
  return { from: Math.max(0, from), to: Math.min(24 * 60, to) };
}

/** Where a minute sits along the window, 0 to 1 (clamped). */
export function positionOf(minute: number, window: { from: number; to: number }): number {
  const span = window.to - window.from;
  if (span <= 0) return 0;
  return Math.max(0, Math.min(1, (minute - window.from) / span));
}

/** Whether a moment has started by `minute` (the "Now" line, today). */
export function hasHappened(moment: TimelineMoment, minute: number): boolean {
  return moment.start <= minute;
}

/** Whether an appointment is under way at `minute`. */
export function isUnderway(moment: TimelineMoment, minute: number): boolean {
  return moment.end !== undefined && moment.start <= minute && minute < moment.end;
}

/**
 * Which moment to describe when nothing has been tapped, today: an appointment under way, else
 * the next thing coming up, else the latest thing that happened. `null` for an empty day.
 */
export function focusAt(moments: readonly TimelineMoment[], minute: number): TimelineMoment | null {
  const sorted = sortMoments(moments);
  const underway = sorted.filter((moment) => isUnderway(moment, minute));
  if (underway.length) return underway[underway.length - 1];
  const next = sorted.find((moment) => moment.start > minute);
  if (next) return next;
  return sorted.length ? sorted[sorted.length - 1] : null;
}

/** The day in numbers, for the chips above the timeline. */
export function daySummary(moments: readonly TimelineMoment[]) {
  const tasks = moments.filter((moment) => moment.lane === 'task');
  return {
    appointments: moments.filter((moment) => moment.lane === 'appointment').length,
    tasks: tasks.length,
    tasksDone: tasks.filter((moment) => moment.done).length,
    family: moments.filter((moment) => moment.lane === 'family').length,
  };
}

/**
 * An earlier day as a record of what happened: the tasks ticked off and the ones that were not,
 * the appointments (with who was going), and how the family kept in touch. Each list is in time
 * order.
 */
export function dayRecord(moments: readonly TimelineMoment[]) {
  const sorted = sortMoments(moments);
  return {
    done: sorted.filter((moment) => moment.lane === 'task' && moment.done),
    missed: sorted.filter((moment) => moment.lane === 'task' && !moment.done),
    appointments: sorted.filter((moment) => moment.lane === 'appointment'),
    family: sorted.filter((moment) => moment.lane === 'family'),
  };
}
