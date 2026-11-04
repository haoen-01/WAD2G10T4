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

/** The small timestamp under the hero's sentence: "Steps so far today" or "Steps from Tue, 18 Aug". */
export function readingStamp(day: string, today: string): string {
  return day === today ? 'Steps so far today' : `Steps from ${formatIsoDay(day)}`;
}

/** "Monday, 2 November": today's date, said first in the hero. */
export function longToday(today: string): string {
  return formatIsoDay(today, { style: 'long' });
}

/**
 * Where the hero's orange cross sits inside her headline, so it reads like the reference's
 * "life's ✚ best": before "for {elder}" ("A usual day ✚ for Mdm Lim"), else straight after her
 * name when the headline starts with it, else nowhere. The words themselves are never changed.
 */
export function crossSplit(
  headline: string,
  elder: string,
): { before: string; after: string } | null {
  if (!elder) return null;
  const forElder = headline.lastIndexOf(` for ${elder}`);
  if (forElder > 0) {
    return { before: headline.slice(0, forElder), after: headline.slice(forElder + 1) };
  }
  if (headline.startsWith(`${elder} `)) {
    return { before: elder, after: headline.slice(elder.length + 1) };
  }
  return null;
}
