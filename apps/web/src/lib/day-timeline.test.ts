import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  clockToMinutes,
  dayRecord,
  daySummary,
  dayWindow,
  focusAt,
  hasHappened,
  isUnderway,
  minutesToLabel,
  momentInZone,
  positionOf,
  sortMoments,
} from './day-timeline';
import type { TimelineMoment } from './day-timeline';

const moment = (over: Partial<TimelineMoment>): TimelineMoment => ({
  id: 'm',
  lane: 'task',
  start: 9 * 60,
  title: 'Task',
  detail: '',
  icon: 'check',
  ...over,
});

const doctor = moment({
  id: 'a',
  lane: 'appointment',
  start: 10 * 60,
  end: 12 * 60,
  title: 'Doctor',
});
const tablet = moment({ id: 't', lane: 'task', start: 8 * 60, title: 'Tablet', done: true });
const walk = moment({ id: 'w', lane: 'task', start: 17 * 60, title: 'Walk', done: false });
const call = moment({ id: 'f', lane: 'family', start: 15 * 60 + 30, title: 'Sarah called' });
const day = [call, doctor, walk, tablet];

describe('clock times', () => {
  it('reads HH:MM as minutes and back', () => {
    assert.equal(clockToMinutes('09:30'), 570);
    assert.equal(clockToMinutes('9:30'), null);
    assert.equal(clockToMinutes('25:00'), null);
    assert.equal(minutesToLabel(570), '9:30 am');
    assert.equal(minutesToLabel(0), '12:00 am');
    assert.equal(minutesToLabel(12 * 60 + 5), '12:05 pm');
    assert.equal(minutesToLabel(-20), '12:00 am');
  });
});

describe('a family update in Singapore time', () => {
  it('lands on the Singapore day and minute', () => {
    // 23:30 UTC on the 19th is 07:30 on the 20th in Singapore (UTC+8).
    assert.deepEqual(momentInZone('2026-10-19T23:30:00Z', 'Asia/Singapore'), {
      day: '2026-10-20',
      minute: 7 * 60 + 30,
    });
  });

  it('gives null for an unreadable timestamp', () => {
    assert.equal(momentInZone('not a time', 'Asia/Singapore'), null);
  });
});

describe('the timeline', () => {
  it('sorts by time', () => {
    assert.deepEqual(
      sortMoments(day).map((m) => m.id),
      ['t', 'a', 'f', 'w'],
    );
  });

  it('draws 7 am to 10 pm, widened for anything outside', () => {
    assert.deepEqual(dayWindow(day), { from: 420, to: 1320 });
    const late = moment({ start: 22 * 60 + 15 });
    const early = moment({ start: 6 * 60 + 40 });
    assert.deepEqual(dayWindow([late, early]), { from: 360, to: 1380 });
  });

  it('places a minute along the window', () => {
    const window = { from: 420, to: 1320 };
    assert.equal(positionOf(420, window), 0);
    assert.equal(positionOf(870, window), 0.5);
    assert.equal(positionOf(2000, window), 1);
  });
});

describe('now', () => {
  it('knows what has passed and what is under way', () => {
    assert.equal(hasHappened(doctor, 10 * 60), true);
    assert.equal(hasHappened(doctor, 9 * 60 + 59), false);
    assert.equal(isUnderway(doctor, 11 * 60), true);
    assert.equal(isUnderway(doctor, 12 * 60), false);
    assert.equal(isUnderway(tablet, 8 * 60), false);
  });

  it('describes an appointment under way, else what is next, else the latest', () => {
    assert.equal(focusAt(day, 11 * 60)?.id, 'a');
    assert.equal(focusAt(day, 9 * 60)?.id, 'a');
    assert.equal(focusAt(day, 16 * 60)?.id, 'w');
    assert.equal(focusAt(day, 20 * 60)?.id, 'w');
    assert.equal(focusAt([], 12 * 60), null);
  });
});

describe('the day in numbers and as a record', () => {
  it('counts appointments, tasks done and family updates', () => {
    assert.deepEqual(daySummary(day), { appointments: 1, tasks: 2, tasksDone: 1, family: 1 });
  });

  it('splits an earlier day into done, not done, appointments and family', () => {
    const record = dayRecord(day);
    assert.deepEqual(
      record.done.map((m) => m.id),
      ['t'],
    );
    assert.deepEqual(
      record.missed.map((m) => m.id),
      ['w'],
    );
    assert.deepEqual(
      record.appointments.map((m) => m.id),
      ['a'],
    );
    assert.deepEqual(
      record.family.map((m) => m.id),
      ['f'],
    );
  });
});
