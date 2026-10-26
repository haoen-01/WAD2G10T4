import assert from 'node:assert/strict';
import test from 'node:test';
import { upcomingEvents } from '../components/senior/upcoming.js';
const event = (id, date, start = '10:00') => ({
  id,
  date,
  start,
  end: '11:00',
  title: id,
  kind: 'activity',
});
test('upcoming shows the next three events in time order without mutating calendar data', () => {
  const items = [
    event('fourth', '2026-10-28'),
    event('second', '2026-10-26'),
    event('first', '2026-10-25', '15:00'),
    event('third', '2026-10-27'),
  ];
  assert.deepEqual(
    upcomingEvents(items, '2026-10-25', '14:00').map((item) => item.id),
    ['first', 'second', 'third'],
  );
  assert.equal(items[0].id, 'fourth');
});
test('upcoming excludes past days, elapsed start times, and events beyond this week', () => {
  const items = [
    event('past', '2026-10-24'),
    event('earlier', '2026-10-25', '09:00'),
    event('next-week', '2026-11-01'),
    event('last-day', '2026-10-31'),
    event('now', '2026-10-25', '14:00'),
  ];
  assert.deepEqual(
    upcomingEvents(items, '2026-10-25', '14:00').map((item) => item.id),
    ['now', 'last-day'],
  );
});
test('upcoming returns an empty list when nothing is planned', () => {
  assert.deepEqual(upcomingEvents([], '2026-10-25', '14:00'), []);
});
