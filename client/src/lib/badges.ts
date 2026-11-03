/**
 * Walking badges: small rewards for walking, worked out from the daily step readings the API
 * already returns (`GET /v1/people/{id}/metrics`) and from walks finished on the Walk page. Pure and
 * free of Vue, so `lib/badges.test.ts` can run it under Node's type stripping.
 *
 * Encouragement only. A badge never feeds a decision: `policy.py` does not see badges, and nothing
 * here is sent anywhere. Missing a goal costs nothing: there are no streaks to break, an unfinished
 * past challenge is simply not shown, and a goal not yet reached says how close it is.
 */
import { addDays, monthOf, toIsoDay } from './calendar';
import {
  formatIsoDay,
  formatMomentDay,
  formatMomentTime,
  formatMonthYear,
  parseIsoDay,
  PRODUCT_TIME_ZONE,
} from './format-date';
import { STRIDE_M } from './walk';

/** One day's steps (the API's `DailyMetric` has more fields; only these are read). */
export interface StepDay {
  day: string;
  steps: number;
}

/** A walk finished on the Walk page while she shared it: when it ended, and how far it went. */
export interface FinishedWalk {
  at: number;
  distanceM: number;
}

export type BadgeShape = 'circle' | 'hexagon' | 'shield' | 'rosette' | 'star' | 'pennant';
export type BadgeMotif =
  | 'footprints'
  | 'numeral'
  | 'week'
  | 'weekend'
  | 'month'
  | 'marathon'
  | 'laurel'
  | 'peak'
  | 'park'
  | 'paths'
  | 'challenge';
export type BadgeTone =
  | 'teal'
  | 'jade'
  | 'orange'
  | 'coral'
  | 'violet'
  | 'sky'
  | 'sun'
  | 'ocean'
  | 'ruby'
  | 'plum'
  | 'emerald'
  | 'forest'
  | 'rose'
  | 'indigo';
export type BadgeGroup = 'day' | 'habit' | 'milestone' | 'walk' | 'challenge';

/** How a badge looks: its outline, colours, picture, and the big text on it (if any). */
export interface BadgeLook {
  shape: BadgeShape;
  tone: BadgeTone;
  motif: BadgeMotif;
  label?: string;
  sub?: string;
}

export interface BadgeResult {
  id: string;
  name: string;
  group: BadgeGroup;
  /** How to earn it, in plain words. */
  how: string;
  /** What she did, to finish "You earned this for …": "walking 5,000 steps in one day". */
  deed?: string;
  earned: boolean;
  /** The day it was earned, for badges read from daily steps (`YYYY-MM-DD`). */
  earnedDay: string | null;
  /** The moment it was earned, for badges from a finished walk (ms since 1970). */
  earnedAt: number | null;
  /** How close she is: `value` of `target`, and the same in words. */
  progress: { value: number; target: number; words: string };
  look: BadgeLook;
}

/** A day with at least this many steps counts as a walking day. */
export const WALKING_DAY_STEPS = 2000;
/** About a marathon (42.2 km) at the average stride the Walk page uses. */
export const MARATHON_STEPS = Math.round(42_195 / STRIDE_M / 1000) * 1000;
/** A finished walk at least this long earns "Park Loop". */
export const LOOP_M = 2000;
/** "Regular Walker": this many finished walks of at least `SHORT_WALK_M`. */
export const REGULAR_WALKS = 3;
export const SHORT_WALK_M = 1000;
/** A personal best counts once there are this many earlier days to beat. */
export const BEST_AFTER_DAYS = 14;
/** The monthly challenge: about this many usual days' steps in the month. */
export const CHALLENGE_USUAL_DAYS = 20;
export const CHALLENGE_DEFAULT_STEPS = 100_000;

const count = (value: number) => Math.round(value).toLocaleString('en-SG');

// ---- Small date helpers (calendar days as `YYYY-MM-DD`, read as UTC so time zones never shift) ----

