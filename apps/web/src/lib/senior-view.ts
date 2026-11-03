/**
 * The senior screen's small rules: which tab is open, the steps ring and its words, the last seven
 * days, and the order of today's tasks. Pure and free of Vue, so `lib/senior-view.test.ts` can run
 * it under Node's type stripping.
 */
import { compareWords, percentOfUsual } from './activity';
import { addDays } from './calendar';

export const TABS = ['today', 'calendar', 'badges', 'family'] as const;
export type SeniorTab = (typeof TABS)[number];
export const TAB_KEY = 'careplus.seniorTab.v1';

/** The tab saved last time, or Today. Storage may be blocked (some private windows). */
export function readTab(storage: Pick<Storage, 'getItem'>): SeniorTab {
  try {
    const value = storage.getItem(TAB_KEY);
    return TABS.find((tab) => tab === value) ?? 'today';
  } catch {
    return 'today';
  }
}

export function saveTab(storage: Pick<Storage, 'setItem'>, tab: SeniorTab): void {
  try {
    storage.setItem(TAB_KEY, tab);
  } catch {
    /* Works for this visit. */
  }
}

/** The tab a key moves to (arrow keys wrap round; Home and End jump), or null for any other key. */
export function adjacentTab(tab: SeniorTab, key: string): SeniorTab | null {
  const index = TABS.indexOf(tab);
  if (key === 'Home') return 'today';
  if (key === 'End') return 'family';
  if (key === 'ArrowRight') return TABS[(index + 1) % TABS.length];
  if (key === 'ArrowLeft') return TABS[(index + TABS.length - 1) % TABS.length];
  return null;
}

/** Today's steps against a usual day. The ring's fill stops at 100%; the percentage does not. */
export function stepProgress(
  steps: number,
  usual: number,
): { percent: number | null; fill: number } {
  const percent = percentOfUsual(steps, usual);
  return { percent, fill: percent === null ? 0 : Math.min(100, Math.max(0, percent)) };
}

export function stepWords(steps: number, usual: number): string {
  const words = compareWords(percentOfUsual(steps, usual));
  if (words === 'more than a usual day') return 'More than usual';
  if (words === 'about the same as a usual day') return 'About the same as usual';
  if (words === 'not enough data to compare yet') return 'Not enough data to compare yet';
  return 'A bit less than usual';
}

/**
 * The senior's one sentence about their steps, compared only with their own usual day, and the
 * friendly icon beside it. Never a judgement about health; "a little less" at most.
 */
export function seniorActivity(
  steps: number,
  usual: number,
  readable = true,
): { sentence: string; icon: 'thumbs-up' | 'walk' | 'watch' } {
  if (!readable) {
    return { sentence: 'Your watch was not worn long enough to count your steps.', icon: 'watch' };
  }
  const percent = percentOfUsual(steps, usual);
  if (percent === null) {
    return { sentence: 'Not enough steps yet to compare with your usual day.', icon: 'walk' };
  }
  if (percent >= 110) return { sentence: 'You walked more than usual.', icon: 'thumbs-up' };
  if (percent >= 90) return { sentence: 'You walked about as much as usual.', icon: 'thumbs-up' };
  return { sentence: 'You walked a little less than usual.', icon: 'walk' };
}

/** The seven days up to `latest`, oldest first, each with its reading or null. */
export function sevenDays<T extends { day: string }>(
  readings: readonly T[],
  latest: string,
): { day: string; reading: T | null }[] {
  return Array.from({ length: 7 }, (_, index) => {
    const day = addDays(latest, index - 6);
    return { day, reading: readings.find((item) => item.day === day) ?? null };
  });
}

interface SeniorTask {
  task_id: string;
  time: string;
  completed: boolean;
}

/** Earliest first; tasks at the same time keep a fixed order. */
export function sortSeniorTasks<T extends SeniorTask>(tasks: readonly T[]): T[] {
  return [...tasks].sort(
    (a, b) => a.time.localeCompare(b.time) || a.task_id.localeCompare(b.task_id),
  );
}

/** The first task not done that is still to come at `clock` (`HH:MM`), or null. */
export function nextSeniorTask(tasks: readonly SeniorTask[], clock: string): string | null {
  return (
    sortSeniorTasks(tasks).find((task) => !task.completed && task.time >= clock)?.task_id ?? null
  );
}

/** Where the senior screen remembers the last day it cheered "all done", so it cheers once a day. */
export const CHEERED_KEY = 'careplus.seniorAllDone.v1';

export interface TaskCount {
  done: number;
  total: number;
}

/** True only when this tick finished the day: some were left before, and now every one is done. */
export function finishedTheDay(before: TaskCount, after: TaskCount): boolean {
  return after.total > 0 && after.done === after.total && before.done < before.total;
}

/**
 * Whether to throw the small "all done" confetti: the day was just finished, it has not been
 * cheered yet today, and the senior has not asked their device for less motion. (The words "All
 * done for today" still show with reduced motion; only the confetti is skipped.)
 */
export function shouldCheer(input: {
  finished: boolean;
  today: string;
  lastCheered: string | null;
  reducedMotion: boolean;
}): boolean {
  return input.finished && !input.reducedMotion && input.lastCheered !== input.today;
}

/** The last day cheered, or null when storage is unavailable or empty. */
export function readCheered(storage: Pick<Storage, 'getItem'>): string | null {
  try {
    return storage.getItem(CHEERED_KEY);
  } catch {
    return null;
  }
}

export function saveCheered(storage: Pick<Storage, 'setItem'>, day: string): void {
  try {
    storage.setItem(CHEERED_KEY, day);
  } catch {
    // Private mode or full storage: at worst it cheers again on the same day.
  }
}
