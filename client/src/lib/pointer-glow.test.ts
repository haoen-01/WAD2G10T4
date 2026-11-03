import assert from 'node:assert/strict';
import { test } from 'node:test';

import { GLOW_REACH, isNear, lean, localPoint } from './pointer-glow';

const box = { left: 100, top: 50, width: 200, height: 100 };

test('the point inside a panel is measured from its top-left corner', () => {
  assert.deepEqual(localPoint(box, 150, 75), { x: 50, y: 25 });
  assert.deepEqual(localPoint(box, 90, 40), { x: -10, y: -10 });
  assert.deepEqual(localPoint(box, 150.6, 75.4), { x: 51, y: 25 });
});

test('a panel lights when the mouse is on it or close to its edge', () => {
  assert.equal(isNear(box, 200, 100), true);
  assert.equal(isNear(box, 100 - GLOW_REACH, 100), true);
  assert.equal(isNear(box, 100 - GLOW_REACH - 1, 100), false);
  assert.equal(isNear(box, 200, 150 + 10, 10), true);
  assert.equal(isNear(box, 200, 150 + 11, 10), false);
  // Off a corner the distance is measured diagonally.
  assert.equal(isNear(box, 300 + 30, 150 + 40, 50), true);
  assert.equal(isNear(box, 300 + 40, 150 + 40, 50), false);
});

test('the lean runs from -1 at one edge to 1 at the other', () => {
  assert.equal(lean(0, 1000), -1);
  assert.equal(lean(500, 1000), 0);
  assert.equal(lean(1000, 1000), 1);
  assert.equal(lean(250, 1000), -0.5);
  assert.equal(lean(1200, 1000), 1);
  assert.equal(lean(-50, 1000), -1);
  assert.equal(lean(10, 0), 0);
});
