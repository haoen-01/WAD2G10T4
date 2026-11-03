/**
 * Plain-language reading of the senior's daily steps for the Home overview: how today compares with
 * a usual day, and how the last fortnight went. Pure and free of Vue, so `lib/activity.test.ts` can
 * run it under Node's type stripping.
 *
 * Nothing here decides anything. The API's policy (`server/src/silverloop/policy.py`) makes every
 * decision; this only describes the numbers it returns, using the same line the policy uses for its
 * first, gentlest action: 20% below the person's usual day. A coordinator can change the later
 * review setting, but never this first rung.
 */

/** The first policy rung: a day more than this far below usual can prompt a gentle check-in. */
export const GENTLE_NUDGE_PERCENT = 20;

/** The fields of a daily metric this module reads (the API's `DailyMetric` has more). */
export interface StepDay {
  day: string;
  steps: number;
  active_minutes?: number;
  sleep_hours?: number | null;
}

/** Steps as a whole-number percentage of a usual day, or `null` when there is no usual day yet. */
export function percentOfUsual(steps: number, usual: number): number | null {
  if (!Number.isFinite(steps) || !Number.isFinite(usual) || usual <= 0) return null;
  return Math.round((steps / usual) * 100);
}

/** True when a day is no more than the gentle-nudge line below usual. */
export function isNearUsual(steps: number, usual: number): boolean {
  const percent = percentOfUsual(steps, usual);
  return percent !== null && percent >= 100 - GENTLE_NUDGE_PERCENT;
}

/** How a day compares with usual, in words a family member would use. */
export function compareWords(percent: number | null): string {
  if (percent === null) return 'not enough data to compare yet';
  if (percent >= 110) return 'more than a usual day';
  if (percent >= 90) return 'about the same as a usual day';
  if (percent >= 100 - GENTLE_NUDGE_PERCENT) return 'a little less than a usual day';
  return 'well below a usual day';
}

export interface FortnightSummary {
  /** Days with a reading. */
  total: number;
  /** Of those, days within the gentle-nudge line of usual. */
  near: number;
  lowest: StepDay | null;
  highest: StepDay | null;
}

/** Counts the days near usual and finds the lowest and highest, ignoring days with no reading. */
export function summariseDays(days: readonly StepDay[], usual: number): FortnightSummary {
  const readable = days.filter((day) => Number.isFinite(day.steps) && day.steps >= 0);
  let lowest: StepDay | null = null;
  let highest: StepDay | null = null;
  for (const day of readable) {
    if (!lowest || day.steps < lowest.steps) lowest = day;
    if (!highest || day.steps > highest.steps) highest = day;
  }
  return {
    total: readable.length,
    near: readable.filter((day) => isNearUsual(day.steps, usual)).length,
    lowest,
    highest,
  };
}

/**
 * One sentence for the chart: "12 of the last 14 days were within 20% of her usual day." `owner` is
 * whose usual day it is: "her" for the family, "your" on the senior's own screen.
 */
export function fortnightSentence(summary: FortnightSummary, owner = 'her'): string {
  if (summary.total === 0) return 'No daily readings yet.';
  const days = summary.total === 1 ? 'day' : 'days';
  if (summary.near === summary.total) {
    return `All of the last ${summary.total} ${days} were within ${GENTLE_NUDGE_PERCENT}% of ${owner} usual day.`;
  }
  return `${summary.near} of the last ${summary.total} ${days} were within ${GENTLE_NUDGE_PERCENT}% of ${owner} usual day.`;
}

/** A step count written for reading aloud and on screen: "5,720 steps". */
export function formatSteps(steps: number): string {
  const rounded = Math.round(steps);
  return `${rounded.toLocaleString('en-SG')} ${rounded === 1 ? 'step' : 'steps'}`;
}
