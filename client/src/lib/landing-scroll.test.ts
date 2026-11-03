import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { clamp01, countUp, holdThenMove, sectionProgress, shotNumber } from './landing-scroll';

describe('progress through a pinned section', () => {
  it('runs from 0 at the pin line to 1 when the stage is about to leave', () => {
    // A 3000px section with an 800px stage, pinned 64px from the top of the window.
    assert.equal(sectionProgress(64, 3000, 800, 64), 0);
    assert.equal(sectionProgress(64 - 1100, 3000, 800, 64), 0.5);
    assert.equal(sectionProgress(64 - 2200, 3000, 800, 64), 1);
    assert.equal(sectionProgress(500, 3000, 800, 64), 0);
    assert.equal(sectionProgress(-9000, 3000, 800, 64), 1);
  });

  it('copes with a section no taller than its stage', () => {
    assert.equal(sectionProgress(10, 800, 800, 0), 0);
    assert.equal(sectionProgress(-10, 800, 800, 0), 1);
  });
});

describe('the app tour', () => {
  it('rests on each screen, then glides to the next', () => {
    // Six screens: five gaps. The first half of each gap holds still.
    assert.equal(holdThenMove(0, 6), 0);
    assert.equal(holdThenMove(0.08, 6), 0);
    assert.ok(holdThenMove(0.15, 6) > 0 && holdThenMove(0.15, 6) < 0.2);
    assert.equal(holdThenMove(0.2, 6), 0.2);
    assert.equal(holdThenMove(1, 6), 1);
    assert.equal(holdThenMove(0.5, 1), 0);
  });

  it('names the screen in the middle', () => {
    assert.equal(shotNumber(0, 6), 1);
    assert.equal(shotNumber(0.2, 6), 2);
    assert.equal(shotNumber(1, 6), 6);
  });
});

describe('small helpers', () => {
  it('clamps and counts up', () => {
    assert.equal(clamp01(-1), 0);
    assert.equal(clamp01(2), 1);
    assert.equal(clamp01(Number.NaN), 0);
    assert.equal(countUp(0, 4980, 5720), 4980);
    assert.equal(countUp(0.5, 4980, 5720), 5350);
    assert.equal(countUp(1.4, 4980, 5720), 5720);
  });
});
