import type { DailyMetric, WearableStatus } from '@silverloop/api-client';

/**
 * The rules behind the Watch page: what each point around the 3D watch says, how the watch turns
 * to show it, and the easing for its spins. Pure and relative-import only (type imports are
 * stripped), so `lib/watch.test.ts` can run it under Node's type stripping.
 *
 * Every figure comes from data the app already has: the senior's daily metrics (steps, active
 * minutes, sleep hours, wear hours) and the simulated watch status (connected, battery, charging).
 * Nothing here reads heart rate, and nothing is framed as a medical sign: a day is only ever
 * compared with the senior's own usual.
 */

export type WatchPointId =
  'steps' | 'active' | 'sleep' | 'wear' | 'battery' | 'connection' | 'water';

/** How the watch is turned, in degrees: `yaw` around the upright axis, `pitch` tipping it back. */
export interface WatchPose {
  yaw: number;
  pitch: number;
}

/** One bar in a detail chart. */
export interface WatchBar {
  label: string;
  value: number;
}

/** One row in a detail panel. */
export interface WatchFact {
  icon: string;
  label: string;
  value: string;
  /** A line or two more, shown when the row is opened. */
  more?: string;
}

export interface WatchPoint {
  id: WatchPointId;
  label: string;
  /** The short line under the label, e.g. "5,720 today". */
  value: string;
  /** Which side of the watch the point sits on (wide screens). */
  side: 'left' | 'right';
  /** An icon name from `Icon.vue`. */
  icon: string;
  /** How the watch turns when this point is opened. */
  pose: WatchPose;
  /** Which way the watch faces when this point is opened. */
  view: 'front' | 'back';
  /** The detail panel. */
  headline: string;
  /** A calm note beside the headline, never a warning ("About the same as usual"). */
  note: string | null;
  /** Up to 14 bars, oldest first, or none. */
  bars: WatchBar[];
  /** A dashed guide across the bars (wear time's 8 hours), if any. */
  guide: number | null;
  facts: WatchFact[];
  /** Fixed device information rather than the senior's data. */
  example?: boolean;
}

/** A day counts as worn when the watch was on for at least this long (see CONTEXT.md). */
export const VALID_WEAR_HOURS = 8;

/** Within this share of usual, a day is "about the same". */
const SAME_SHARE = 0.15;

// ---- Numbers into words ----

