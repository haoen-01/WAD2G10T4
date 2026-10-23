/**
 * The product's one date vocabulary (PLAN §1.2): "Thu, 20 Aug", never ISO, never a
 * browser-locale numeric date. Pure and deterministic, so the server render and the client
 * hydration always print the same string whatever the machine's locale or time zone.
 *
 * - A calendar day (`YYYY-MM-DD`, a demo/simulated day) is read in UTC, so it never shifts a day.
 * - A moment (a full timestamp) is read in the product's own time zone, Singapore, where every AAC
 *   and persona is set.
 *
 * Names come from fixed English tables rather than `Intl` month names: ICU's en-GB short month for
 * September is "Sept", and its short weekday form drops the comma.
 */

export const PRODUCT_TIME_ZONE = 'Asia/Singapore';

export const WEEKDAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const;
export const WEEKDAYS_LONG = [
  'Sunday',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
] as const;
const MONTHS_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const;
const MONTHS_LONG = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const;

export type DayFormatOptions = {
  /** `short` "Thu, 20 Aug" (default) · `long` "Thursday, 20 August". */
  style?: 'short' | 'long';
  /** Leave the weekday out: "20 Aug". */
  weekday?: boolean;
};

type DayParts = { year: number; month: number; day: number; weekday: number };

function joinDay({ month, day, weekday }: DayParts, options: DayFormatOptions = {}): string {
  const long = options.style === 'long';
  const monthName = (long ? MONTHS_LONG : MONTHS_SHORT)[month - 1];
  const date = `${day} ${monthName}`;
  if (options.weekday === false) return date;
  return `${(long ? WEEKDAYS_LONG : WEEKDAYS_SHORT)[weekday]}, ${date}`;
}

/** The parts of a real `YYYY-MM-DD` calendar day (a leading day of a longer ISO string is fine),
 *  or `null` for anything else, including impossible dates such as `2026-02-30`. */
export function parseIsoDay(value: string | null | undefined): DayParts | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec((value ?? '').trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return { year, month, day, weekday: date.getUTCDay() };
}

/**
 * A calendar day, `YYYY-MM-DD`, as "Thu, 20 Aug". Returns `fallback` for a missing or unparseable
 * value (default: the value as given, so nothing is guessed at).
 */
export function formatIsoDay(
  value: string | null | undefined,
  options: DayFormatOptions & { fallback?: string } = {},
): string {
  const parts = parseIsoDay(value);
  if (!parts) return options.fallback ?? value ?? '';
  return joinDay(parts, options);
}

const MOMENT_PARTS = new Intl.DateTimeFormat('en-US', {
  timeZone: PRODUCT_TIME_ZONE,
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hourCycle: 'h23',
});

function momentParts(value: string | Date): (DayParts & { hour: number; minute: number }) | null {
  const moment = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(moment.getTime())) return null;
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    Number(MOMENT_PARTS.formatToParts(moment).find((part) => part.type === type)?.value);
  const year = get('year');
  const month = get('month');
  const day = get('day');
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return { year, month, day, weekday, hour: get('hour') % 24, minute: get('minute') };
}

/** A month as "September 2026". `month` is 1-12. */
export function formatMonthYear(year: number, month: number): string {
  return `${MONTHS_LONG[month - 1]} ${year}`;
}

/**
 * A 24-hour clock time, `HH:MM`, as "10:00 am" or "2:30 pm". Anything that is not a real clock time
 * comes back as given, so nothing is guessed at.
 */
export function formatClockTime(value: string | null | undefined): string {
  const match = /^(\d{2}):(\d{2})$/.exec((value ?? '').trim());
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return value ?? '';
  const hour = Number(match[1]);
  return `${hour % 12 === 0 ? 12 : hour % 12}:${match[2]} ${hour < 12 ? 'am' : 'pm'}`;
}

/** A timestamp's day in Singapore time, as "Thu, 20 Aug". */
export function formatMomentDay(
  value: string | Date | null | undefined,
  options: DayFormatOptions & { fallback?: string } = {},
): string {
  const parts = value ? momentParts(value) : null;
  return parts ? joinDay(parts, options) : (options.fallback ?? 'Not recorded');
}

/** A timestamp in Singapore time, as "Thu, 20 Aug, 4:17 pm". */
export function formatMomentTime(
  value: string | Date | null | undefined,
  options: DayFormatOptions & { fallback?: string } = {},
): string {
  const parts = value ? momentParts(value) : null;
  if (!parts) return options.fallback ?? 'Not recorded';
  const hour12 = parts.hour % 12 === 0 ? 12 : parts.hour % 12;
  const minute = String(parts.minute).padStart(2, '0');
  return `${joinDay(parts, options)}, ${hour12}:${minute} ${parts.hour < 12 ? 'am' : 'pm'}`;
}
