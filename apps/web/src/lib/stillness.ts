/**
 * The "Still for a while" check-in: has the senior stayed in one spot, away from home, for longer
 * than the family's limit? Pure and free of Vue so `lib/stillness.test.ts` pins every rule.
 *
 * This is a stillness timer on location and nothing more. It is not fall detection and makes no
 * guess about health: it never says she has fallen or is unwell, it never contacts anyone by
 * itself, and it only runs when the senior has turned it on. A person decides what to do.
 *
 * The rules, in order:
 * 1. No recent reading (the watch is out of signal): no stillness at all. No data is not "still".
 * 2. The stop is every reading, back from the latest, within `stillRadiusM` of where she is now
 *    (the average of the last few readings, so one wobbly reading does not move it), and it ends at
 *    any gap in the readings longer than `SIGNAL_LOST_MS`: time without signal never counts. GPS
 *    wobble does not restart the clock. The clock starts no earlier than when she turned the
 *    check-in on, and "I'm OK" from the senior restarts it.
 * 3. No alert at home, at a usual place that never alerts, during a calendar appointment, or for a
 *    stop the family has already marked "She's fine". A usual place may instead give extra time.
 * 4. Otherwise `soon` from `promptLeadMs` before the limit (the senior's page asks "Are you OK?"),
 *    and `alert` at the limit (the family is told), but only once she has been asked for at least
 *    `promptLeadMs`. The senior is always asked first, even after a gap or a late start.
 */
import { distanceM } from './geo';
import { lngLatOf, SIGNAL_LOST_MS, type Place, type WalkFix } from './walk';

export interface StillnessSettings {
  /** How long in one spot, away from home, before the family is told. */
  limitMs: number;
  /** "One spot": GPS readings within this many metres of the latest one. */
  stillRadiusM: number;
  /** How long before the limit the senior is asked "I'm OK?". */
  promptLeadMs: number;
}

export const MINUTE_MS = 60_000;
export const HOUR_MS = 60 * MINUTE_MS;

export const DEFAULT_STILLNESS: StillnessSettings = {
  limitMs: 2 * HOUR_MS,
  stillRadiusM: 50,
  promptLeadMs: 15 * MINUTE_MS,
};

/** The limits the family can choose from, in minutes: 30 minutes to 4 hours. */
export const LIMIT_CHOICES_MIN = [30, 60, 90, 120, 180, 240] as const;

/** A place where long stays are normal (the AAC, a friend's flat). `extraMs: null` = never alert. */
export interface UsualPlace extends Place {
  extraMs: number | null;
}

/** Something on the calendar, as a span of time. */
export interface BusyWindow {
  title: string;
  startMs: number;
  endMs: number;
}

/** Appointments start and end loosely: a little either side still counts as "at it". */
export const BUSY_MARGIN_MS = 30 * MINUTE_MS;

export type StillnessReason = 'home' | 'usual_place' | 'appointment' | 'dismissed';

export type Stillness =
  | { kind: 'none' }
  | { kind: 'no_signal' }
  | {
      kind: 'still';
      /** When the stop began (the earliest reading in it). Can shift by a reading or two. */
      stopStart: number;
      /** When the clock started: the stop's start, or the senior's latest "I'm OK". */
      since: number;
      forMs: number;
      lng: number;
      lat: number;
      /** How long this stop may last before the family is told (with any usual-place extra). */
      limitMs: number;
      /** When the family will be (or was) told, or null when this stop never alerts. */
      alertAt: number | null;
      /** Why this stop will not alert, if it will not. */
      quietBecause: StillnessReason | null;
      /** The usual place or appointment behind `quietBecause`, in words. */
      quietLabel: string | null;
      phase: 'quiet' | 'soon' | 'alert';
    };