function weekday(iso: string): number {
  return parseIsoDay(iso)?.weekday ?? -1;
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Readable days only, one per day, oldest first. */
export function cleanDays(days: readonly StepDay[]): StepDay[] {
  const byDay = new Map<string, StepDay>();
  for (const day of days) {
    if (!parseIsoDay(day.day) || !Number.isFinite(day.steps) || day.steps < 0) continue;
    byDay.set(day.day.slice(0, 10), { day: day.day.slice(0, 10), steps: day.steps });
  }
  return [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day));
}

/** The middle of the readings, or null with fewer than 7 to go on. */
export function usualSteps(days: readonly StepDay[]): number | null {
  const steps = days.map((day) => day.steps).sort((a, b) => a - b);
  if (steps.length < 7) return null;
  const middle = Math.floor(steps.length / 2);
  return steps.length % 2 ? steps[middle] : (steps[middle - 1] + steps[middle]) / 2;
}

// ---- The rules ----

function result(
  base: Pick<BadgeResult, 'id' | 'name' | 'group' | 'how' | 'deed' | 'look'>,
  earned: { day?: string | null; at?: number | null },
  progress: BadgeResult['progress'],
): BadgeResult {
  const earnedDay = earned.day ?? null;
  const earnedAt = earned.at ?? null;
  return {
    ...base,
    earned: earnedDay !== null || earnedAt !== null,
    earnedDay,
    earnedAt,
    progress,
  };
}

function dayGoal(
  days: StepDay[],
  id: string,
  name: string,
  target: number,
  look: BadgeLook,
): BadgeResult {
  const hit = days.find((day) => day.steps >= target);
  const best = days.reduce((top, day) => Math.max(top, day.steps), 0);
  return result(
    {
      id,
      name,
      group: 'day',
      how: `Walk ${count(target)} steps in one day.`,
      deed: `walking ${count(target)} steps in one day`,
      look,
    },
    { day: hit?.day },
    {
      value: Math.min(best, target),
      target,
      words: hit
        ? `${count(hit.steps)} steps that day.`
        : `Best day so far: ${count(best)} of ${count(target)} steps.`,
    },
  );
}

/** The first day on which `need` walking days fall within the `span` days ending that day. */
function windowGoal(
  days: StepDay[],
  span: number,
  need: number,
): { day: string | null; best: number } {
  const walking = days.filter((day) => day.steps >= WALKING_DAY_STEPS).map((day) => day.day);
  let best = 0;
  for (let i = 0; i < walking.length; i += 1) {
    const end = walking[i];
    const start = addDays(end, -(span - 1));
    const inside = walking.slice(0, i + 1).filter((day) => day >= start).length;
    best = Math.max(best, inside);
    if (inside >= need) return { day: end, best: need };
  }
  return { day: null, best };
}

function habitGoal(
  days: StepDay[],
  id: string,
  name: string,
  span: number,
  need: number,
  how: string,
  look: BadgeLook,
): BadgeResult {
  const { day, best } = windowGoal(days, span, need);
  return result(
    {
      id,
      name,
      group: 'habit',
      how,
      deed: `having ${need} walking days in ${span === 7 ? 'a week' : span === 30 ? 'a month' : `${span} days`}`,
      look,
    },
    { day },
    {
      value: best,
      target: need,
      words: day ? `${need} walking days.` : `Best so far: ${best} of ${need} walking days.`,
    },
  );
}

