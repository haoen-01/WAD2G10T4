import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  greetingFor,
  minutesOf,
  nextTask,
  relativeDay,
  timeRange,
  untilWords,
  visitWhen,
} from './today';

describe('greetingFor', () => {
  it('changes at noon and at 6 pm', () => {
    assert.equal(greetingFor(7), 'Good morning');
    assert.equal(greetingFor(12), 'Good afternoon');
    assert.equal(greetingFor(18), 'Good evening');
  });
});

describe('relativeDay', () => {
  it('names the nearest days and counts the rest', () => {
    assert.equal(relativeDay('2026-10-10', '2026-10-10'), 'Today');
    assert.equal(relativeDay('2026-10-11', '2026-10-10'), 'Tomorrow');
    assert.equal(relativeDay('2026-10-09', '2026-10-10'), 'Yesterday');
    assert.equal(relativeDay('2026-10-14', '2026-10-10'), 'In 4 days');
    assert.equal(relativeDay('2026-10-07', '2026-10-10'), '3 days ago');
  });

  it('counts across a month end', () => {
    assert.equal(relativeDay('2026-11-02', '2026-10-30'), 'In 3 days');
  });
});

describe('timeRange', () => {
  it('shows the start and the end', () => {
    assert.equal(timeRange('10:00', '11:30'), '10:00 am – 11:30 am');
    assert.equal(timeRange('11:30', '13:00'), '11:30 am – 1:00 pm');
  });

  it('shows only the start when there is no later end', () => {
    assert.equal(timeRange('10:00', ''), '10:00 am');
    assert.equal(timeRange('10:00', null), '10:00 am');
    assert.equal(timeRange('10:00', '10:00'), '10:00 am');
  });
});

describe('visitWhen', () => {
  it('names the actual day, never "In 7 days"', () => {
    assert.equal(visitWhen('2026-10-23', '10:00', '11:00'), 'Fri, 23 Oct, 10:00 am – 11:00 am');
  });
});

describe('minutesOf', () => {
  it('reads the local clock', () => {
    assert.equal(minutesOf(new Date(2026, 9, 10, 14, 5)), 845);
  });
});

describe('untilWords', () => {
  it('reads naturally', () => {
    assert.equal(untilWords(0), 'now');
    assert.equal(untilWords(1), 'in 1 minute');
    assert.equal(untilWords(25), 'in 25 minutes');
    assert.equal(untilWords(60), 'in 1 hour');
    assert.equal(untilWords(95), 'in 1 hour 35 minutes');
    assert.equal(untilWords(150), 'in about 3 hours');
    assert.equal(untilWords(358), 'in about 6 hours');
  });
});

describe('nextTask', () => {
  const tasks = [
    { id: 'a', time: '08:00' },
    { id: 'b', time: '10:00' },
    { id: 'c', time: '17:00' },
  ];

  it('picks the earliest unfinished task still to come', () => {
    assert.deepEqual(nextTask(tasks, 9 * 60, new Set()), { task: tasks[1], overdue: false });
  });

  it('falls back to something overdue once the day has passed', () => {
    assert.deepEqual(nextTask(tasks, 20 * 60, new Set(['b', 'c'])), {
      task: tasks[0],
      overdue: true,
    });
  });

  it('has nothing to say when everything is done', () => {
    assert.equal(nextTask(tasks, 9 * 60, new Set(['a', 'b', 'c'])), null);
  });
});