export interface StillnessInput {
  fixes: readonly WalkFix[];
  now: number;
  home: Place;
  usualPlaces: readonly UsualPlace[];
  busy: readonly BusyWindow[];
  settings: StillnessSettings;
  /** When the senior last pressed "I'm OK", if ever. */
  okAt: number | null;
  /** When the senior turned the check-in on: time before that is not counted. */
  consentAt: number | null;
  /** When the senior was first asked "Are you OK?" about this stop, or null if not yet. */
  askedAt: number | null;
  /** Where and when the family last said "She's fine": quiet for the rest of that stop. */
  dismissed: { lng: number; lat: number; at: number } | null;
}

/** How many of the latest readings are averaged for "where she is now". */
export const ANCHOR_READINGS = 6;

export function checkStillness(input: StillnessInput): Stillness {
  const { fixes, now, settings } = input;
  const last = fixes[fixes.length - 1];
  if (!last) return { kind: 'none' };
  if (now - last.at > SIGNAL_LOST_MS) return { kind: 'no_signal' };

  const recent = fixes.slice(-ANCHOR_READINGS);
  const here: [number, number] = [
    recent.reduce((sum, fix) => sum + fix.lng, 0) / recent.length,
    recent.reduce((sum, fix) => sum + fix.lat, 0) / recent.length,
  ];
  let stopStart = last.at;
  for (let i = fixes.length - 1; i >= 0; i -= 1) {
    if (distanceM(lngLatOf(fixes[i]), here) > settings.stillRadiusM) break;
    if (i < fixes.length - 1 && fixes[i + 1].at - fixes[i].at > SIGNAL_LOST_MS) break;
    stopStart = fixes[i].at;
  }
  const since = Math.max(stopStart, input.okAt ?? stopStart, input.consentAt ?? stopStart);
  const forMs = Math.max(0, now - since);

  let quietBecause: StillnessReason | null = null;
  let quietLabel: string | null = null;
  let limitMs = settings.limitMs;

  const distanceTo = (place: Place) => distanceM([place.lng, place.lat], here);
  const usual = input.usualPlaces.find((place) => distanceTo(place) <= place.radiusM);
  const busy = input.busy.find(
    (window) => now >= window.startMs - BUSY_MARGIN_MS && now <= window.endMs + BUSY_MARGIN_MS,
  );

  if (distanceTo(input.home) <= input.home.radiusM) {
    quietBecause = 'home';
  } else if (usual && usual.extraMs === null) {
    quietBecause = 'usual_place';
    quietLabel = usual.name;
  } else if (busy) {
    quietBecause = 'appointment';
    quietLabel = busy.title;
  } else if (
    input.dismissed &&
    stopStart <= input.dismissed.at &&
    distanceTo({ name: '', radiusM: 0, ...input.dismissed }) <= settings.stillRadiusM
  ) {
    quietBecause = 'dismissed';
  } else if (usual) {
    limitMs += usual.extraMs ?? 0;
    quietLabel = usual.name;
  }

  let phase: 'quiet' | 'soon' | 'alert' = 'quiet';
  let alertAt: number | null = null;
  if (!quietBecause) {
    // She must have been asked for `promptLeadMs` before her family is told.
    const asked = input.askedAt !== null && input.askedAt >= since ? input.askedAt : null;
    alertAt = Math.max(
      since + limitMs,
      (asked ?? Math.max(now, since + limitMs - settings.promptLeadMs)) + settings.promptLeadMs,
    );
    if (now >= alertAt && asked !== null) phase = 'alert';
    else if (forMs >= limitMs - settings.promptLeadMs) phase = 'soon';
  }

  return {
    kind: 'still',
    stopStart,
    since,
    forMs,
    lng: here[0],
    lat: here[1],
    limitMs,
    alertAt,
    quietBecause,
    quietLabel,
    phase,
  };
}

/** "2 hours", "1 hour 30 minutes", "30 minutes": the limit in words. */
export function limitWords(limitMs: number): string {
  const minutes = Math.round(limitMs / MINUTE_MS);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const h = hours === 1 ? '1 hour' : `${hours} hours`;
  const m = rest === 1 ? '1 minute' : `${rest} minutes`;
  if (hours === 0) return m;
  return rest === 0 ? h : `${h} ${m}`;
}