function weekendGoal(days: StepDay[], look: BadgeLook): BadgeResult {
  const walking = new Set(
    days.filter((day) => day.steps >= WALKING_DAY_STEPS).map((day) => day.day),
  );
  let earned: string | null = null;
  let best = 0;
  for (const day of days) {
    if (weekday(day.day) !== 0) continue; // Sundays
    const both = [addDays(day.day, -1), day.day].filter((d) => walking.has(d)).length;
    best = Math.max(best, both);
    if (both === 2) {
      earned = day.day;
      break;
    }
  }
  // A Saturday that is the latest reading counts as half a weekend so far.
  const last = days[days.length - 1];
  if (!earned && last && weekday(last.day) === 6 && walking.has(last.day)) best = Math.max(best, 1);
  return result(
    {
      id: 'weekend-walker',
      name: 'Weekend Walker',
      group: 'habit',
      how: `Walk at least ${count(WALKING_DAY_STEPS)} steps on a Saturday and the Sunday after.`,
      deed: 'walking on a Saturday and the Sunday after',
      look,
    },
    { day: earned },
    {
      value: earned ? 2 : best,
      target: 2,
      words: earned ? 'Saturday and Sunday.' : `Best weekend so far: ${best} of 2 days.`,
    },
  );
}

/** Milestones count the steps of this many days, ending on the day they are passed. */
export const MILESTONE_DAYS = 90;

function totalGoal(
  days: StepDay[],
  id: string,
  name: string,
  target: number,
  how: string,
  look: BadgeLook,
): BadgeResult {
  // A running total over the last `MILESTONE_DAYS` days (by date, so gaps are allowed).
  let total = 0;
  let from = 0;
  let earned: string | null = null;
  for (const day of days) {
    total += day.steps;
    const start = addDays(day.day, -(MILESTONE_DAYS - 1));
    while (days[from].day < start) {
      total -= days[from].steps;
      from += 1;
    }
    if (total >= target) {
      earned = day.day;
      break;
    }
  }
  return result(
    {
      id,
      name,
      group: 'milestone',
      how,
      deed: `walking ${count(target)} steps within ${MILESTONE_DAYS} days`,
      look,
    },
    { day: earned },
    {
      value: Math.min(total, target),
      target,
      words: earned
        ? `${count(target)} steps within ${MILESTONE_DAYS} days.`
        : `${count(total)} of ${count(target)} steps in the last ${MILESTONE_DAYS} days.`,
    },
  );
}

function personalBest(days: StepDay[]): BadgeResult {
  let top = 0;
  let earned: StepDay | null = null;
  for (let i = 0; i < days.length; i += 1) {
    if (i >= BEST_AFTER_DAYS && days[i].steps > top) {
      earned = days[i];
      break;
    }
    top = Math.max(top, days[i].steps);
  }
  const ready = days.length >= BEST_AFTER_DAYS;
  return result(
    {
      id: 'personal-best',
      name: 'Personal Best',
      group: 'milestone',
      how: `Beat your best day, once you have ${BEST_AFTER_DAYS} days of walking to beat.`,
      deed: 'walking more than on any day before',
      look: { shape: 'shield', tone: 'ruby', motif: 'peak' },
    },
    { day: earned?.day },
    earned
      ? {
          value: 1,
          target: 1,
          words: `${count(earned.steps)} steps, beating ${count(top)}.`,
        }
      : ready
        ? { value: 0, target: 1, words: `Your best day so far: ${count(top)} steps. Beat it!` }
        : {
            value: days.length,
            target: BEST_AFTER_DAYS,
            words: `${days.length} of ${BEST_AFTER_DAYS} days of walking so far.`,
          },
  );
}

