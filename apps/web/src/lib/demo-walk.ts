/**
 * The simulated walk that stands in for a real watch's GPS until one is connected. A made-up
 * senior's made-up walk from a made-up home through Bishan–Ang Mo Kio Park and back: about 2.4 km,
 * at an older walker's pace, with two rests, a little GPS wobble, and controls to pause it, speed it
 * up, keep her in one place, skip ahead or lose the signal. Pure and free of Vue so
 * `lib/demo-walk.test.ts` can run it.
 *
 * The route is drawn by hand around the park, not traced from a map, so on the street map it may
 * not follow the park's paths exactly. A recorded walk (a GPX file) can be played instead.
 */
import { offsetM, pathLengthM, pointAlong, type LngLat } from './geo';
import type { UsualPlace } from './stillness';
import type { Place, WalkFix } from './walk';

export interface DemoRoute {
  name: string;
  path: LngLat[];
  home: Place;
  /** Where she sits down, as metres along the path, and for how long. */
  rests: { atM: number; forMs: number }[];
  /** Named spots for "near the pond". */
  landmarks: Place[];
  /** Places where a long stay is normal, so no check-in alert. */
  usualPlaces: UsualPlace[];
  /** What to call anywhere else. */
  area: string;
}

/** An older walker's pace: about 3.2 km an hour. */
export const WALK_SPEED_MPS = 0.9;
/** How often the watch sends a reading. */
export const FIX_EVERY_MS = 5_000;
/** How much reading history is kept: enough for a long day out. */
export const KEEP_FIXES = 6 * 720;

const HOME: LngLat = [103.8442, 1.3664];

/** The park loop: out along the north bank, over the river, back along the south bank. */
const PARK_LOOP: LngLat[] = [
  HOME,
  [103.84405, 1.36585],
  [103.8439, 1.3653],
  [103.8433, 1.3647],
  [103.8423, 1.3641],
  [103.841, 1.3636],
  [103.8396, 1.3633],
  [103.8383, 1.363],
  [103.8376, 1.3625],
  [103.838, 1.36195],
  [103.8393, 1.362],
  [103.8408, 1.3623],
  [103.8423, 1.36255],
  [103.8438, 1.36275],
  [103.8453, 1.363],
  [103.8464, 1.3634],
  [103.8462, 1.3641],
  [103.8453, 1.3647],
  [103.8444, 1.3652],
  [103.84405, 1.36585],
  HOME,
];

/** Metres along `PARK_LOOP` to a given corner, for placing the rests. */
function metresTo(index: number): number {
  return pathLengthM(PARK_LOOP.slice(0, index + 1));
}

const place = (name: string, at: LngLat, radiusM: number): Place => ({
  name,
  lng: at[0],
  lat: at[1],
  radiusM,
});

export const DEMO_ROUTE: DemoRoute = {
  name: 'Bishan–Ang Mo Kio Park loop',
  path: PARK_LOOP,
  home: place('Home', HOME, 60),
  rests: [
    { atM: metresTo(7), forMs: 6 * 60_000 },
    { atM: metresTo(15), forMs: 4 * 60_000 },
  ],
  landmarks: [
    place('the park entrance', [103.8439, 1.3653], 50),
    place('the big lawn', [103.8383, 1.363], 70),
    place('the river bridge', [103.8378, 1.3622], 45),
    place('the pond', [103.8464, 1.3634], 60),
    place('the river path', [103.8415, 1.3633], 160),
  ],
  usualPlaces: [{ ...place('Active Ageing Centre', [103.8455, 1.367], 60), extraMs: null }],
  area: 'Bishan–Ang Mo Kio Park',
};

export interface SimState {
  /** The simulated clock, ms since 1970. Runs faster than real time at 5× or 20×. */
  clock: number;
  startedAt: number;
  nextFixAt: number;
  progressM: number;
  restIndex: number;
  restUntil: number | null;
  /** Demo control: she stays where she is, however much time passes. */
  stayStill: boolean;
  /** Demo control: the watch sends nothing. */
  signalLost: boolean;
  finished: boolean;
  /** For the GPS wobble: the same walk wobbles the same way every time. */
  seed: number;
}

export function startSim(now: number): SimState {
  return {
    clock: now,
    startedAt: now,
    nextFixAt: now,
    progressM: 0,
    restIndex: 0,
    restUntil: null,
    stayStill: false,
    signalLost: false,
    finished: false,
    seed: 20_261_023,
  };
}

/** A small seeded random number generator (mulberry32): 0 to 1, and the next seed. */
function random(seed: number): [number, number] {
  const next = (seed + 0x6d2b79f5) | 0;
  let t = next;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return [((t ^ (t >>> 14)) >>> 0) / 4_294_967_296, next];
}

