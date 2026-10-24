import assert from 'node:assert/strict';
import test from 'node:test';

import { weekOf } from './week';

test('a week runs Sunday to Saturday and contains the day', () => {
  // 2026-10-24 is a Saturday.
  const week = weekOf('2026-10-24');
  assert.equal(week.length, 7);
  assert.equal(week[0], '2026-10-18');
  assert.equal(week[6], '2026-10-24');
  assert.ok(week.includes('2026-10-24'));
});

test('a Sunday starts its own week', () => {
  assert.equal(weekOf('2026-10-25')[0], '2026-10-25');
});

test('a week can cross a month and a year', () => {
  assert.deepEqual(weekOf('2026-12-31'), [
    '2026-12-27',
    '2026-12-28',
    '2026-12-29',
    '2026-12-30',
    '2026-12-31',
    '2027-01-01',
    '2027-01-02',
  ]);
});

test('an unreadable day gives no week', () => {
  assert.deepEqual(weekOf('not a day'), []);
});