function walkGoals(walks: readonly FinishedWalk[]): BadgeResult[] {
  const sorted = walks
    .filter((walk) => Number.isFinite(walk.at) && Number.isFinite(walk.distanceM))
    .sort((a, b) => a.at - b.at);
  const loop = sorted.find((walk) => walk.distanceM >= LOOP_M);
  const longest = sorted.reduce((top, walk) => Math.max(top, walk.distanceM), 0);
  const short = sorted.filter((walk) => walk.distanceM >= SHORT_WALK_M);
  const km = (m: number) => `${(m / 1000).toFixed(1)} km`;
  return [
    result(
      {
        id: 'park-loop',
        name: 'Park Loop',
        group: 'walk',
        how: `Finish a walk of ${km(LOOP_M)} or more on the Walk page.`,
        deed: `finishing a walk of ${km(LOOP_M)} or more`,
        look: { shape: 'shield', tone: 'forest', motif: 'park' },
      },
      { at: loop?.at },
      {
        value: Math.min(longest, LOOP_M),
        target: LOOP_M,
        words: loop
          ? `${km(loop.distanceM)} walked.`
          : `Longest walk so far: ${km(longest)} of ${km(LOOP_M)}.`,
      },
    ),
    result(
      {
        id: 'regular-walker',
        name: 'Regular Walker',
        group: 'walk',
        how: `Finish ${REGULAR_WALKS} walks of ${km(SHORT_WALK_M)} or more on the Walk page.`,
        deed: `finishing ${REGULAR_WALKS} walks of ${km(SHORT_WALK_M)} or more`,
        look: { shape: 'pennant', tone: 'indigo', motif: 'paths' },
      },
      { at: short[REGULAR_WALKS - 1]?.at },
      {
        value: Math.min(short.length, REGULAR_WALKS),
        target: REGULAR_WALKS,
        words:
          short.length >= REGULAR_WALKS
            ? `${REGULAR_WALKS} walks finished.`
            : `${short.length} of ${REGULAR_WALKS} walks finished.`,
      },
    ),
  ];
}

const CHALLENGE_TONES: BadgeTone[] = [
  'sky',
  'rose',
  'emerald',
  'sun',
  'coral',
  'teal',
  'ruby',
  'orange',
  'indigo',
  'plum',
  'ocean',
  'jade',
];

/** The month's goal: about 20 usual days, from the readings before the month began. */
export function challengeTarget(days: readonly StepDay[], monthStart: string): number {
  const before = days.filter((day) => day.day < monthStart && day.day >= addDays(monthStart, -28));
  const usual = usualSteps(before);
  if (usual === null) return CHALLENGE_DEFAULT_STEPS;
  return Math.max(20_000, Math.round((usual * CHALLENGE_USUAL_DAYS) / 5000) * 5000);
}

/**
 * One challenge per month: past months only when won (a missed one is never shown), and the
 * latest month always, won or in progress.
 */
function challenges(days: StepDay[]): BadgeResult[] {
  const last = days[days.length - 1];
  if (!last) return [];
  const months = [...new Set(days.map((day) => day.day.slice(0, 7)))];
  const out: BadgeResult[] = [];
  for (const key of months) {
    const { year, month } = monthOf(`${key}-01`);
    const start = toIsoDay(year, month, 1);
    const target = challengeTarget(days, start);
    const inMonth = days.filter((day) => day.day.startsWith(key));
    let total = 0;
    let won: string | null = null;
    for (const day of inMonth) {
      total += day.steps;
      if (total >= target) {
        won = day.day;
        break;
      }
    }
    if (!won) total = inMonth.reduce((sum, day) => sum + day.steps, 0);
    const current = key === last.day.slice(0, 7);
    if (!won && !current) continue;
    const monthName = formatMonthYear(year, month).split(' ')[0];
    const left = daysInMonth(year, month) - Number(last.day.slice(8, 10));
    out.push(
      result(
        {
          id: `challenge-${key}`,
          name: `${monthName} Challenge`,
          group: 'challenge',
          how: `Walk ${count(target)} steps in ${monthName} ${year}.`,
          deed: `walking ${count(target)} steps in ${monthName} ${year}`,
          look: {
            shape: 'circle',
            tone: CHALLENGE_TONES[month - 1],
            motif: 'challenge',
            label: monthName.slice(0, 3).toUpperCase(),
            sub: String(year),
          },
        },
        { day: won },
        {
          value: Math.min(total, target),
          target,
          words: won
            ? `${count(target)} steps in ${monthName}.`
            : `${count(total)} of ${count(target)} steps · ${
                left === 0 ? 'the month’s last day' : `${left} ${left === 1 ? 'day' : 'days'} left`
              }.`,
        },
      ),
    );
  }
  return out;
}

