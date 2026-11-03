/**
 * Small "what time is it for this person" helpers: the greeting, how far away a day is, when a visit
 * is in words, and which of today's tasks comes next. Pure and free of Vue, so `lib/today.test.ts` can run them under
 * Node's type stripping. The screens pass the clock in; nothing here reads it.
 */
import { addDays, timeToMinutes } from './calendar';
import { formatClockTime, formatIsoDay } from './format-date';

/** "Good morning" before noon, "Good afternoon" until 6 pm, then "Good evening". */
export function greetingFor(hour: number): string {
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

/** How far a day is from today, in words: "Today", "Tomorrow", "In 3 days", "Yesterday", … */
export function relativeDay(iso: string, today: string): string {
  if (iso === today) return 'Today';
  if (iso === addDays(today, 1)) return 'Tomorrow';
  if (iso === addDays(today, -1)) return 'Yesterday';
  const days = Math.round(
    (Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 864e5,
  );
  if (!Number.isFinite(days)) return '';
  return days > 0 ? `In ${days} days` : `${-days} days ago`;
}

/** "10:00 am – 11:30 am", or just the start when there is no later end. */
export function timeRange(start: string, end: string | null | undefined): string {
  const from = formatClockTime(start);
  if (!end || timeToMinutes(end) <= timeToMinutes(start)) return from;
  return `${from} – ${formatClockTime(end)}`;
}

/** A visit's actual day and times, "Fri, 24 Oct, 10:00 am – 11:30 am", never "In 7 days". */
export function visitWhen(date: string, start: string, end?: string | null): string {
  return `${formatIsoDay(date)}, ${timeRange(start, end)}`;
}

/** Minutes after midnight on a clock. */
export function minutesOf(date: Date): number {
  return date.getHours() * 60 + date.getMinutes();
}

/**
 * "in 25 minutes", "in 1 hour 30 minutes", "in about 6 hours", or "now" within a minute. Beyond two
 * hours the exact minutes stop mattering, so it rounds to the hour.
 */
export function untilWords(minutes: number): string {
  if (minutes <= 0) return 'now';
  if (minutes >= 120) return `in about ${Math.round(minutes / 60)} hours`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const h = hours === 1 ? '1 hour' : `${hours} hours`;
  const m = rest === 1 ? '1 minute' : `${rest} minutes`;
  if (hours === 0) return `in ${m}`;
  return rest === 0 ? `in ${h}` : `in ${h} ${m}`;
}

/**
 * The task to show as "next": the earliest unfinished one that is not yet past, or else the
 * earliest unfinished one at all (something overdue), or `null` when everything is done.
 */
export function nextTask<T extends { id: string; time: string }>(
  tasks: readonly T[],
  nowMinutes: number,
  done: ReadonlySet<string>,
): { task: T; overdue: boolean } | null {
  const open = tasks.filter((task) => !done.has(task.id));
  const upcoming = open.find((task) => timeToMinutes(task.time) >= nowMinutes);
  if (upcoming) return { task: upcoming, overdue: false };
  return open[0] ? { task: open[0], overdue: true } : null;
}
