import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  formatClockTime,
  formatIsoDay,
  formatMomentDay,
  formatMomentTime,
  formatMonthYear,
  parseIsoDay,
} from './format-date';

describe('formatIsoDay', () => {
  it('reads a calendar day as "Thu, 20 Aug"', () => {
    assert.equal(formatIsoDay('2026-08-20'), 'Thu, 20 Aug');
    assert.equal(formatIsoDay('2026-09-17'), 'Thu, 17 Sep');
    assert.equal(formatIsoDay('2026-01-01T00:00:00Z'), 'Thu, 1 Jan');
  });

  it('offers a long form and a form without the weekday', () => {
    assert.equal(formatIsoDay('2026-08-20', { style: 'long' }), 'Thursday, 20 August');
    assert.equal(formatIsoDay('2026-08-20', { weekday: false }), '20 Aug');
  });

  it('never guesses at a missing or impossible day', () => {
    assert.equal(formatIsoDay('2026-02-30'), '2026-02-30');
    assert.equal(formatIsoDay('not-a-day'), 'not-a-day');
    assert.equal(formatIsoDay(null, { fallback: 'Not set' }), 'Not set');
    assert.equal(formatIsoDay(undefined), '');
    assert.equal(parseIsoDay('2026-13-01'), null);
  });
});

describe('formatMomentTime', () => {
  it('reads a timestamp in Singapore time, whatever the machine zone', () => {
    assert.equal(formatMomentTime('2026-09-17T09:30:00Z'), 'Thu, 17 Sep, 5:30 pm');
    // 20:00 UTC is already the next morning in Singapore.
    assert.equal(formatMomentTime('2026-08-19T20:05:00Z'), 'Thu, 20 Aug, 4:05 am');
    assert.equal(formatMomentTime('2026-08-20T04:00:00Z'), 'Thu, 20 Aug, 12:00 pm');
    assert.equal(formatMomentTime('2026-08-19T16:00:00Z'), 'Thu, 20 Aug, 12:00 am');
  });

  it('gives the day alone, and says so when there is no moment', () => {
    assert.equal(formatMomentDay('2026-08-19T20:05:00Z'), 'Thu, 20 Aug');
    assert.equal(formatMomentTime('garbage'), 'Not recorded');
    assert.equal(formatMomentDay(null, { fallback: '—' }), '—');
  });
});

describe('formatClockTime', () => {
  it('reads a 24-hour time the way the app writes times: "10:00 am", "2:30 pm"', () => {
    assert.equal(formatClockTime('10:00'), '10:00 am');
    assert.equal(formatClockTime('14:30'), '2:30 pm');
    assert.equal(formatClockTime('08:05'), '8:05 am');
  });

  it('gets midnight and noon right', () => {
    assert.equal(formatClockTime('00:00'), '12:00 am');
    assert.equal(formatClockTime('12:00'), '12:00 pm');
    assert.equal(formatClockTime('23:59'), '11:59 pm');
  });

  it('never guesses at something that is not a clock time', () => {
    assert.equal(formatClockTime('24:00'), '24:00');
    assert.equal(formatClockTime('9:5'), '9:5');
    assert.equal(formatClockTime('soon'), 'soon');
    assert.equal(formatClockTime(null), '');
    assert.equal(formatClockTime(undefined), '');
  });
});

describe('formatMonthYear', () => {
  it('writes a month in full, with its year', () => {
    assert.equal(formatMonthYear(2026, 9), 'September 2026');
    assert.equal(formatMonthYear(2027, 1), 'January 2027');
  });
});