/** Every badge, earned or not, in the order they are shown. */
export function evaluateBadges(
  readings: readonly StepDay[],
  walks: readonly FinishedWalk[] = [],
): BadgeResult[] {
  const days = cleanDays(readings);
  return [
    ...challenges(days).reverse(),
    dayGoal(days, 'first-steps', 'First Steps', 1000, {
      shape: 'circle',
      tone: 'teal',
      motif: 'footprints',
    }),
    dayGoal(days, 'steps-3k', '3,000 Step Day', 3000, {
      shape: 'hexagon',
      tone: 'jade',
      motif: 'numeral',
      label: '3K',
    }),
    dayGoal(days, 'steps-5k', '5,000 Step Day', 5000, {
      shape: 'hexagon',
      tone: 'orange',
      motif: 'numeral',
      label: '5K',
    }),
    dayGoal(days, 'steps-8k', '8,000 Step Day', 8000, {
      shape: 'hexagon',
      tone: 'coral',
      motif: 'numeral',
      label: '8K',
    }),
    dayGoal(days, 'steps-10k', '10,000 Step Day', 10_000, {
      shape: 'hexagon',
      tone: 'violet',
      motif: 'numeral',
      label: '10K',
    }),
    habitGoal(
      days,
      'steady-week',
      'Steady Week',
      7,
      5,
      `Have 5 walking days (${count(WALKING_DAY_STEPS)}+ steps) in any 7 days.`,
      { shape: 'shield', tone: 'sky', motif: 'week' },
    ),
    weekendGoal(days, { shape: 'pennant', tone: 'sun', motif: 'weekend' }),
    habitGoal(
      days,
      'month-of-walks',
      'Month of Walks',
      30,
      20,
      `Have 20 walking days (${count(WALKING_DAY_STEPS)}+ steps) in any 30 days.`,
      { shape: 'circle', tone: 'ocean', motif: 'month' },
    ),
    totalGoal(
      days,
      'marathon',
      'Marathon, Step by Step',
      MARATHON_STEPS,
      `Walk ${count(MARATHON_STEPS)} steps within ${MILESTONE_DAYS} days: about the 42 km of a marathon.`,
      { shape: 'star', tone: 'ruby', motif: 'marathon', label: '42', sub: 'KM' },
    ),
    totalGoal(
      days,
      'steps-100k',
      '100,000 Steps',
      100_000,
      `Walk 100,000 steps within ${MILESTONE_DAYS} days.`,
      {
        shape: 'rosette',
        tone: 'plum',
        motif: 'laurel',
        label: '100K',
      },
    ),
    totalGoal(
      days,
      'steps-250k',
      'Quarter Million',
      250_000,
      `Walk 250,000 steps within ${MILESTONE_DAYS} days.`,
      {
        shape: 'rosette',
        tone: 'emerald',
        motif: 'laurel',
        label: '250K',
      },
    ),
    personalBest(days),
    ...walkGoals(walks),
  ];
}

// ---- Claiming, kept in this browser ----

export type BadgeState = 'locked' | 'ready' | 'claimed';

/** Locked until earned; earned but not yet claimed is "ready"; then claimed. */
export function badgeState(badge: BadgeResult, claimedAt: number | undefined): BadgeState {
  if (!badge.earned) return 'locked';
  return claimedAt === undefined ? 'ready' : 'claimed';
}

export const BADGES_KEY = 'careplus.badges.v1';
/** Finished walks kept for the walk badges; older ones are dropped. */
export const KEEP_WALKS = 50;

export interface BadgeStore {
  /** Per senior (person id): badge id → when it was claimed (ms since 1970). */
  claims: Record<string, Record<string, number>>;
  /**
   * Per senior: every badge as it was when first earned. The rules only see the last 90 days, so a
   * badge earned from days that have since rolled out of view is kept from here: once earned,
   * always earned.
   */
  earned: Record<string, Record<string, BadgeResult>>;
  /** Per senior: walks finished on the Walk page while she shared them. */
  walks: Record<string, FinishedWalk[]>;
  /**
   * Per senior: which badges have been seen up close since they were claimed, by whom (`self` or
   * `family`, see `seenKey`), and when. The first look is the one that is celebrated.
   */
  seen: Record<string, Record<string, number>>;
}

