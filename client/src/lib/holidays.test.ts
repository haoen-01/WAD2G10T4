import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { holidaysByDay, holidaysInMonth, toHolidays } from './holidays';

describe('toHolidays', () => {
  it('keeps well-formed entries, sorted by date', () => {
    const holidays = toHolidays([
      { date: '2026-12-25', name: 'Christmas Day' },
      { date: '2026-02-17', localName: 'Chinese New Year' },
      { date: 'not a date', name: 'Broken' },
      { date: '2026-05-01' },
      null,
    ]);
    assert.deepEqual(holidays, [
      { date: '2026-02-17', name: 'Chinese New Year' },
      { date: '2026-12-25', name: 'Christmas Day' },
    ]);
  });

  it('gives nothing for a body that is not a list', () => {
    assert.deepEqual(toHolidays({ error: 'x' }), []);
    assert.deepEqual(toHolidays(null), []);
  });
});

describe('holidaysByDay and holidaysInMonth', () => {
  const holidays = [
    { date: '2026-02-17', name: 'Chinese New Year' },
    { date: '2026-02-18', name: 'Chinese New Year' },
    { date: '2026-03-21', name: 'Hari Raya Puasa' },
    { date: '2026-03-21', name: 'Another' },
  ];

  it('keys by date and joins two on one day', () => {
    assert.deepEqual(holidaysByDay(holidays), {
      '2026-02-17': 'Chinese New Year',
      '2026-02-18': 'Chinese New Year',
      '2026-03-21': 'Hari Raya Puasa / Another',
    });
  });

  it('picks one month', () => {
    assert.equal(holidaysInMonth(holidays, 2026, 2).length, 2);
    assert.equal(holidaysInMonth(holidays, 2026, 4).length, 0);
  });
});
