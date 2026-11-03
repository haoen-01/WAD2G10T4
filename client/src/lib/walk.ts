/**
 * A senior's walk, read from the GPS fixes their watch sends: how far, how long, whether they are
 * walking, resting, home, or out of signal, and roughly where. Pure and free of Vue so
 * `lib/walk.test.ts` can run it under Node's type stripping.
 *
 * Location only: nothing here reads heart rate or guesses at health. "Resting" means the fixes have
 * stayed in one small area for a few minutes, nothing more.
 */
import { distanceM, type LngLat } from './geo';

/** One GPS reading from the watch. `at` is milliseconds since 1970 (UTC). */
export interface WalkFix {
  at: number;
  lng: number;
  lat: number;
  /** How far off the reading may be, in metres (the watch's own estimate). */
  accuracyM: number;
  /** Direction of travel, 0 = north, or null when not moving. */
  heading: number | null;
}

/** A named spot: home, a landmark, a place she often stays at. */
export interface Place {
  name: string;
  lng: number;
  lat: number;
  radiusM: number;
}

export type WalkState = 'waiting' | 'walking' | 'resting' | 'home' | 'signal_lost';

/** No reading for this long and the watch is treated as out of signal. */
export const SIGNAL_LOST_MS = 60_000;
/** In one small area for this long counts as resting. */
export const REST_AFTER_MS = 3 * 60_000;
/** "One small area" for resting: GPS wanders a few metres even when someone sits still. */
export const REST_RADIUS_M = 25;
/** Moves shorter than this between counted points are treated as GPS noise, not walking. */
export const NOISE_M = 8;
/** An average stride, for an "about … steps" figure. Labelled as an estimate wherever shown. */
export const STRIDE_M = 0.65;

export const lngLatOf = (fix: Pick<WalkFix, 'lng' | 'lat'>): LngLat => [fix.lng, fix.lat];

export function isAt(place: Place, fix: Pick<WalkFix, 'lng' | 'lat'>): boolean {
  return distanceM(lngLatOf(place), lngLatOf(fix)) <= place.radiusM;
}

/**
 * How far she has walked: the fixes are followed, but a step only counts once she is more than
 * `NOISE_M` from the last counted point, so GPS wobble while sitting does not add distance.
 */
export function walkedDistanceM(fixes: readonly WalkFix[]): number {
  if (fixes.length < 2) return 0;
  let total = 0;
  let anchor = lngLatOf(fixes[0]);
  for (let i = 1; i < fixes.length; i += 1) {
    const here = lngLatOf(fixes[i]);
    const step = distanceM(anchor, here);
    if (step >= NOISE_M) {
      total += step;
      anchor = here;
    }
  }
  return total;
}

export interface WalkSummary {
  distanceM: number;
  durationMs: number;
  /** Minutes per kilometre while out, or null before there is enough to say. */
  paceMinPerKm: number | null;
  /** Distance divided by an average stride: an estimate, not the watch's step count. */
  aboutSteps: number;
}

export function summarise(fixes: readonly WalkFix[], now: number): WalkSummary {
  if (fixes.length === 0) return { distanceM: 0, durationMs: 0, paceMinPerKm: null, aboutSteps: 0 };
  const distance = walkedDistanceM(fixes);
  const duration = Math.max(0, now - fixes[0].at);
  const pace = distance >= 100 ? duration / 60_000 / (distance / 1000) : null;
  return {
    distanceM: distance,
    durationMs: duration,
    paceMinPerKm: pace,
    aboutSteps: Math.round(distance / STRIDE_M),
  };
}

/**
 * What she is doing now. Out of signal wins (a lost watch says nothing about moving), then home,
 * then resting (still within `REST_RADIUS_M` of the latest fix for `REST_AFTER_MS`), else walking.
 */
export function walkState(fixes: readonly WalkFix[], now: number, home: Place): WalkState {
  const last = fixes[fixes.length - 1];
  if (!last) return 'waiting';
  if (now - last.at > SIGNAL_LOST_MS) return 'signal_lost';
  // Home only once she has been out: setting off from the front door is the start of a walk.
  if (isAt(home, last)) return fixes.some((fix) => !isAt(home, fix)) ? 'home' : 'walking';
  const here = lngLatOf(last);
  let since = last.at;
  for (let i = fixes.length - 1; i >= 0; i -= 1) {
    if (distanceM(lngLatOf(fixes[i]), here) > REST_RADIUS_M) break;
    since = fixes[i].at;
  }
  return now - since >= REST_AFTER_MS ? 'resting' : 'walking';
}

export const STATE_WORDS: Record<WalkState, string> = {
  waiting: 'Not out on a walk',
  walking: 'Walking',
  resting: 'Resting',
  home: 'Back home',
  signal_lost: 'Watch out of signal',
};

/** "near the pond": the closest named place within its radius, else `fallback`. */
export function nearWords(
  point: Pick<WalkFix, 'lng' | 'lat'>,
  places: readonly Place[],
  fallback: string,
): string {
  let best: { place: Place; distance: number } | null = null;
  for (const place of places) {
    const distance = distanceM(lngLatOf(place), lngLatOf(point));
    if (distance <= place.radiusM && (!best || distance < best.distance))
      best = { place, distance };
  }
  return best ? best.place.name : fallback;
}

/** "1.2 km", "350 m". */
export function formatDistance(metres: number): string {
  if (metres < 1000) return `${Math.round(metres / 10) * 10} m`;
  return `${(metres / 1000).toFixed(1)} km`;
}

/** "1 h 05 min", "12 min", "under a minute". */
export function formatDuration(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return 'under a minute';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return `${hours} h ${String(rest).padStart(2, '0')} min`;
}

/** "8 s ago", "3 min ago", "1 h 10 min ago". */
export function ago(ms: number): string {
  if (ms < 60_000) return `${Math.max(0, Math.round(ms / 1000))} s ago`;
  return `${formatDuration(ms)} ago`;
}

/** "4:05 pm", in the computer's own time, like the calendar. */
export function clockTime(at: number): string {
  const time = new Date(at);
  const hours = time.getHours();
  const minutes = String(time.getMinutes()).padStart(2, '0');
  return `${hours % 12 || 12}:${minutes} ${hours < 12 ? 'am' : 'pm'}`;
}