export type Audience = 'self' | 'family';

/** The key for "this badge, seen by her" or "seen by her family". */
export const seenKey = (id: string, audience: Audience) => `${audience}:${id}`;

/** Celebrate this look? Only a claimed badge, only the first time this audience sees it. */
export function isFirstLook(
  claimed: boolean,
  seen: Record<string, number> | undefined,
  id: string,
  audience: Audience,
): boolean {
  return claimed && seen?.[seenKey(id, audience)] === undefined;
}

const SHAPE_NAMES: readonly BadgeShape[] = [
  'circle',
  'hexagon',
  'shield',
  'rosette',
  'star',
  'pennant',
];
const MOTIF_NAMES: readonly BadgeMotif[] = [
  'footprints',
  'numeral',
  'week',
  'weekend',
  'month',
  'marathon',
  'laurel',
  'peak',
  'park',
  'paths',
  'challenge',
];
const TONE_NAMES: readonly BadgeTone[] = [
  'teal',
  'jade',
  'orange',
  'coral',
  'violet',
  'sky',
  'sun',
  'ocean',
  'ruby',
  'plum',
  'emerald',
  'forest',
  'rose',
  'indigo',
];
const GROUP_NAMES: readonly BadgeGroup[] = ['day', 'habit', 'milestone', 'walk', 'challenge'];

const isOneOf = <T extends string>(list: readonly T[], value: unknown): value is T =>
  typeof value === 'string' && (list as readonly string[]).includes(value);

/** A remembered badge, if it is whole and drawable; anything else is dropped. */
function readEarned(value: unknown): BadgeResult | null {
  if (!isRecord(value) || !isRecord(value.look) || !isRecord(value.progress)) return null;
  const { look, progress } = value;
  const day =
    typeof value.earnedDay === 'string' && parseIsoDay(value.earnedDay) ? value.earnedDay : null;
  const at =
    typeof value.earnedAt === 'number' && Number.isFinite(value.earnedAt) ? value.earnedAt : null;
  if (
    typeof value.id !== 'string' ||
    typeof value.name !== 'string' ||
    typeof value.how !== 'string' ||
    !isOneOf(GROUP_NAMES, value.group) ||
    !isOneOf(SHAPE_NAMES, look.shape) ||
    !isOneOf(TONE_NAMES, look.tone) ||
    !isOneOf(MOTIF_NAMES, look.motif) ||
    (day === null && at === null) ||
    typeof progress.words !== 'string' ||
    typeof progress.target !== 'number' ||
    !(progress.target > 0)
  ) {
    return null;
  }
  return {
    id: value.id,
    name: value.name,
    group: value.group,
    how: value.how,
    ...(typeof value.deed === 'string' ? { deed: value.deed } : {}),
    earned: true,
    earnedDay: day,
    earnedAt: at,
    progress: { value: progress.target, target: progress.target, words: progress.words },
    look: {
      shape: look.shape,
      tone: look.tone,
      motif: look.motif,
      ...(typeof look.label === 'string' ? { label: look.label } : {}),
      ...(typeof look.sub === 'string' ? { sub: look.sub } : {}),
    },
  };
}

/**
 * The shelf as shown: today's results, with every badge ever earned kept earned (on the day it was
 * first earned), and remembered challenges from months no longer in view put back in.
 */
export function withRemembered(
  results: readonly BadgeResult[],
  remembered: Record<string, BadgeResult> = {},
): BadgeResult[] {
  const ids = new Set(results.map((badge) => badge.id));
  const merged = results.map((badge) => remembered[badge.id] ?? badge);
  const old = Object.values(remembered)
    .filter((badge) => !ids.has(badge.id))
    .sort((a, b) => b.id.localeCompare(a.id));
  const challenges = [
    ...merged.filter((badge) => badge.group === 'challenge'),
    ...old.filter((badge) => badge.group === 'challenge'),
  ];
  return [
    ...challenges,
    ...merged.filter((badge) => badge.group !== 'challenge'),
    ...old.filter((badge) => badge.group !== 'challenge'),
  ];
}

