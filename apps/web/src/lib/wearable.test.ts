import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { batteryLevel, describeBattery, syncedAgo } from './wearable';

describe('batteryLevel', () => {
  it('uses the usual phone bands: green from 50%, amber from 20%, red below', () => {
    assert.equal(batteryLevel(100, false), 'good');
    assert.equal(batteryLevel(50, false), 'good');
    assert.equal(batteryLevel(49, false), 'low');
    assert.equal(batteryLevel(20, false), 'low');
    assert.equal(batteryLevel(19, false), 'critical');
    assert.equal(batteryLevel(3, false), 'critical');
  });

  it('says charging whatever the level, so nobody is asked to charge a watch that is charging', () => {
    assert.equal(batteryLevel(10, true), 'charging');
  });
});

describe('describeBattery', () => {
  it('always says the level in words, not only in colour', () => {
    assert.equal(describeBattery(72, false), '72%');
    assert.equal(describeBattery(35, false), '35%, getting low');
    assert.equal(describeBattery(12, false), '12%, needs charging');
    assert.equal(describeBattery(40, true), '40%, charging');
  });
});

describe('syncedAgo', () => {
  const now = new Date('2026-10-14T10:00:00Z');
  it('reads like a person would say it', () => {
    assert.equal(syncedAgo('2026-10-14T10:00:00Z', now), 'synced just now');
    assert.equal(syncedAgo('2026-10-14T09:48:00Z', now), 'synced 12 min ago');
    assert.equal(syncedAgo('2026-10-14T07:00:00Z', now), 'synced 3 h ago');
    assert.equal(syncedAgo('2026-10-14T10:05:00Z', now), 'synced just now');
  });
});
