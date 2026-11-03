import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { offsetM, type LngLat } from './geo';
import {
  checkStillness,
  DEFAULT_STILLNESS,
  HOUR_MS,
  limitWords,
  MINUTE_MS,
  type StillnessInput,
  type UsualPlace,
} from './stillness';
import type { Place, WalkFix } from './walk';

const HOME_AT: LngLat = [103.8442, 1.3664];
const HOME: Place = { name: 'Home', lng: HOME_AT[0], lat: HOME_AT[1], radiusM: 60 };
const BENCH = offsetM(HOME_AT, -400, -300); // in the park, 500 m from home
const T0 = new Date(2026, 9, 23, 14, 0).getTime();

const fixAt = (at: number, point: LngLat): WalkFix => ({
  at,
  lng: point[0],
  lat: point[1],
  accuracyM: 6,
  heading: null,
});

/** She walks to `spot` (arriving at T0), then stays there for `minutes`, wobbling a few metres. */
function stayAt(spot: LngLat, minutes: number): WalkFix[] {
  const fixes: WalkFix[] = [];
  for (let s = 600; s > 0; s -= 30) fixes.push(fixAt(T0 - s * 1000, offsetM(spot, s * 3, 0)));
  for (let s = 0; s <= minutes * 60; s += 30) {
    fixes.push(fixAt(T0 + s * 1000, offsetM(spot, s % 60 ? 12 : -12, s % 90 ? 8 : -8)));
  }
  return fixes;
}

function input(fixes: WalkFix[], overrides: Partial<StillnessInput> = {}): StillnessInput {
  return {
    fixes,
    now: fixes[fixes.length - 1].at,
    home: HOME,
    usualPlaces: [],
    busy: [],
    settings: DEFAULT_STILLNESS,
    okAt: null,
    consentAt: null,
    askedAt: null,
    dismissed: null,
    ...overrides,
  };
}

/** The senior was asked "Are you OK?" 15 minutes before the last reading. */
const askedBeforeEnd = (fixes: WalkFix[]) => ({
  askedAt: fixes[fixes.length - 1].at - 15 * MINUTE_MS,
});

