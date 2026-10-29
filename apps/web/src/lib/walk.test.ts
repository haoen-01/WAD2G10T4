import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { offsetM, type LngLat } from './geo';
import {
  ago,
  clockTime,
  formatDistance,
  formatDuration,
  nearWords,
  summarise,
  walkedDistanceM,
  walkState,
  type Place,
  type WalkFix,
} from './walk';

const START: LngLat = [103.8442, 1.3664];
const HOME: Place = { name: 'Home', lng: START[0], lat: START[1], radiusM: 60 };
const T0 = new Date(2026, 9, 23, 15, 0).getTime();

const fixAt = (at: number, point: LngLat): WalkFix => ({
  at,
  lng: point[0],
  lat: point[1],
  accuracyM: 6,
  heading: null,
});

/** Walks north at 1 m/s from home, a reading every 5 s, for `seconds`. */
function walkNorth(seconds: number, from = START, at = T0): WalkFix[] {
  const fixes: WalkFix[] = [];
  for (let s = 0; s <= seconds; s += 5) fixes.push(fixAt(at + s * 1000, offsetM(from, 0, s)));
  return fixes;
}

describe('walkedDistanceM', () => {
  it('adds up the walk', () => {
    assert.ok(Math.abs(walkedDistanceM(walkNorth(300)) - 300) < 1);
  });

  it('does not count GPS wobble while she sits still', () => {
    const spot = offsetM(START, 0, 400);
    const wobble = Array.from({ length: 60 }, (_, i) =>
      fixAt(T0 + i * 5000, offsetM(spot, i % 2 ? 3 : -3, i % 3 ? 2 : -2)),
    );
    assert.ok(walkedDistanceM(wobble) < 1);
  });
});

describe('summarise', () => {
  it('gives distance, time out, pace and an estimated step count', () => {
    const fixes = walkNorth(600);
    const summary = summarise(fixes, T0 + 600_000);
    assert.ok(Math.abs(summary.distanceM - 600) < 1);
    assert.equal(summary.durationMs, 600_000);
    assert.ok(summary.paceMinPerKm !== null && Math.abs(summary.paceMinPerKm - 16.67) < 0.1);
    assert.equal(summary.aboutSteps, Math.round(summary.distanceM / 0.65));
  });

  it('gives no pace before 100 m', () => {
    assert.equal(summarise(walkNorth(30), T0 + 30_000).paceMinPerKm, null);
    assert.equal(summarise([], T0).distanceM, 0);
  });
});

describe('walkState', () => {
  it('is waiting before any reading, and walking while she moves away from home', () => {
    assert.equal(walkState([], T0, HOME), 'waiting');
    const fixes = walkNorth(300);
    assert.equal(walkState(fixes, T0 + 300_000, HOME), 'walking');
  });

  it('is walking (not "back home") as she sets off from home', () => {
    assert.equal(walkState(walkNorth(20), T0 + 20_000, HOME), 'walking');
  });

  it('is resting after 3 minutes in one small area, and walking again before that', () => {
    const out = walkNorth(300);
    const spot = offsetM(START, 0, 300);
    const still = Array.from({ length: 40 }, (_, i) =>
      fixAt(T0 + 305_000 + i * 5000, offsetM(spot, i % 2 ? 4 : -4, 0)),
    );
    const two = still.slice(0, 24);
    assert.equal(walkState([...out, ...two], two[two.length - 1].at, HOME), 'walking');
    assert.equal(walkState([...out, ...still], still[still.length - 1].at, HOME), 'resting');
  });

  it('is back home once she returns after being out', () => {
    const out = walkNorth(300);
    const back = [...out, fixAt(T0 + 2_000_000, offsetM(START, 5, 5))];
    assert.equal(walkState(back, T0 + 2_000_000, HOME), 'home');
  });

  it('is out of signal after a minute without a reading, wherever she was', () => {
    const fixes = walkNorth(300);
    assert.equal(walkState(fixes, T0 + 300_000 + 61_000, HOME), 'signal_lost');
  });
});

describe('words', () => {
  it('names the nearest place within its radius, else the area', () => {
    const pond: Place = { name: 'the pond', lng: 103.8464, lat: 1.3634, radiusM: 60 };
    const lawn: Place = { name: 'the big lawn', lng: 103.8383, lat: 1.363, radiusM: 70 };
    const byPond = offsetM([pond.lng, pond.lat], 20, 0);
    assert.equal(
      nearWords({ lng: byPond[0], lat: byPond[1] }, [lawn, pond], 'the park'),
      'the pond',
    );
    assert.equal(nearWords({ lng: 103.85, lat: 1.37 }, [lawn, pond], 'the park'), 'the park');
  });

  it('formats distances, durations and times', () => {
    assert.equal(formatDistance(346), '350 m');
    assert.equal(formatDistance(1234), '1.2 km');
    assert.equal(formatDuration(30_000), 'under a minute');
    assert.equal(formatDuration(12 * 60_000), '12 min');
    assert.equal(formatDuration(65 * 60_000), '1 h 05 min');
    assert.equal(ago(8_000), '8 s ago');
    assert.equal(ago(3 * 60_000), '3 min ago');
    assert.equal(clockTime(new Date(2026, 9, 23, 16, 5).getTime()), '4:05 pm');
    assert.equal(clockTime(new Date(2026, 9, 23, 0, 30).getTime()), '12:30 am');
  });
});
