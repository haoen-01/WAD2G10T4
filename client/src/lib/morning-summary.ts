/**
 * The morning summary that greets a family member on Home once a day
 * (`components/home/MorningSummary.vue`): how the senior's latest day went against her usual day,
 * one line on whether all is well, and a short list of what matters today. Pure and free of Vue, so
 * `lib/morning-summary.test.ts` can run it under Node's type stripping.
 *
 * Nothing here decides anything. The verdict comes from what the API's policy already said
 * (`attention_band` and `last_decision`), and the steps wording is the same as the Home hero's.
 * No health words: Care+ describes activity, never illness.
 */
import { compareWords, percentOfUsual } from './activity';
import { addDays } from './calendar';
import { formatIsoDay } from './format-date';
import { timeRange } from './today';

/**
 * Kept in this browser: `off`, or the day it was last shown for each senior, as JSON
 * (`{"mdm-lim":"2026-11-04"}`), so switching between two seniors does not open it again.
 */
export const MORNING_KEY = 'careplus.morning.v1';
export const MORNING_OFF = 'off';

/** The day it was last shown for each senior. Anything unreadable counts as never shown. */
function shownDays(stored: string | null): Record<string, string> {
  if (!stored || stored === MORNING_OFF) return {};
  try {
    const parsed: unknown = JSON.parse(stored);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, string>)
      : {};
  } catch {
    return {};
  }
}

/** True when the summary should open by itself: not turned off, and not yet shown today. */
export function shouldShowSummary(stored: string | null, personId: string, today: string): boolean {
  if (stored === MORNING_OFF) return false;
  return shownDays(stored)[personId] !== today;
}

/** What to keep after showing it today for this senior (the other seniors' days are kept). */
export function shownToday(stored: string | null, personId: string, today: string): string {
  return JSON.stringify({ ...shownDays(stored), [personId]: today });
}

export type Verdict = 'good' | 'watch' | 'review' | 'paused' | 'unread';

export interface SummaryInput {
  elder: string;
  today: string;
  /** The latest reading's day and steps, and her usual day (the API's baseline). */
  readingDay: string;
  steps: number;
  usual: number;
  attentionBand: string;
  lastDecision: string;
  consentActive: boolean;
  /**
   * The API's `signal.quality.safe_to_interpret`: false when the watch was not worn long enough to
   * compare the day with a usual one. The policy then says nothing either way, so neither does this.
   */
  readable: boolean;
  appointmentsToday: readonly {
    title: string;
    start: string;
    end: string;
    needsSomeone: boolean;
  }[];
  tasksToday: readonly { title: string; time: string; completed: boolean }[];
  /** Visits in the next three days that still have no one going. */
  unhelpedSoon: readonly { title: string; date: string }[];
  /** The watch battery, when known. */
  battery: { percent: number; charging: boolean } | null;
}

export interface TodoItem {
  icon: 'calendar' | 'checklist' | 'hand' | 'battery';
  text: string;
  /** Where on Home or in the app it is dealt with. */
  to: string;
}

export interface MorningSummary {
  dayLabel: string;
  steps: number;
  percent: number | null;
  compare: string;
  verdict: Verdict;
  headline: string;
  note: string;
  todo: TodoItem[];
}

/** "Yesterday", "Today", or the reading's own day ("Tue, 18 Aug") for older sample readings. */
export function readingDayLabel(readingDay: string, today: string): string {
  if (readingDay === today) return 'Today so far';
  if (readingDay === addDays(today, -1)) return 'Yesterday';
  return formatIsoDay(readingDay);
}

/** The one-line verdict, from what the policy said (never from a guess here). */
export function verdictOf(
  attentionBand: string,
  lastDecision: string,
  consentActive: boolean,
): Verdict {
  if (!consentActive) return 'paused';
  if (attentionBand === 'review' || lastDecision === 'coordinator_review') return 'review';
  if (attentionBand === 'watch' || lastDecision === 'gentle_nudge') return 'watch';
  return 'good';
}

const LINES: Record<Verdict, (elder: string) => { headline: string; note: string }> = {
  good: (elder) => ({
    headline: 'All’s good.',
    note: `${elder}’s activity is within her usual range. Nothing needs doing.`,
  }),
  watch: (elder) => ({
    headline: 'Keep an eye on it.',
    note: `${elder} was less active than usual. A friendly call or visit could help; keep monitoring this week.`,
  }),
  review: (elder) => ({
    headline: 'Keep monitoring.',
    note: `${elder}’s activity has been lower for a while, so a person is reviewing her week. You don’t need to do anything yet.`,
  }),
  paused: (elder) => ({
    headline: 'Sharing is paused.',
    note: `${elder} has paused sharing her activity, so there is nothing new to show.`,
  }),
  unread: (elder) => ({
    headline: 'Not enough watch wear to compare.',
    note: `${elder}’s watch was not worn long enough to compare with a usual day. A reminder to wear it could help.`,
  }),
};

/** Builds the summary from what Home has already loaded. */
export function buildSummary(input: SummaryInput): MorningSummary {
  const policyVerdict = verdictOf(input.attentionBand, input.lastDecision, input.consentActive);
  // A pause in sharing comes first; otherwise a day that cannot be read is not compared at all.
  const verdict = policyVerdict !== 'paused' && !input.readable ? 'unread' : policyVerdict;
  const percent = verdict === 'unread' ? null : percentOfUsual(input.steps, input.usual);
  const { headline, note } = LINES[verdict](input.elder);

  const todo: TodoItem[] = [];
  for (const visit of input.appointmentsToday) {
    todo.push({
      icon: 'calendar',
      text: `${visit.title}, ${timeRange(visit.start, visit.end)}${visit.needsSomeone ? ' · no one going yet' : ''}`,
      to: '/calendar',
    });
  }
  const open = input.tasksToday.filter((task) => !task.completed);
  if (open.length > 0) {
    const next = [...open].sort((a, b) => a.time.localeCompare(b.time))[0];
    todo.push({
      icon: 'checklist',
      text: `${open.length} ${open.length === 1 ? 'task' : 'tasks'} to do today, starting with ${next.title} at ${timeRange(next.time, null)}`,
      to: '#home-tasks',
    });
  } else if (input.tasksToday.length > 0) {
    todo.push({ icon: 'checklist', text: 'Every task for today is done', to: '#home-tasks' });
  }
  const others = input.unhelpedSoon.filter(
    (visit) =>
      !input.appointmentsToday.some(
        (today) => today.title === visit.title && visit.date === input.today,
      ),
  );
  if (others.length > 0) {
    const first = others[0];
    todo.push({
      icon: 'hand',
      text:
        others.length === 1
          ? `${first.title} on ${formatIsoDay(first.date)} still needs someone to go along`
          : `${others.length} visits in the next 3 days still need someone to go along`,
      to: '#home-needs',
    });
  }
  if (input.battery && !input.battery.charging && input.battery.percent < 20) {
    todo.push({
      icon: 'battery',
      text: `Her watch is at ${input.battery.percent}%: remind ${input.elder} to charge it`,
      to: '/watch',
    });
  }

  return {
    dayLabel: readingDayLabel(input.readingDay, input.today),
    steps: input.steps,
    percent,
    compare: verdict === 'unread' ? 'not enough watch wear to compare' : compareWords(percent),
    verdict,
    headline,
    note,
    todo,
  };
}