/** Badges earned now that are not remembered yet. */
export function newlyEarned(
  results: readonly BadgeResult[],
  remembered: Record<string, BadgeResult> = {},
): BadgeResult[] {
  return results.filter((badge) => badge.earned && !remembered[badge.id]);
}

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

function readWalks(list: unknown[]): FinishedWalk[] {
  return list
    .filter(
      (walk): walk is FinishedWalk =>
        isRecord(walk) &&
        typeof walk.at === 'number' &&
        Number.isFinite(walk.at) &&
        typeof walk.distanceM === 'number' &&
        Number.isFinite(walk.distanceM),
    )
    .map((walk) => ({ at: walk.at, distanceM: walk.distanceM }))
    .slice(-KEEP_WALKS);
}

/** Per senior: key → a moment (ms since 1970). Anything that is not a real moment is dropped. */
function readTimes(value: unknown): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  if (!isRecord(value)) return out;
  for (const [person, list] of Object.entries(value)) {
    if (!isRecord(list)) continue;
    const kept: Record<string, number> = {};
    for (const [key, at] of Object.entries(list)) {
      if (typeof at === 'number' && Number.isFinite(at)) kept[key] = at;
    }
    out[person] = kept;
  }
  return out;
}

/** Reads what this browser remembers; anything unreadable is dropped, never guessed at. */
export function readBadgeStore(storage: StorageLike): BadgeStore {
  const empty: BadgeStore = { claims: {}, earned: {}, walks: {}, seen: {} };
  try {
    const saved: unknown = JSON.parse(storage.getItem(BADGES_KEY) ?? '{}');
    if (!isRecord(saved)) return empty;
    const claims = readTimes(saved.claims);
    const seen = readTimes(saved.seen);
    const earned: BadgeStore['earned'] = {};
    if (isRecord(saved.earned)) {
      for (const [person, list] of Object.entries(saved.earned)) {
        if (!isRecord(list)) continue;
        const kept: Record<string, BadgeResult> = {};
        for (const [id, value] of Object.entries(list)) {
          const badge = readEarned(value);
          if (badge && badge.id === id) kept[id] = badge;
        }
        earned[person] = kept;
      }
    }
    const walks: BadgeStore['walks'] = {};
    if (isRecord(saved.walks)) {
      for (const [person, list] of Object.entries(saved.walks)) {
        if (Array.isArray(list)) walks[person] = readWalks(list);
      }
    }
    return { claims, earned, walks, seen };
  } catch {
    return empty;
  }
}

export function saveBadgeStore(storage: StorageLike, store: BadgeStore): void {
  try {
    storage.setItem(BADGES_KEY, JSON.stringify(store));
  } catch {
    // Storage blocked: claims last until the page reloads.
  }
}

/**
 * What another tab saved, joined with this one's, so neither undoes the other: every claim and
 * every first look (the earlier time if both have one), every remembered badge (the first kept),
 * every walk once.
 */
