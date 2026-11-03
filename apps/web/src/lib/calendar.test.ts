import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  addDays,
  opensAddForm,
  dayClick,
  monthGrid,
  monthOf,
  shiftMonth,
  spansOverlap,
  timeToMinutes,
  todayIso,
  toIsoDay,
} from './calendar';

describe('days', () => {
  it('writes a day as YYYY-MM-DD with the zeros in place', () => {
    assert.equal(toIsoDay(2026, 9, 5), '2026-09-05');
    assert.equal(toIsoDay(987, 1, 1), '0987-01-01');
  });

  it('reads today from the machine calendar, not from UTC', () => {
    // A local-time constructor: 23:30 on the 30th is still the 30th here, whatever UTC says.
    assert.equal(todayIso(new Date(2026, 8, 30, 23, 30)), '2026-09-30');
    assert.equal(todayIso(new Date(2026, 0, 1, 0, 5)), '2026-01-01');
  });

  it('adds days across months, years and leap days', () => {
    assert.equal(addDays('2026-09-21', 1), '2026-09-22');
    assert.equal(addDays('2026-09-30', 1), '2026-10-01');
    assert.equal(addDays('2026-12-31', 1), '2027-01-01');
    assert.equal(addDays('2028-02-28', 1), '2028-02-29');
    assert.equal(addDays('2027-02-28', 1), '2027-03-01');
    assert.equal(addDays('2026-03-01', -1), '2026-02-28');
    assert.equal(addDays('2026-09-21', 0), '2026-09-21');
  });

  it('leaves a day it cannot read as it was, rather than inventing one', () => {
    assert.equal(addDays('soon', 3), 'soon');
  });
});

describe('months', () => {
  it('finds the month a day is in', () => {
    assert.deepEqual(monthOf('2026-09-21'), { year: 2026, month: 9 });
  });

  it('moves between months, including across a year in either direction', () => {
    assert.deepEqual(shiftMonth({ year: 2026, month: 9 }, 1), { year: 2026, month: 10 });
    assert.deepEqual(shiftMonth({ year: 2026, month: 12 }, 1), { year: 2027, month: 1 });
    assert.deepEqual(shiftMonth({ year: 2026, month: 1 }, -1), { year: 2025, month: 12 });
    assert.deepEqual(shiftMonth({ year: 2026, month: 1 }, -13), { year: 2024, month: 12 });
    assert.deepEqual(shiftMonth({ year: 2026, month: 5 }, 0), { year: 2026, month: 5 });
  });
});

describe('monthGrid', () => {
  it('lays September 2026 out Sunday first, filled with the days either side', () => {
    const weeks = monthGrid({ year: 2026, month: 9 });
    assert.equal(weeks.length, 5);
    assert.ok(weeks.every((week) => week.length === 7));
    // 1 September 2026 is a Tuesday, so the first row starts on Sunday 30 August.
    assert.deepEqual(weeks[0][0], { iso: '2026-08-30', day: 30, inMonth: false });
    assert.deepEqual(weeks[0][2], { iso: '2026-09-01', day: 1, inMonth: true });
    assert.deepEqual(weeks[4][6], { iso: '2026-10-03', day: 3, inMonth: false });
  });

  it('needs only four rows when the month fits exactly (February 2026)', () => {
    const weeks = monthGrid({ year: 2026, month: 2 });
    assert.equal(weeks.length, 4);
    assert.ok(weeks.flat().every((cell) => cell.inMonth));
  });

  it('needs six rows when a long month starts late in the week (August 2026)', () => {
    const weeks = monthGrid({ year: 2026, month: 8 });
    assert.equal(weeks.length, 6);
    assert.equal(weeks[0][0].iso, '2026-07-26');
    assert.equal(weeks[5][6].iso, '2026-09-05');
  });

  it('counts each day of the month exactly once', () => {
    const inMonth = monthGrid({ year: 2028, month: 2 })
      .flat()
      .filter((cell) => cell.inMonth);
    assert.deepEqual(
      inMonth.map((cell) => cell.day),
      Array.from({ length: 29 }, (_, index) => index + 1),
    );
  });
});

describe('clock times', () => {
  it('reads HH:MM as minutes after midnight', () => {
    assert.equal(timeToMinutes('00:00'), 0);
    assert.equal(timeToMinutes('09:30'), 570);
    assert.equal(timeToMinutes('23:59'), 1439);
  });

  it('says whether two spans share time, and not when they only touch', () => {
    const morning = { start: '09:00', end: '11:00' };
    assert.equal(spansOverlap(morning, { start: '10:00', end: '12:00' }), true);
    assert.equal(spansOverlap(morning, { start: '09:30', end: '10:00' }), true);
    assert.equal(spansOverlap({ start: '10:00', end: '12:00' }, morning), true);
    assert.equal(spansOverlap(morning, { start: '11:00', end: '12:00' }), false);
    assert.equal(spansOverlap(morning, { start: '07:00', end: '09:00' }), false);
    assert.equal(spansOverlap(morning, { start: '13:00', end: '14:00' }), false);
  });
});

describe('opensAddForm', () => {
  it('opens the add form on an empty day from today on', () => {
    assert.equal(opensAddForm('2026-11-02', '2026-11-02', true, 0), true);
    assert.equal(opensAddForm('2026-11-20', '2026-11-02', true, 0), true);
  });

  it('does not open it for a past day, a booked day, or someone who cannot add', () => {
    assert.equal(opensAddForm('2026-11-01', '2026-11-02', true, 0), false);
    assert.equal(opensAddForm('2026-11-03', '2026-11-02', true, 1), false);
    assert.equal(opensAddForm('2026-11-03', '2026-11-02', false, 0), false);
  });
});

describe('dayClick', () => {
  const base = {
    today: '2026-11-02',
    canAdd: true,
    appointmentsThatDay: 0,
    formOpen: false,
    formIsAuto: false,
  };

  it('opens the form for an empty day and only shows a booked one', () => {
    assert.equal(dayClick({ ...base, day: '2026-11-05' }), 'select-and-add');
    assert.equal(dayClick({ ...base, day: '2026-11-05', appointmentsThatDay: 2 }), 'select');
  });

  it('moves the date of a form the person opened or started filling in', () => {
    assert.equal(dayClick({ ...base, day: '2026-11-05', formOpen: true }), 'form-date');
    assert.equal(
      dayClick({ ...base, day: '2026-10-30', formOpen: true, appointmentsThatDay: 1 }),
      'select',
    );
  });

  it('never lets an untouched form that opened by itself take over a later click', () => {
    const auto = { ...base, formOpen: true, formIsAuto: true };
    assert.equal(dayClick({ ...auto, day: '2026-11-06', appointmentsThatDay: 1 }), 'select');
    assert.equal(dayClick({ ...auto, day: '2026-11-07' }), 'select-and-add');
  });
});