/** Moves her along the path from time `from` to `to`, sitting out any rests on the way. */
function move(state: SimState, route: DemoRoute, length: number, from: number, to: number): void {
  let t = from;
  while (t < to) {
    if (state.finished || state.stayStill) return;
    if (state.restUntil !== null) {
      if (state.restUntil >= to) return;
      t = state.restUntil;
      state.restUntil = null;
      continue;
    }
    const rest = route.rests[state.restIndex];
    const stopAt = rest ? Math.min(rest.atM, length) : length;
    const canWalk = ((to - t) / 1000) * WALK_SPEED_MPS;
    if (state.progressM + canWalk >= stopAt) {
      t += ((stopAt - state.progressM) / WALK_SPEED_MPS) * 1000;
      state.progressM = stopAt;
      if (rest) {
        state.restIndex += 1;
        state.restUntil = t + rest.forMs;
      } else {
        state.finished = true;
      }
    } else {
      state.progressM += canWalk;
      t = to;
    }
  }
}

function moving(state: SimState): boolean {
  return !state.finished && !state.stayStill && state.restUntil === null;
}

/** One reading at the current spot, wobbled by up to a few metres as real GPS is. */
function readingAt(state: SimState, route: DemoRoute, at: number): WalkFix {
  const { point, bearing } = pointAlong(route.path, state.progressM);
  let r: number;
  [r, state.seed] = random(state.seed);
  const angle = r * 2 * Math.PI;
  [r, state.seed] = random(state.seed);
  const wobble = 1 + r * 3.5;
  [r, state.seed] = random(state.seed);
  const accuracyM = Math.round(5 + r * 7);
  const [lng, lat] = offsetM(point, Math.sin(angle) * wobble, Math.cos(angle) * wobble);
  return { at, lng, lat, accuracyM, heading: moving(state) ? Math.round(bearing) : null };
}

/**
 * Runs the simulation forward by `elapsedMs` of simulated time, returning the new state and every
 * reading the watch would have sent in that time (none while the signal is lost).
 */
export function advanceSim(
  current: SimState,
  route: DemoRoute,
  elapsedMs: number,
): { state: SimState; fixes: WalkFix[] } {
  const state = { ...current };
  const length = pathLengthM(route.path);
  const target = state.clock + Math.max(0, elapsedMs);
  const fixes: WalkFix[] = [];
  let t = state.clock;
  while (state.nextFixAt <= target) {
    move(state, route, length, t, state.nextFixAt);
    t = state.nextFixAt;
    if (!state.signalLost) fixes.push(readingAt(state, route, t));
    state.nextFixAt += FIX_EVERY_MS;
  }
  move(state, route, length, t, target);
  state.clock = target;
  return { state, fixes };
}

/** Where the simulated walker is right now, without the wobble (for tests and the start pin). */
export function simPosition(state: SimState, route: DemoRoute): LngLat {
  return pointAlong(route.path, state.progressM).point;
}

/**
 * The track points of a GPX file (what Strava, Garmin and most watches export), as
 * `[longitude, latitude]`. Long tracks are thinned to at most `maxPoints`. Throws a plain-words
 * error when the file has no usable track. The file is read in the browser and never sent anywhere.
 */
export function parseGpx(text: string, maxPoints = 2000): LngLat[] {
  const points: LngLat[] = [];
  for (const match of text.matchAll(/<(?:trkpt|rtept)\b([^>]*)>/g)) {
    const lat = Number(/\blat\s*=\s*["']([-+\d.]+)["']/.exec(match[1])?.[1]);
    const lng = Number(/\blon\s*=\s*["']([-+\d.]+)["']/.exec(match[1])?.[1]);
    if (
      Number.isFinite(lat) &&
      Number.isFinite(lng) &&
      Math.abs(lat) <= 90 &&
      Math.abs(lng) <= 180
    ) {
      points.push([lng, lat]);
    }
  }
  if (points.length < 2)
    throw new Error('That file has no walk in it. Choose a GPX file with a track.');
  if (points.length <= maxPoints) return points;
  const step = points.length / maxPoints;
  const thinned: LngLat[] = [];
  for (let i = 0; i < maxPoints - 1; i += 1) thinned.push(points[Math.floor(i * step)]);
  thinned.push(points[points.length - 1]);
  return thinned;
}

/** A route from a recorded track: home is where it starts; no rests or named places. */
export function routeFromTrack(path: LngLat[], name: string): DemoRoute {
  return {
    name,
    path,
    home: place('Home', path[0], 60),
    rests: [],
    landmarks: [],
    usualPlaces: [],
    area: 'the recorded route',
  };
}

/**
 * The senior's phone number for Call and Message. The family data has no phone numbers yet, so the
 * demo uses this obviously made-up one; a real number would come from the senior's profile.
 */
export const DEMO_SENIOR_PHONE = { dial: '+6500000000', words: '+65 0000 0000 (demo number)' };