export function mergeStores(saved: BadgeStore, mine: BadgeStore): BadgeStore {
  const people = (a: object, b: object) => [...new Set([...Object.keys(a), ...Object.keys(b)])];
  /** Both tabs' moments, the earlier one where both have one. */
  const earliest = (a: BadgeStore['claims'], b: BadgeStore['claims']) => {
    const out: BadgeStore['claims'] = {};
    for (const person of people(a, b)) {
      const joined = { ...(a[person] ?? {}) };
      for (const [key, at] of Object.entries(b[person] ?? {})) {
        joined[key] = Math.min(at, joined[key] ?? at);
      }
      out[person] = joined;
    }
    return out;
  };
  const claims = earliest(saved.claims, mine.claims);
  const earned: BadgeStore['earned'] = {};
  for (const person of people(saved.earned, mine.earned)) {
    earned[person] = { ...(mine.earned[person] ?? {}), ...(saved.earned[person] ?? {}) };
  }
  const walks: BadgeStore['walks'] = {};
  for (const person of people(saved.walks, mine.walks)) {
    let joined: FinishedWalk[] = [...(saved.walks[person] ?? [])];
    for (const walk of mine.walks[person] ?? []) joined = addWalk(joined, walk);
    walks[person] = joined.sort((a, b) => a.at - b.at).slice(-KEEP_WALKS);
  }
  return { claims, earned, walks, seen: earliest(saved.seen ?? {}, mine.seen ?? {}) };
}

/**
 * A walk to record, or null: only the moment the demo walk finishes, only while she shares it,
 * and only the part she shared (`sharedM`, from the readings kept while sharing). `at` is the real
 * time it finished, so it is never later than when she claims the badge.
 */
export function finishedWalk(
  before: { finished: boolean } | null | undefined,
  now: { finished: boolean } | null | undefined,
  sharing: boolean,
  sharedM: number,
  at: number,
): FinishedWalk | null {
  if (!now?.finished || before?.finished || !sharing) return null;
  if (!(sharedM >= SHORT_WALK_M)) return null;
  return { at, distanceM: Math.round(sharedM) };
}

/** When a claim is recorded: now, but never before the badge was earned. */
export function claimTime(badge: BadgeResult, now: number): number {
  return badge.earnedAt !== null ? Math.max(now, badge.earnedAt) : now;
}

/** A finished walk, added once (the same end time is never counted twice). */
export function addWalk(walks: readonly FinishedWalk[], walk: FinishedWalk): FinishedWalk[] {
  if (walks.some((saved) => saved.at === walk.at)) return [...walks];
  return [...walks, walk].slice(-KEEP_WALKS);
}

// ---- Words ----

const YEAR = new Intl.DateTimeFormat('en-US', { timeZone: PRODUCT_TIME_ZONE, year: 'numeric' });

/** A moment in Singapore time with its year: "Sat, 31 Oct 2026, 3:42 pm". */
export function momentWords(at: number): string {
  const moment = new Date(at);
  const time = formatMomentTime(moment).split(', ').pop();
  return `${formatMomentDay(moment)} ${YEAR.format(moment)}, ${time}`;
}

/** When it was earned: "Thu, 6 Aug 2026", or with the time for a walk badge. */
export function earnedWords(badge: BadgeResult): string {
  if (badge.earnedAt !== null) return momentWords(badge.earnedAt);
  if (badge.earnedDay) return `${formatIsoDay(badge.earnedDay)} ${badge.earnedDay.slice(0, 4)}`;
  return 'Not earned yet';
}

const GERUNDS: Record<string, string> = {
  Walk: 'walking',
  Have: 'having',
  Beat: 'beating',
  Finish: 'finishing',
};

/** "Walk 5,000 steps in one day." as "walking 5,000 steps in one day". */
function asDeed(how: string): string {
  const [verb, ...rest] = how.replace(/\.$/, '').split(' ');
  return [GERUNDS[verb] ?? verb.toLowerCase(), ...rest].join(' ');
}

/**
 * One sentence under a badge seen up close, in the way she would say it. `who` is "You" on her
 * own page and her name for the family.
 */
export function badgeSentence(badge: BadgeResult, who: string): string {
  if (!badge.earned) return badge.how;
  const deed = badge.deed ?? asDeed(badge.how);
  return `${who} earned this for ${deed}, on ${earnedWords(badge)}.`;
}

/** "6 of 15 earned", for the shelf's heading. */
export function shelfSummary(badges: readonly BadgeResult[]): string {
  const earned = badges.filter((badge) => badge.earned).length;
  return `${earned} of ${badges.length} earned`;
}
