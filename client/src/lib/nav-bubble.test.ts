import assert from 'node:assert/strict';
import { test } from 'node:test';

import { sameSpan, stretchSpan } from './nav-bubble';

test('moving right, the bubble stretches from the old link to the end of the new one', () => {
  assert.deepEqual(stretchSpan({ x: 4, w: 90 }, { x: 200, w: 110 }), { x: 4, w: 306 });
});

test('moving left, it stretches from the start of the new link to the end of the old one', () => {
  assert.deepEqual(stretchSpan({ x: 200, w: 110 }, { x: 4, w: 90 }), { x: 4, w: 306 });
});

test('next-door links that overlap still give one covering span', () => {
  assert.deepEqual(stretchSpan({ x: 10, w: 100 }, { x: 60, w: 30 }), { x: 10, w: 100 });
});

test('the same place, to the pixel, needs no stretch', () => {
  assert.equal(sameSpan({ x: 10.2, w: 99.8 }, { x: 10, w: 100 }), true);
  assert.equal(sameSpan({ x: 10, w: 100 }, { x: 12, w: 100 }), false);
});
