/**
 * Words for daily readings. Sample activity has its own simulated dates, which rarely match the real
 * date on the calendar and the family feed beside it. So a chart says how long before the latest
 * reading a day was ("3 days ago"), and the figures say "today" only when the reading really is from
 * today; otherwise they name the reading's own day. Pure and free of Vue, so
 * `lib/reading-days.test.ts` can run it under Node's type stripping.
 */
import { formatIsoDay, parseIsoDay } from './format-date';

/** Sample activity, as the API marks it on a reading or on its data-quality check. */
export function isSampleSource(source: string | null | undefined): boolean {
  return source === 'synthetic';
}

/** The newest of the given days, or `null` when there are none. */
export function latestDay(days: readonly { day: string }[]): string | null {
  let latest: string | null = null;
  for (const { day } of days) if (latest === null || day > latest) latest = day;
  return latest;
}

/** Whole days from `day` to `latest`, or `null` when either is not a real calendar day. */
export function daysBefore(day: string, latest: string): number | null {
  const from = parseIsoDay(day);
  const to = parseIsoDay(latest);
  if (!from || !to) return null;
  const toMs = Date.UTC(to.year, to.month - 1, to.day);
  return Math.round((toMs - Date.UTC(from.year, from.month - 1, from.day)) / 86_400_000);
}

/** One bar's name: "Latest reading", "1 day ago", "13 days ago". */
export function readingDayLabel(day: string, latest: string): string {
  const gap = daysBefore(day, latest);
  if (gap === null || gap <= 0) return 'Latest reading';
  return `${gap} ${gap === 1 ? 'day' : 'days'} ago`;
}

/**
 * The left end of a chart's axis, where the oldest bar is, in that bar's own words ("13 days ago");
 * `null` for a single reading.
 */
export function oldestReadingLabel(days: readonly { day: string }[]): string | null {
  const latest = latestDay(days);
  if (latest === null) return null;
  let span = 0;
  for (const { day } of days) span = Math.max(span, daysBefore(day, latest) ?? 0);
  if (span === 0) return null;
  return `${span} ${span === 1 ? 'day' : 'days'} ago`;
}

/** A bar's name on the senior's own chart: the same count, with no "reading" in it. */
export function seniorDayLabel(day: string, latest: string): string {
  const label = readingDayLabel(day, latest);
  return label === 'Latest reading' ? 'Latest day' : label;
}

/** The senior's line under their steps: "These steps are from today." or "... from Tue, 18 Aug." */
export function seniorReadingLine(day: string, today: string): string {
  return `These steps are from ${day === today ? 'today' : formatIsoDay(day)}.`;
}

/** Under the senior's chart, what "days ago" counts from; `null` when that is today. */
export function seniorCountedBackLine(latest: string | null, today: string): string | null {
  if (latest === null || latest === today) return null;
  // Non-breaking spaces, so the date never splits across two lines.
  return `“Days ago” means days before ${formatIsoDay(latest).replaceAll(' ', '\u00a0')}.`;
}

export interface HomeReadingWords {
  heading: string;
  /** The label beside the step count. */
  stepsLabel: string;
  /** The sentence around the step count: "{ledeStart} 5,720 steps {ledeWhen}, ...". */
  ledeStart: string;
  ledeWhen: string;
}

/**
 * Home's words for the latest reading. "Today" only when the reading is from today. The lede names
 * the senior ("Mr Tan walked …"): Care+ does not record gender, so it never says "she" or "he".
 */
export function homeReadingWords(day: string, today: string, elder: string): HomeReadingWords {
  if (day === today) {
    return {
      heading: `Today with ${elder}`,
      stepsLabel: 'Today so far',
      ledeStart: `${elder} has walked`,
      ledeWhen: 'so far',
    };
  }
  const named = formatIsoDay(day);
  return {
    heading: `${elder} on ${named}`,
    stepsLabel: `Steps on ${named}`,
    ledeStart: `${elder} walked`,
    ledeWhen: `on ${named}`,
  };
}

/** What "days ago" counts from, when that is not today; `null` when it is, or with no readings. */
export function countedBackNote(latest: string | null, today: string): string | null {
  if (latest === null || latest === today) return null;
  return `Days are counted back from the latest reading, ${formatIsoDay(latest)}.`;
}
