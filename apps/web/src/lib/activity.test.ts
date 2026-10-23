import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  GENTLE_NUDGE_PERCENT,
  compareWords,
  formatSteps,
  fortnightSentence,
  isNearUsual,
  percentOfUsual,
  summariseDays,
} from './activity';

describe('percentOfUsual', () => {
  it('rounds to a whole percentage', () => {
    assert.equal(percentOfUsual(5720, 5747), 100);
    assert.equal(percentOfUsual(2873, 5747), 50);
  });

  it('has no answer without a usual day', () => {
    assert.equal(percentOfUsual(4000, 0), null);
    assert.equal(percentOfUsual(Number.NaN, 5000), null);
  });
});

describe('isNearUsual', () => {
  it('uses the policy’s first rung as the line', () => {
    assert.equal(GENTLE_NUDGE_PERCENT, 20);
    assert.equal(isNearUsual(8000, 10000), true);
    assert.equal(isNearUsual(7900, 10000), false);
  });
});

describe('compareWords', () => {
  it('describes each band in plain words', () => {
    assert.equal(compareWords(120), 'more than a usual day');
    assert.equal(compareWords(100), 'about the same as a usual day');
    assert.equal(compareWords(85), 'a little less than a usual day');
    assert.equal(compareWords(60), 'well below a usual day');
    assert.equal(compareWords(null), 'not enough data to compare yet');
  });
});

describe('summariseDays', () => {
  const days = [
    { day: '2026-08-01', steps: 5000 },
    { day: '2026-08-02', steps: 3000 },
    { day: '2026-08-03', steps: 6500 },
  ];

  it('counts days near usual and finds the extremes', () => {
    const summary = summariseDays(days, 5000);
    assert.equal(summary.total, 3);
    assert.equal(summary.near, 2);
    assert.equal(summary.lowest?.day, '2026-08-02');
    assert.equal(summary.highest?.day, '2026-08-03');
  });

  it('ignores days without a reading', () => {
    const summary = summariseDays([...days, { day: '2026-08-04', steps: Number.NaN }], 5000);
    assert.equal(summary.total, 3);
  });

  it('copes with no days at all', () => {
    const summary = summariseDays([], 5000);
    assert.deepEqual(summary, { total: 0, near: 0, lowest: null, highest: null });
  });
});

describe('fortnightSentence', () => {
  it('says how many days were near usual', () => {
    assert.equal(
      fortnightSentence({ total: 14, near: 12, lowest: null, highest: null }),
      '12 of the last 14 days were within 20% of her usual day.',
    );
  });

  it('says "all" when every day was near usual', () => {
    assert.equal(
      fortnightSentence({ total: 14, near: 14, lowest: null, highest: null }),
      'All of the last 14 days were within 20% of her usual day.',
    );
  });

  it('speaks to the senior on their own screen', () => {
    assert.equal(
      fortnightSentence({ total: 7, near: 7, lowest: null, highest: null }, 'your'),
      'All of the last 7 days were within 20% of your usual day.',
    );
  });

  it('says so when there is nothing to summarise', () => {
    assert.equal(
      fortnightSentence({ total: 0, near: 0, lowest: null, highest: null }),
      'No daily readings yet.',
    );
  });
});

describe('formatSteps', () => {
  it('groups thousands and pluralises', () => {
    assert.equal(formatSteps(5720.4), '5,720 steps');
    assert.equal(formatSteps(1), '1 step');
  });
});
