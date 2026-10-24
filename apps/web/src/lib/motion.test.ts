import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { DURATION, STAGGER, durationFor, enterFrom, staggerDelay } from './motion';

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
