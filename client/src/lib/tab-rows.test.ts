import assert from 'node:assert/strict';
import { test } from 'node:test';

import { LABEL_ROOM, pillLeft, sectionTabLayout, tabRows } from './tab-rows';

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

test("the senior's four section tabs: one row while they fit, else two rows of two", () => {
  // Measured icon-and-word widths. A 375 px phone's bar is 359 px inside: four 89.75 px tabs.
  // At 100% "Calendar" (76 px) keeps 6 px a side: one row.
  assert.deepEqual(tabRows([51, 76, 66, 55], 359, LABEL_ROOM), { rows: 1, perRow: 4 });
  // At 125% (95 px) it would not: two rows of two, never three and one.
  assert.deepEqual(tabRows([64, 95, 83, 69], 359, LABEL_ROOM), { rows: 2, perRow: 2 });
  // A wide screen at 150% (1078 px inside), "Badges" with its count the widest: one row.
  assert.deepEqual(tabRows([154, 205, 230, 166], 1078, LABEL_ROOM), { rows: 1, perRow: 4 });
  // A tablet at 150% (658 px inside): two rows.
  assert.deepEqual(tabRows([142, 189, 216, 153], 658, LABEL_ROOM), { rows: 2, perRow: 2 });
});

const tab = (icon: number, label: number, extra = 0) => ({ icon, label, extra });

test('senior section bar on a phone: one row stacks the icon above the word', () => {
  // 375 px at 100%: "Calendar" (76 px) fits four to a row with its icon above it.
  const normal = [tab(18, 51), tab(18, 76), tab(18, 66, 22), tab(18, 55)];
  assert.deepEqual(sectionTabLayout(normal, 359, 8, true), { rows: 1, perRow: 4, look: 'stacked' });
});

test('senior section bar on a phone: two rows put the icon beside the word when it fits', () => {
  // 375 px at 125%: two rows either way; beside each word the rows are far shorter. The count
  // floats on the icon, so it takes no width.
  const large = [tab(28, 64), tab(28, 95), tab(28, 83, 27), tab(28, 69)];
  assert.deepEqual(sectionTabLayout(large, 359, 10, true), { rows: 2, perRow: 2, look: 'beside' });
  // 320 px at 100%: "Calendar" is 76 px in a 76 px tab, so two rows, icons beside.
  const small = [tab(22, 51), tab(22, 76), tab(22, 66, 22), tab(22, 55)];
  assert.deepEqual(sectionTabLayout(small, 304, 8, true), { rows: 2, perRow: 2, look: 'beside' });
});

test('senior section bar on a phone: words alone when even beside would need more rows', () => {
  // 320 px at 150%: beside, "Calendar" needs 33 + 12 + 115 = 160 px plus room in a 152 px tab;
  // the word alone (and "Badges" with its count after it) fits two to a row.
  const huge = [tab(33, 77), tab(33, 115), tab(33, 100, 32), tab(33, 83)];
  assert.deepEqual(sectionTabLayout(huge, 304, 12, true), { rows: 2, perRow: 2, look: 'words' });
  // The count keeps half a gap (6 px) from its word: 104 + 6 + 32 + 12 = 154 px is too wide for a
  // 152 px tab, though the word and count alone (148 px) would squeeze in.
  const tight = [tab(33, 77), tab(33, 115), tab(33, 104, 32), tab(33, 83)];
  assert.equal(sectionTabLayout(tight, 304, 12, true).look, 'stacked');
});

test('senior section bar on a phone: stacked when nothing else saves a row', () => {
  // A longer "Badges" (130 px) whose count would not fit beside it in a 152 px tab: two rows,
  // stacked, rather than four rows of words.
  const long = [tab(33, 77), tab(33, 115), tab(33, 130, 32), tab(33, 83)];
  assert.deepEqual(sectionTabLayout(long, 304, 12, true), { rows: 2, perRow: 2, look: 'stacked' });
});

test('senior section bar on a wide screen: always beside, the count in line after the word', () => {
  // 1280 px at 150%: one row.
  const wide = [tab(36, 106), tab(36, 157), tab(36, 135, 36), tab(36, 118)];
  assert.deepEqual(sectionTabLayout(wide, 1078, 12, false), { rows: 1, perRow: 4, look: 'beside' });
  // A tablet at 150%: two rows, still beside.
  assert.deepEqual(sectionTabLayout(wide, 658, 12, false), { rows: 2, perRow: 2, look: 'beside' });
});