export function median(values: readonly number[]): number | null {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/** A day against the senior's own usual: "about the same", "more" or "less" than usual. */
export function compareToUsual(value: number, usual: number | null): string | null {
  if (usual === null || usual <= 0) return null;
  const change = (value - usual) / usual;
  if (Math.abs(change) <= SAME_SHARE) return 'About the same as usual';
  return change > 0 ? 'More than usual' : 'Less than usual';
}

/** 7.4 hours as "7 h 24 min" (and 8 as "8 h"). */
export function hoursLabel(hours: number): string {
  const total = Math.max(0, Math.round(hours * 60));
  const whole = Math.floor(total / 60);
  const minutes = total % 60;
  if (!whole) return `${minutes} min`;
  return minutes ? `${whole} h ${minutes} min` : `${whole} h`;
}

const numberFormat = new Intl.NumberFormat('en-SG');
export function formatNumber(value: number): string {
  return numberFormat.format(Math.round(value));
}

/** "Tue" for a `YYYY-MM-DD` day, read as a calendar date (no time zone shift). */
export function weekdayOf(day: string): string {
  const [year, month, date] = day.split('-').map(Number);
  if (!year || !month || !date) return '';
  return new Intl.DateTimeFormat('en-SG', { weekday: 'short', timeZone: 'UTC' }).format(
    new Date(Date.UTC(year, month - 1, date)),
  );
}

function barsOf(metrics: readonly DailyMetric[], read: (metric: DailyMetric) => number | null) {
  return metrics
    .slice(-14)
    .map((metric) => ({ label: weekdayOf(metric.day), value: read(metric) }))
    .filter((bar): bar is WatchBar => bar.value !== null && Number.isFinite(bar.value));
}

// ---- The points ----

export interface WatchInput {
  /** Steps so far today, or `null` when unknown. */
  steps: number | null;
  /** The senior's usual day of steps, or `null`. */
  usualSteps: number | null;
  /** Recent daily metrics, oldest first (the last one is the latest day). */
  metrics: readonly DailyMetric[];
  wearable: WearableStatus | null;
  /** "5 min ago", worked out by the caller (`syncedAgo`), or `null`. */
  syncedAgo: string | null;
  /** What the family calls the senior. */
  elder: string;
}

/** The poses the watch turns to: its face, its back (the sensors) and its crown side. */
const FRONT: WatchPose = { yaw: -24, pitch: -8 };
const BACK: WatchPose = { yaw: 168, pitch: -10 };
const CROWN: WatchPose = { yaw: -62, pitch: -6 };
const TILTED: WatchPose = { yaw: 22, pitch: -18 };

/** What each detail row says when it is opened, keyed `point:label`. */
const MORE: Record<string, string> = {
  'steps:Usual day':
    'The middle of the last two weeks of steps. Each day is compared with this, never with anyone else.',
  'steps:Days shown': 'One bar per day, oldest on the left. The bright bar is the latest day.',
  'active:Usual day': 'The middle of the last two weeks of active minutes.',
  'active:Counted': 'Minutes the watch counted as brisk movement, such as a walk at a steady pace.',
  'sleep:Usual night': 'The middle of the nights the watch recorded over the last two weeks.',
  'sleep:Nights recorded':
    'Sleep is only recorded on nights the watch was worn to bed. A missing night is left blank.',
  'wear:Days that counted': 'Days the watch was worn for at least 8 hours.',
  'wear:Why it matters':
    'A day worn only briefly says little about the day, so Care+ leaves it out of any comparison.',
  'battery:Charging': 'Shown as soon as the watch is put on its charger.',
  'battery:Last synced': 'When the watch last sent its readings to Care+.',
  'battery:General care tip':
    'General device-care tip: follow the manufacturer’s charging instructions.',
  'connection:Status': 'Connected means the watch is sending readings to Care+.',
  'connection:Last synced': 'When the watch last sent its readings.',
  'connection:Source':
    'This is a simulated watch, so the readings are sample data until a real watch is linked.',
  'water:Fine for': 'Water on the surface, like rain, a shower or a swim in a pool.',
  'water:Avoid': 'Hot water and strong jets can push water past the seals.',
  'water:After a swim': 'Fresh water rinses off chlorine and salt, which can wear the strap.',
};

export function watchPoints(input: WatchInput): WatchPoint[] {
  const { metrics, wearable, elder } = input;
  const latest = metrics.length ? metrics[metrics.length - 1] : null;
  const earlier = metrics.slice(0, -1);

  // Steps: today's running count against the usual day.
  const steps = input.steps ?? latest?.steps ?? null;
  const usualSteps = input.usualSteps ?? median(earlier.map((metric) => metric.steps));
  // Active minutes, sleep and wear: the latest day against the days before it.
  const active = latest?.active_minutes ?? null;
  const usualActive = median(earlier.map((metric) => metric.active_minutes));
  const sleepNights = metrics.filter((metric) => typeof metric.sleep_hours === 'number');
  const sleep = sleepNights.length
    ? (sleepNights[sleepNights.length - 1].sleep_hours ?? null)
    : null;
  const usualSleep = median(sleepNights.slice(0, -1).map((metric) => metric.sleep_hours ?? 0));
  const wear = latest?.wear_hours ?? null;
  const wornDays = metrics.slice(-14).filter((metric) => metric.wear_hours >= VALID_WEAR_HOURS);

  const battery = wearable?.battery_percent ?? null;
  const charging = wearable?.charging ?? false;
  const connected = wearable?.connected ?? false;

  const list: WatchPoint[] = [
    {
      id: 'steps',
      label: 'Steps',
      value: steps === null ? 'Not available' : `${formatNumber(steps)} today`,
      side: 'left',
      icon: 'walk',
      pose: FRONT,
      view: 'front',
      headline: steps === null ? 'Not available' : `${formatNumber(steps)} steps`,
      note: steps === null ? null : compareToUsual(steps, usualSteps),
      bars: barsOf(metrics, (metric) => metric.steps),
      guide: null,
      facts: [
        {
          icon: 'walk',
          label: 'Usual day',
          value: usualSteps === null ? '—' : `${formatNumber(usualSteps)} steps`,
        },
        {
          icon: 'calendar',
          label: 'Days shown',
          value: `The last ${Math.min(14, metrics.length)} days`,
        },
      ],
    },
    {
      id: 'active',
      label: 'Active minutes',
      value: active === null ? 'Not available' : `${active} min`,
      side: 'left',
      icon: 'activity',
      pose: TILTED,
      view: 'front',
      headline: active === null ? 'Not available' : `${active} active minutes`,
      note: active === null ? null : compareToUsual(active, usualActive),
      bars: barsOf(metrics, (metric) => metric.active_minutes),
      guide: null,
      facts: [
        {
          icon: 'activity',
          label: 'Usual day',
          value: usualActive === null ? '—' : `${Math.round(usualActive)} min`,
        },
        { icon: 'clock', label: 'Counted', value: 'Minutes of brisk movement, from the watch' },
      ],
    },
    {
      id: 'sleep',
      label: 'Sleep',
      value: sleep === null ? 'Not recorded' : hoursLabel(sleep),
      side: 'left',
      icon: 'moon',
      pose: FRONT,
      view: 'front',
      headline: sleep === null ? 'Not recorded' : hoursLabel(sleep),
      note: sleep === null ? null : compareToUsual(sleep, usualSleep),
      bars: barsOf(metrics, (metric) => metric.sleep_hours ?? null),
      guide: null,
      facts: [
        {
          icon: 'moon',
          label: 'Usual night',
          value: usualSleep === null ? '—' : hoursLabel(usualSleep),
        },
        {
          icon: 'calendar',
          label: 'Nights recorded',
          value: `${sleepNights.slice(-14).length} of the last ${Math.min(14, metrics.length)}`,
        },
      ],
    },
    {
      id: 'wear',
      label: 'Wear time',
      value: wear === null ? 'Not available' : hoursLabel(wear),
      side: 'left',
      icon: 'clock',
      pose: BACK,
      view: 'back',
      headline: wear === null ? 'Not available' : `${hoursLabel(wear)} worn`,
      note:
        wear === null
          ? null
          : wear >= VALID_WEAR_HOURS
            ? 'Worn long enough to count the day'
            : `Under ${VALID_WEAR_HOURS} h, so the day is not counted`,
      bars: barsOf(metrics, (metric) => metric.wear_hours),
      guide: VALID_WEAR_HOURS,
      facts: [
        {
          icon: 'check-circle',
          label: 'Days that counted',
          value: `${wornDays.length} of the last ${Math.min(14, metrics.length)}`,
        },
        {
          icon: 'info',
          label: 'Why it matters',
          value: `Care+ only compares days worn ${VALID_WEAR_HOURS} h or more`,
        },
      ],
    },
    {
      id: 'battery',
      label: charging ? 'Charging' : 'Battery',
      value: battery === null ? 'Not available' : `${battery}%${charging ? ' · charging' : ''}`,
      side: 'right',
      icon: 'battery',
      // On the charger: show its back with the charger docked. Otherwise: the battery on screen.
      pose: charging ? BACK : FRONT,
      view: charging ? 'back' : 'front',
      headline: battery === null ? 'Not available' : `${battery}%`,
      note: charging
        ? 'Charging now'
        : battery !== null && battery <= 20
          ? `Remind ${elder} to charge it`
          : null,
      bars: [],
      guide: null,
      facts: [
        { icon: 'battery', label: 'Charging', value: charging ? 'Yes, on the charger' : 'No' },
        {
          icon: 'clock',
          label: 'Last synced',
          value: input.syncedAgo ?? 'Not yet',
        },
        {
          icon: 'info',
          label: 'General care tip',
          value: 'Follow the manufacturer’s charging instructions',
        },
      ],
    },
    {
      id: 'connection',
      label: 'Connection',
      value: wearable === null ? 'Checking…' : connected ? 'Connected' : 'Not connected',
      side: 'right',
      icon: 'link',
      pose: CROWN,
      view: 'front',
      headline: wearable === null ? 'Checking…' : connected ? 'Connected' : 'Not connected',
      note: input.syncedAgo ? `Synced ${input.syncedAgo.replace(/^synced\s*/i, '')}` : null,
      bars: [],
      guide: null,
      facts: [
        {
          icon: 'link',
          label: 'Status',
          value: connected ? 'Sending readings' : 'Waiting for the watch',
        },
        { icon: 'clock', label: 'Last synced', value: input.syncedAgo ?? 'Not yet' },
        { icon: 'info', label: 'Source', value: 'Simulated watch, until a real one is linked' },
      ],
    },
    {
      id: 'water',
      label: 'Water resistance',
      value: '50 m',
      side: 'right',
      icon: 'water',
      pose: TILTED,
      view: 'front',
      headline: '50 m',
      note: 'Example spec for the simulated watch',
      bars: [],
      guide: null,
      example: true,
      facts: [
        { icon: 'water', label: 'Fine for', value: 'Hand washing, rain, showering, swimming' },
        { icon: 'x', label: 'Avoid', value: 'Hot tubs, saunas and high-pressure water' },
        { icon: 'info', label: 'After a swim', value: 'Rinse with fresh water and dry the strap' },
      ],
    },
  ];
  // Each row opens to say a little more.
  for (const point of list) {
    for (const fact of point.facts) fact.more = MORE[`${point.id}:${fact.label}`];
  }
  return list;
}

/** Watch care, as general tips. "Today" reflects the watch's real status. */
export function careTimeline(wearable: WearableStatus | null) {
  const battery = wearable?.battery_percent ?? null;
  const today =
    wearable === null
      ? 'Checking…'
      : !wearable.connected
        ? 'Not connected'
        : battery !== null && battery <= 20 && !wearable.charging
          ? 'Needs charging'
          : 'All good';
  return [
    { when: 'Today', what: today, now: true },
    { when: '3 months', what: 'Clean sensors', now: false },
    { when: '6 months', what: 'Check battery', now: false },
    { when: '12 months', what: 'General check', now: false },
  ];
}

// ---- Turning the watch ----

export function easeOutCubic(t: number): number {
  const clamped = Math.max(0, Math.min(1, t));
  return 1 - (1 - clamped) ** 3;
}

export function easeInOutCubic(t: number): number {
  const clamped = Math.max(0, Math.min(1, t));
  return clamped < 0.5 ? 4 * clamped ** 3 : 1 - (-2 * clamped + 2) ** 3 / 2;
}

/** An angle in (-180, 180]. */
export function wrapAngle(degrees: number): number {
  const turned = ((((degrees + 180) % 360) + 360) % 360) - 180;
  return turned === -180 ? 180 : turned;
}

/** Where to aim so the watch takes the short way round from `from` to `to`. */
export function nearestTurn(from: number, to: number): number {
  return from + wrapAngle(to - from);
}

/** Viewport framing for the CSS watch; coordinates describe the centre of its scene. */
export function watchFrame(id: WatchPointId, width: number, height: number) {
  const compact = width < 992;
  const magnification: Record<WatchPointId, number> = {
    // Close enough that the watch fills its half of the screen, as in a product close-up.
    steps: 3.0,
    active: 2.9,
    sleep: 3.3,
    wear: 3.2,
    battery: 2.9,
    connection: 3.4,
    water: 3.4,
  };
  if (compact) {
    return {
      x: width / 2,
      y: 218,
      // Keep the entire case within the phone, including at 375 px.
      scale: Math.min(0.9, Math.max(0.5, width / 440)),
    };
  }
  return {
    x: width * (id === 'connection' ? 0.74 : 0.7),
    y: height * (id === 'sleep' ? 0.56 : 0.53),
    scale: magnification[id] * Math.min(1.35, Math.max(0.7, height / 850)),
  };
}
