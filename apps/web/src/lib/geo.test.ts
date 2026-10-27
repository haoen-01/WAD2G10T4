import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { bearingDeg, circleRing, distanceM, offsetM, pathLengthM, pointAlong } from './geo';
import type { LngLat } from './geo';

const PARK: LngLat = [103.8436, 1.363];

describe('distanceM', () => {
  it('measures a known distance: one thousandth of a degree of latitude is about 111 m', () => {
    const north: LngLat = [PARK[0], PARK[1] + 0.001];
    assert.ok(Math.abs(distanceM(PARK, north) - 111.2) < 0.5);
  });

  it('is zero for the same point', () => {
    assert.equal(distanceM(PARK, PARK), 0);
  });
});

describe('bearingDeg', () => {
  it('gives compass directions', () => {
    assert.ok(Math.abs(bearingDeg(PARK, [PARK[0], PARK[1] + 0.01]) - 0) < 0.01);
    assert.ok(Math.abs(bearingDeg(PARK, [PARK[0] + 0.01, PARK[1]]) - 90) < 0.1);
    assert.ok(Math.abs(bearingDeg(PARK, [PARK[0] - 0.01, PARK[1]]) - 270) < 0.1);
  });
});

describe('offsetM and pointAlong', () => {
  it('moves a point by metres east and north', () => {
    const moved = offsetM(PARK, 30, 40);
    assert.ok(Math.abs(distanceM(PARK, moved) - 50) < 0.1);
  });

  it('finds the point a given distance along a path, and stops at its ends', () => {
    const end = offsetM(PARK, 0, 200);
    const path: LngLat[] = [PARK, end];
    assert.ok(Math.abs(pathLengthM(path) - 200) < 0.1);
    const half = pointAlong(path, 100);
    assert.ok(Math.abs(distanceM(PARK, half.point) - 100) < 0.1);
    assert.ok(half.bearing < 0.01 || half.bearing > 359.99);
    assert.deepEqual(pointAlong(path, -5).point, PARK);
    assert.ok(distanceM(pointAlong(path, 999).point, end) < 0.01);
  });
});

describe('circleRing', () => {
  it('draws a closed ring at the given radius', () => {
    const ring = circleRing(PARK, 12, 16);
    assert.equal(ring.length, 17);
    assert.deepEqual(ring[0], ring[16]);
    for (const point of ring) assert.ok(Math.abs(distanceM(PARK, point) - 12) < 0.05);
  });
});
