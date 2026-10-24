import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  DURATION,
  STAGGER,
  durationFor,
  enterFrom,
  shouldDismissSheet,
  staggerDelay,
} from './motion';

describe('staggerDelay', () => {
  it('starts at zero and steps up', () => {
    assert.equal(staggerDelay(0), 0);
    assert.equal(staggerDelay(1), STAGGER.step);
    assert.ok(staggerDelay(3) > staggerDelay(2));
  });

  it('never waits longer than the cap', () => {
    assert.equal(staggerDelay(500), STAGGER.max);
  });

  it('does not wait when motion is reduced or the index is odd', () => {
    assert.equal(staggerDelay(4, true), 0);
    assert.equal(staggerDelay(-2), 0);
    assert.equal(staggerDelay(Number.NaN), 0);
  });
});

describe('enterFrom', () => {
  it('rises and fades normally, only fades when reduced', () => {
    assert.deepEqual(enterFrom(false), { opacity: 0, y: 12 });
    assert.deepEqual(enterFrom(true), { opacity: 0, y: 0 });
  });
});

describe('durationFor', () => {
  it('is instant when reduced', () => {
    assert.equal(durationFor(DURATION.slow, true), 0);
    assert.equal(durationFor(DURATION.slow, false), DURATION.slow);
  });
});

describe('shouldDismissSheet', () => {
  it('closes past 30% of the height', () => {
    assert.equal(shouldDismissSheet(300, 0, 1000), true);
    assert.equal(shouldDismissSheet(299, 0, 1000), false);
  });

  it('closes on a quick downward flick, however short', () => {
    assert.equal(shouldDismissSheet(20, 500, 1000), true);
    assert.equal(shouldDismissSheet(20, 499, 1000), false);
  });

  it('never closes on an upward pull or an unmeasured sheet', () => {
    assert.equal(shouldDismissSheet(-400, 900, 1000), false);
    assert.equal(shouldDismissSheet(0, 900, 1000), false);
    assert.equal(shouldDismissSheet(400, 900, 0), false);
    assert.equal(shouldDismissSheet(Number.NaN, 900, 1000), false);
  });
});
