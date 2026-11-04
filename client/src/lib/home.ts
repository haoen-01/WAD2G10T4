/**
 * Small rules for the family Home screen: how many rows a list shows before "See all", the one
 * sample-data notice, and how the hero names the day a reading is from. Pure and free of Vue, so
 * `lib/home.test.ts` can run them under Node's type stripping.
 */
import { formatIsoDay } from './format-date';

/** Rows a Home list shows before "See all". */
export const HOME_LIST_CAP = 5;

/** The first `cap` rows, and how many more there are. */
export function capRows<T>(
  rows: readonly T[],
  cap = HOME_LIST_CAP,
): { shown: T[]; hidden: number } {
  const limit = Math.max(0, Math.floor(cap));
  return { shown: rows.slice(0, limit), hidden: Math.max(0, rows.length - limit) };
}

/**
 * The one "Sample data" notice for a screen, naming what is sample, or `null` when nothing is.
 * Synthetic steps and seeded family updates must always be labelled; one notice covers the screen.
 */
export function sampleNotice(
  elder: string,
  parts: { steps: boolean; feed: boolean },
): string | null {
  if (parts.steps && parts.feed) {
    return `${elder}’s steps and the older family updates are sample data, not real.`;
  }
  if (parts.steps) return `${elder}’s steps are sample data, not real.`;
  if (parts.feed) return 'The older family updates are sample data, not real.';
  return null;
}

/** The reading's own day ("Tue, 18 Aug") when it is not from today, or `null` when it is. */
export function readingPastDay(day: string, today: string): string | null {
  return day === today ? null : formatIsoDay(day);
}

/**
 * The small timestamp under the hero's sentence: "Steps so far today", or, for an older reading,
 * "Latest reading from Tue, 18 Aug", so a past day is never taken for today.
 */
export function readingStamp(day: string, today: string): string {
  return day === today ? 'Steps so far today' : `Latest reading from ${formatIsoDay(day)}`;
}

/**
 * The hero's headline in its natural phrases, one per line: a leading day ("Tue, 18 Aug"), the
 * middle, and a closing "for {elder}". The words are never changed; a headline with neither
 * comes back whole and wraps on its own.
 */
export function headlineLines(headline: string, elder: string): string[] {
  const lines: string[] = [];
  let rest = headline;
  const day = /^[A-Z][a-z]{2}, \d{1,2} [A-Z][a-z]{2} /.exec(rest);
  if (day) {
    lines.push(day[0].trim());
    rest = rest.slice(day[0].length);
  }
  const closing = elder ? ` for ${elder}` : '';
  if (closing && rest.endsWith(closing) && rest.length > closing.length) {
    lines.push(rest.slice(0, -closing.length), closing.trim());
  } else {
    lines.push(rest);
  }
  return lines;
}

/** "Monday, 2 November": today's date, said first in the hero. */
export function longToday(today: string): string {
  return formatIsoDay(today, { style: 'long' });
}