describe('checkStillness', () => {
  it('says nothing before any reading', () => {
    assert.deepEqual(checkStillness({ ...input(stayAt(BENCH, 1)), fixes: [] }), { kind: 'none' });
  });

  it('is quiet under the limit, asks the senior first, then alerts at 2 hours', () => {
    const quiet = checkStillness(input(stayAt(BENCH, 60)));
    assert.equal(quiet.kind === 'still' && quiet.phase, 'quiet');
    assert.equal(quiet.kind === 'still' && quiet.since, T0);

    const soon = checkStillness(input(stayAt(BENCH, 106)));
    assert.equal(soon.kind === 'still' && soon.phase, 'soon');

    const at120 = stayAt(BENCH, 120);
    const alert = checkStillness(input(at120, askedBeforeEnd(at120)));
    assert.equal(alert.kind === 'still' && alert.phase, 'alert');
    assert.equal(alert.kind === 'still' && alert.alertAt, T0 + 2 * HOUR_MS);
  });

  it('does not let GPS wobble of a few metres restart the clock', () => {
    const result = checkStillness(input(stayAt(BENCH, 90)));
    assert.equal(result.kind === 'still' && result.forMs, 90 * MINUTE_MS);
  });

  it('never alerts at home, however long', () => {
    const result = checkStillness(input(stayAt(HOME_AT, 300)));
    assert.equal(result.kind === 'still' && result.phase, 'quiet');
    assert.equal(result.kind === 'still' && result.quietBecause, 'home');
    assert.equal(result.kind === 'still' && result.alertAt, null);
  });

  it('never counts a lost signal as staying still', () => {
    const fixes = stayAt(BENCH, 150);
    const result = checkStillness({ ...input(fixes), now: fixes[fixes.length - 1].at + 61_000 });
    assert.deepEqual(result, { kind: 'no_signal' });
  });

  it('does not alert at a usual place that never alerts, and adds time at one that does', () => {
    const centre: UsualPlace = {
      name: 'Active Ageing Centre',
      lng: BENCH[0],
      lat: BENCH[1],
      radiusM: 80,
      extraMs: null,
    };
    const never = checkStillness(input(stayAt(BENCH, 200), { usualPlaces: [centre] }));
    assert.equal(never.kind === 'still' && never.quietBecause, 'usual_place');
    assert.equal(never.kind === 'still' && never.quietLabel, 'Active Ageing Centre');

    const longer = { ...centre, name: 'the market', extraMs: HOUR_MS };
    const at150 = checkStillness(input(stayAt(BENCH, 150), { usualPlaces: [longer] }));
    assert.equal(at150.kind === 'still' && at150.phase, 'quiet');
    const stay180 = stayAt(BENCH, 180);
    const at180 = checkStillness(
      input(stay180, { usualPlaces: [longer], ...askedBeforeEnd(stay180) }),
    );
    assert.equal(at180.kind === 'still' && at180.phase, 'alert');
  });

  it('does not alert during a calendar appointment (with half an hour either side)', () => {
    const fixes = stayAt(BENCH, 150);
    const now = fixes[fixes.length - 1].at;
    const busy = [
      { title: 'Doctor’s appointment', startMs: now - HOUR_MS, endMs: now - 10 * MINUTE_MS },
    ];
    const result = checkStillness(input(fixes, { busy }));
    assert.equal(result.kind === 'still' && result.quietBecause, 'appointment');
    assert.equal(result.kind === 'still' && result.quietLabel, 'Doctor’s appointment');

    const over = [{ ...busy[0], endMs: now - 45 * MINUTE_MS }];
    const after = checkStillness(input(fixes, { busy: over, ...askedBeforeEnd(fixes) }));
    assert.equal(after.kind === 'still' && after.phase, 'alert');
  });

  it('restarts the clock when the senior presses "I\'m OK"', () => {
    const fixes = stayAt(BENCH, 150);
    const okAt = T0 + 110 * MINUTE_MS;
    const result = checkStillness(input(fixes, { okAt }));
    assert.equal(result.kind === 'still' && result.since, okAt);
    assert.equal(result.kind === 'still' && result.phase, 'quiet');
    assert.equal(result.kind === 'still' && result.alertAt, okAt + 2 * HOUR_MS);
  });

  it('stays quiet for a stop the family marked "She\'s fine", but alerts for the next stop', () => {
    const fixes = stayAt(BENCH, 150);
    const at = fixes[fixes.length - 1].at;
    const dismissed = { lng: BENCH[0], lat: BENCH[1], at };
    const fine = checkStillness(input(fixes, { dismissed }));
    assert.equal(fine.kind === 'still' && fine.quietBecause, 'dismissed');

    const elsewhere = offsetM(BENCH, 300, 0);
    const next = [...fixes];
    for (let s = 30; s <= 125 * 60; s += 30) next.push(fixAt(at + s * 1000, elsewhere));
    const second = checkStillness(input(next, { dismissed, ...askedBeforeEnd(next) }));
    assert.equal(second.kind === 'still' && second.phase, 'alert');
  });

  it('keeps the same stop start when one wobbly reading lands near the edge', () => {
    const fixes = stayAt(BENCH, 60);
    const before = checkStillness(input(fixes));
    const wobble = fixAt(fixes[fixes.length - 1].at + 5000, offsetM(BENCH, 35, 0));
    const after = checkStillness(input([...fixes, wobble]));
    assert.equal(before.kind === 'still' && after.kind === 'still', true);
    assert.equal(
      before.kind === 'still' && before.stopStart,
      after.kind === 'still' && after.stopStart,
    );
  });

  it('always asks the senior first: no alert until she has been asked for 15 minutes', () => {
    const fixes = stayAt(BENCH, 150);
    const never = checkStillness(input(fixes));
    assert.equal(never.kind === 'still' && never.phase, 'soon');
    const now = fixes[fixes.length - 1].at;
    const justAsked = checkStillness(input(fixes, { askedAt: now - 5 * MINUTE_MS }));
    assert.equal(justAsked.kind === 'still' && justAsked.phase, 'soon');
    assert.equal(justAsked.kind === 'still' && justAsked.alertAt, now + 10 * MINUTE_MS);
  });

  it('does not count time without signal: the stop starts again after a gap', () => {
    const fixes: WalkFix[] = [];
    for (let s = 0; s <= 600; s += 30) fixes.push(fixAt(T0 + s * 1000, BENCH));
    const back = T0 + 120 * MINUTE_MS;
    fixes.push(fixAt(back, BENCH));
    const result = checkStillness(input(fixes, { askedAt: back - 30 * MINUTE_MS }));
    assert.equal(result.kind === 'still' && result.since, back);
    assert.equal(result.kind === 'still' && result.phase, 'quiet');
  });

  it('starts the clock no earlier than when the senior turned the check-in on', () => {
    const fixes = stayAt(BENCH, 150);
    const consentAt = fixes[fixes.length - 1].at - 10 * MINUTE_MS;
    const result = checkStillness(input(fixes, { consentAt, ...askedBeforeEnd(fixes) }));
    assert.equal(result.kind === 'still' && result.since, consentAt);
    assert.equal(result.kind === 'still' && result.phase, 'quiet');
  });

  it("follows the family's chosen limit", () => {
    const settings = { ...DEFAULT_STILLNESS, limitMs: 30 * MINUTE_MS };
    const stay = stayAt(BENCH, 31);
    const result = checkStillness(input(stay, { settings, ...askedBeforeEnd(stay) }));
    assert.equal(result.kind === 'still' && result.phase, 'alert');
  });
});

describe('limitWords', () => {
  it('says the limit in words', () => {
    assert.equal(limitWords(2 * HOUR_MS), '2 hours');
    assert.equal(limitWords(HOUR_MS), '1 hour');
    assert.equal(limitWords(90 * MINUTE_MS), '1 hour 30 minutes');
    assert.equal(limitWords(30 * MINUTE_MS), '30 minutes');
  });
});
