import assert from 'node:assert/strict';
import { test } from 'node:test';

import { LABEL_ROOM, pillLeft, tabRows } from './tab-rows';

test('one row when every label fits its share of the bar', () => {
  assert.deepEqual(tabRows([40, 46, 38, 62, 48], 375, 8), { rows: 1, perRow: 5 });
});

test('a second row, not smaller words, when the widest label would not fit', () => {
  // Five tabs at 320 px are 64 px each; a 85 px label needs three to a row.
  assert.deepEqual(tabRows([50, 60, 48, 85, 64], 320, 8), { rows: 2, perRow: 3 });
  // Six tabs split evenly, three and three.
  assert.deepEqual(tabRows([50, 60, 60, 48, 85, 64], 320, 8), { rows: 2, perRow: 3 });
});

test('more rows only when two are still too narrow', () => {
  assert.deepEqual(tabRows([150, 60, 60, 48, 85, 64], 320, 8), { rows: 3, perRow: 2 });
  assert.deepEqual(tabRows([400, 60], 320, 8), { rows: 2, perRow: 1 });
});

test('nothing to measure yet: one row', () => {
  assert.deepEqual(tabRows([], 375, 8), { rows: 1, perRow: 1 });
  assert.deepEqual(tabRows([40, 40], 0, 8), { rows: 1, perRow: 2 });
});

test('labels keep 6 px clear on each side: "Calendar" at 125% on a 375 px phone takes two rows', () => {
  // Five 75 px tabs; a 66 px "Calendar" would come within 9 px of its tab's edges: three to a row.
  assert.deepEqual(tabRows([44, 45, 36, 66, 48], 375, LABEL_ROOM), { rows: 2, perRow: 3 });
  // At 100% (a 53 px "Calendar") one row still fits, five or six tabs to a 390 px phone.
  assert.deepEqual(tabRows([35, 36, 29, 53, 39], 375, LABEL_ROOM), { rows: 1, perRow: 5 });
  assert.deepEqual(tabRows([35, 42, 36, 29, 53, 39], 390, LABEL_ROOM), { rows: 1, perRow: 6 });
});

test('the highlight pill is centred on its tab but never leaves the bar', () => {
  assert.equal(pillLeft(100, 100, 64, 500), 118);
  // A 75 px end tab under an 80 px pill: held at the edges, not at -2.5 or 377.5.
  assert.equal(pillLeft(0, 75, 80, 375), 0);
  assert.equal(pillLeft(300, 75, 80, 375), 295);
  // A bar narrower than the pill: from the left edge.
  assert.equal(pillLeft(0, 40, 80, 40), 0);
});
