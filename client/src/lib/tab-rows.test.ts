import assert from 'node:assert/strict';
import { test } from 'node:test';

import { tabRows } from './tab-rows';

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
