import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  countedBackNote,
  daysBefore,
  homeReadingWords,
  isSampleSource,
  latestDay,
  oldestReadingLabel,
  readingDayLabel,
  seniorCountedBackLine,
  seniorDayLabel,
  seniorReadingLine,
} from './reading-days';

const fortnight = Array.from({ length: 14 }, (_, index) => ({
  day: `2026-08-${String(7 + index).padStart(2, '0')}`,
}));

describe('readingDayLabel', () => {
  it('names the newest reading, and counts back from it', () => {
    assert.equal(readingDayLabel('2026-08-20', '2026-08-20'), 'Latest reading');
    assert.equal(readingDayLabel('2026-08-19', '2026-08-20'), '1 day ago');
    assert.equal(readingDayLabel('2026-08-07', '2026-08-20'), '13 days ago');
  });

  it('counts across a month end', () => {
    assert.equal(readingDayLabel('2026-07-31', '2026-08-02'), '2 days ago');
  });

  it('never shows a date, even for a day it cannot read', () => {
    assert.equal(readingDayLabel('not a day', '2026-08-20'), 'Latest reading');
    assert.equal(daysBefore('2026-02-30', '2026-08-20'), null);
  });
});

describe('latestDay', () => {
  it('finds the newest day in any order, or nothing', () => {
    assert.equal(latestDay([{ day: '2026-08-20' }, { day: '2026-08-07' }]), '2026-08-20');
    assert.equal(latestDay([{ day: '2026-08-07' }, { day: '2026-08-20' }]), '2026-08-20');
    assert.equal(latestDay([]), null);
  });
});

describe('oldestReadingLabel', () => {
  it("uses the oldest bar's own words on the two charts: 14 readings and 7 readings", () => {
    assert.equal(oldestReadingLabel(fortnight), readingDayLabel('2026-08-07', '2026-08-20'));
    assert.equal(oldestReadingLabel(fortnight), '13 days ago');
    assert.equal(oldestReadingLabel(fortnight.slice(-7)), '6 days ago');
  });

  it('counts days for any other span', () => {
    assert.equal(oldestReadingLabel(fortnight.slice(-2)), '1 day ago');
    assert.equal(oldestReadingLabel(fortnight.slice(-4)), '3 days ago');
    assert.equal(oldestReadingLabel(fortnight.slice(-11)), '10 days ago');
  });

  it('has nothing to say for one reading or none', () => {
    assert.equal(oldestReadingLabel(fortnight.slice(-1)), null);
    assert.equal(oldestReadingLabel([]), null);
  });
});

describe('isSampleSource', () => {
  it('marks only synthetic readings as Sample', () => {
    assert.equal(isSampleSource('synthetic'), true);
    assert.equal(isSampleSource('apple_health_export'), false);
    assert.equal(isSampleSource(undefined), false);
  });
});

describe('homeReadingWords', () => {
  it('says today only for a reading from today', () => {
    assert.deepEqual(homeReadingWords('2026-11-01', '2026-11-01', 'Mdm Lim'), {
      heading: 'Today with Mdm Lim',
      stepsLabel: 'Today so far',
      ledeStart: 'Mdm Lim has walked',
      ledeWhen: 'so far',
    });
  });

  it('names the day of any other reading, with no "today" anywhere', () => {
    const words = homeReadingWords('2026-08-18', '2026-11-01', 'Mdm Lim');
    assert.deepEqual(words, {
      heading: 'Mdm Lim on Tue, 18 Aug',
      stepsLabel: 'Steps on Tue, 18 Aug',
      ledeStart: 'Mdm Lim walked',
      ledeWhen: 'on Tue, 18 Aug',
    });
    assert.doesNotMatch(JSON.stringify(words), /today|so far/i);
  });

  it('names the senior in the lede, never "she" or "he" (Care+ does not record gender)', () => {
    const today = homeReadingWords('2026-11-01', '2026-11-01', 'Mr Tan');
    const older = homeReadingWords('2026-08-18', '2026-11-01', 'Mr Tan');
    assert.equal(today.ledeStart, 'Mr Tan has walked');
    assert.equal(older.ledeStart, 'Mr Tan walked');
    assert.doesNotMatch(JSON.stringify([today, older]), /\b(she|her|he|his)\b/i);
  });
});

describe('countedBackNote', () => {
  it('names the latest reading unless it is from today', () => {
    assert.equal(
      countedBackNote('2026-08-18', '2026-11-01'),
      'Days are counted back from the latest reading, Tue, 18 Aug.',
    );
    assert.equal(countedBackNote('2026-11-01', '2026-11-01'), null);
    assert.equal(countedBackNote(null, '2026-11-01'), null);
  });
});

describe('the senior wording', () => {
  it('says how recent the steps are, in plain words', () => {
    assert.equal(seniorReadingLine('2026-11-01', '2026-11-01'), 'These steps are from today.');
    assert.equal(
      seniorReadingLine('2026-08-18', '2026-11-01'),
      'These steps are from Tue, 18 Aug.',
    );
  });

  it('says what the days count back from, only when that is not today', () => {
    assert.equal(
      seniorCountedBackLine('2026-08-18', '2026-11-01'),
      '“Days ago” means days before Tue,\u00a018\u00a0Aug.',
    );
    assert.equal(seniorCountedBackLine('2026-11-01', '2026-11-01'), null);
    assert.equal(seniorCountedBackLine(null, '2026-11-01'), null);
  });

  it('calls the newest bar the latest day, and counts back from it', () => {
    assert.equal(seniorDayLabel('2026-08-18', '2026-08-18'), 'Latest day');
    assert.equal(seniorDayLabel('2026-08-12', '2026-08-18'), '6 days ago');
  });
});
