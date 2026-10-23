/**
 * Date and clock helpers for the calendar. Pure and import-light so `lib/calendar.test.ts` can run
 * them under Node's type stripping.
 *
 * A day is a `YYYY-MM-DD` string and a clock time is `HH:MM` (24-hour), the same shapes the rest of
 * the app uses. Day arithmetic is done in UTC so a daylight-saving change or the machine's time
 * zone can never move a day; only `todayIso` reads the machine's own calendar, because "today" is
 * whatever the person looking at the screen sees on their wall calendar.
 */

export interface CalendarCell {
  iso: string;
  /** Day of the month, 1-31. */
  day: number;
  /** False for the days of the neighbouring months that fill out the first and last week. */
  inMonth: boolean;
}

/** A month to show; `month` is 1-12. */
export interface MonthRef {
  year: number;
  month: number;
}

const pad = (value: number, width = 2) => String(value).padStart(width, '0');

/** `YYYY-MM-DD` from its parts (`month` is 1-12). */
export function toIsoDay(year: number, month: number, day: number): string {
  return `${pad(year, 4)}-${pad(month)}-${pad(day)}`;
}

/** Today on this machine's calendar, as `YYYY-MM-DD`. */
export function todayIso(now: Date = new Date()): string {
  return toIsoDay(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

function fromUtc(date: Date): string {
  return toIsoDay(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

/** The day `days` after `iso` (before it, when negative). An unreadable day comes back as given. */
export function addDays(iso: string, days: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  return fromUtc(
    new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + days)),
  );
}

/** The month a day falls in. An unreadable day reads as January of year 0 rather than crashing. */
export function monthOf(iso: string): MonthRef {
  const match = /^(\d{4})-(\d{2})/.exec(iso);
  return match ? { year: Number(match[1]), month: Number(match[2]) } : { year: 0, month: 1 };
}

/** The month `delta` months after (or before) `ref`. */
export function shiftMonth({ year, month }: MonthRef, delta: number): MonthRef {
  const index = year * 12 + (month - 1) + delta;
  return { year: Math.floor(index / 12), month: (((index % 12) + 12) % 12) + 1 };
}

/**
 * The weeks that show one month, Sunday first. The days of the neighbouring months that fill the
 * first and last week are included (and marked `inMonth: false`), so every row has seven days.
 */
export function monthGrid({ year, month }: MonthRef): CalendarCell[][] {
  const daysBeforeFirst = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const total = Math.ceil((daysBeforeFirst + daysInMonth) / 7) * 7;

  const weeks: CalendarCell[][] = [];
  for (let index = 0; index < total; index += 1) {
    const date = new Date(Date.UTC(year, month - 1, 1 - daysBeforeFirst + index));
    if (index % 7 === 0) weeks.push([]);
    weeks[weeks.length - 1].push({
      iso: fromUtc(date),
      day: date.getUTCDate(),
      inMonth: date.getUTCMonth() === month - 1,
    });
  }
  return weeks;
}

/** Minutes after midnight for `HH:MM`. */
export function timeToMinutes(value: string): number {
  const [hour, minute] = value.split(':');
  return Number(hour) * 60 + Number(minute);
}

/** Whether two `HH:MM` spans share any time. Spans that only touch (10-11 and 11-12) do not. */
export function spansOverlap(
  a: { start: string; end: string },
  b: { start: string; end: string },
): boolean {
  return (
    timeToMinutes(a.start) < timeToMinutes(b.end) && timeToMinutes(b.start) < timeToMinutes(a.end)
  );
}
