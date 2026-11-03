import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  advanceSim,
  DEMO_ROUTE,
  FIX_EVERY_MS,
  parseGpx,
  routeFromTrack,
  simPosition,
  startSim,
  WALK_SPEED_MPS,
} from './demo-walk';
import { distanceM, pathLengthM } from './geo';
import { walkedDistanceM, walkState } from './walk';

const T0 = new Date(2026, 9, 23, 15, 0).getTime();
const MIN = 60_000;

describe('the demo route', () => {
  it('is a loop of about 2.4 km that starts and ends at home', () => {
    const length = pathLengthM(DEMO_ROUTE.path);
    assert.ok(length > 2200 && length < 3000, `length ${length}`);
    assert.deepEqual(DEMO_ROUTE.path[0], DEMO_ROUTE.path[DEMO_ROUTE.path.length - 1]);
    assert.deepEqual(DEMO_ROUTE.path[0], [DEMO_ROUTE.home.lng, DEMO_ROUTE.home.lat]);
  });
});

describe('advanceSim', () => {
  it('sends a reading every 5 seconds and moves her at an older walker’s pace', () => {
    const { state, fixes } = advanceSim(startSim(T0), DEMO_ROUTE, 2 * MIN);
    assert.equal(fixes.length, (2 * MIN) / FIX_EVERY_MS + 1);
    assert.ok(Math.abs(state.progressM - 2 * 60 * WALK_SPEED_MPS) < 0.01);
    assert.equal(state.clock, T0 + 2 * MIN);
    // The wobble keeps every reading within a few metres of the path.
    for (const fix of fixes) assert.ok(fix.accuracyM >= 5 && fix.accuracyM <= 12);
  });

  it('gives the same walk for the same steps, however they are split', () => {
    const once = advanceSim(startSim(T0), DEMO_ROUTE, 10 * MIN);
    let state = startSim(T0);
    const parts = [];
    for (let i = 0; i < 10; i += 1) {
      const step = advanceSim(state, DEMO_ROUTE, MIN);
      state = step.state;
      parts.push(...step.fixes);
    }
    assert.deepEqual(parts, once.fixes);
  });

  it('rests on the way, then walks home and finishes', () => {
    const { state, fixes } = advanceSim(startSim(T0), DEMO_ROUTE, 90 * MIN);
    assert.ok(state.finished);
    assert.equal(walkState(fixes, state.clock, DEMO_ROUTE.home), 'home');
    const walked = walkedDistanceM(fixes);
    // GPS wobble adds a little, as it does on a real watch; within 12% of the true length.
    assert.ok(Math.abs(walked / pathLengthM(DEMO_ROUTE.path) - 1) < 0.12, `walked ${walked}`);
  });

  it('keeps her in one place while "stay still" is on, however much time passes', () => {
    const out = advanceSim(startSim(T0), DEMO_ROUTE, 10 * MIN).state;
    const before = simPosition(out, DEMO_ROUTE);
    const { state, fixes } = advanceSim({ ...out, stayStill: true }, DEMO_ROUTE, 60 * MIN);
    assert.ok(distanceM(simPosition(state, DEMO_ROUTE), before) < 0.01);
    for (const fix of fixes) assert.equal(fix.heading, null);
  });

  it('sends nothing while the signal is lost, but keeps time', () => {
    const { state, fixes } = advanceSim({ ...startSim(T0), signalLost: true }, DEMO_ROUTE, 5 * MIN);
    assert.equal(fixes.length, 0);
    assert.equal(state.clock, T0 + 5 * MIN);
  });
});

describe('parseGpx', () => {
  const gpx = `<?xml version="1.0"?><gpx><trk><trkseg>
    <trkpt lat="1.3630" lon="103.8400"><ele>20</ele></trkpt>
    <trkpt lon="103.8410" lat="1.3635"></trkpt>
    <trkpt lat='1.3640' lon='103.8420'/>
  </trkseg></trk></gpx>`;

  it('reads track points in either attribute order, as [longitude, latitude]', () => {
    assert.deepEqual(parseGpx(gpx), [
      [103.84, 1.363],
      [103.841, 1.3635],
      [103.842, 1.364],
    ]);
  });

  it('thins long tracks and keeps the last point', () => {
    const many = Array.from(
      { length: 5000 },
      (_, i) => `<trkpt lat="1.36" lon="${103.8 + i / 1e5}"/>`,
    );
    const points = parseGpx(`<gpx>${many.join('')}</gpx>`, 100);
    assert.equal(points.length, 100);
    assert.deepEqual(points[99], [103.8 + 4999 / 1e5, 1.36]);
  });

  it('refuses a file with no track, in plain words', () => {
    assert.throws(() => parseGpx('<gpx></gpx>'), /no walk in it/);
  });

  it('makes a route that starts at home', () => {
    const route = routeFromTrack(parseGpx(gpx), 'My walk');
    assert.equal(route.home.lng, 103.84);
    assert.equal(route.rests.length, 0);
  });
});
