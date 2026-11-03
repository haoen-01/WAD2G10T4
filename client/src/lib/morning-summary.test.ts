import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  buildSummary,
  MORNING_OFF,
  readingDayLabel,
  shouldShowSummary,
  shownToday,
  verdictOf,
  type SummaryInput,
} from './morning-summary';

const base: SummaryInput = {
  elder: 'Mdm Lim',
  today: '2026-11-04',
  readingDay: '2026-11-03',
  steps: 5720,
  usual: 5747,
  attentionBand: 'stable',
  lastDecision: 'no_action',
  consentActive: true,
  readable: true,
  appointmentsToday: [],
  tasksToday: [],
  unhelpedSoon: [],
  battery: null,
};

describe('when the summary opens by itself', () => {
  it('opens once a day for each senior, and never once turned off', () => {
    assert.equal(shouldShowSummary(null, 'mdm-lim', '2026-11-04'), true);
    const kept = shownToday(null, 'mdm-lim', '2026-11-04');
    assert.equal(shouldShowSummary(kept, 'mdm-lim', '2026-11-04'), false);
    assert.equal(shouldShowSummary(kept, 'mdm-lim', '2026-11-05'), true);
    assert.equal(shouldShowSummary(kept, 'mr-tan', '2026-11-04'), true);
    assert.equal(shouldShowSummary(MORNING_OFF, 'mdm-lim', '2026-11-05'), false);
  });

  it('remembers each senior, so switching between two does not open it again', () => {
    const both = shownToday(shownToday(null, 'mdm-lim', '2026-11-04'), 'mr-tan', '2026-11-04');
    assert.equal(shouldShowSummary(both, 'mdm-lim', '2026-11-04'), false);
    assert.equal(shouldShowSummary(both, 'mr-tan', '2026-11-04'), false);
  });

  it('treats an unreadable stored value as never shown', () => {
    assert.equal(shouldShowSummary('mdm-lim@2026-11-04', 'mdm-lim', '2026-11-04'), true);
    assert.equal(shouldShowSummary('[1]', 'mdm-lim', '2026-11-04'), true);
  });
});

describe('the reading day', () => {
  it('says yesterday or today when it is, and the date when it is an older sample', () => {
    assert.equal(readingDayLabel('2026-11-03', '2026-11-04'), 'Yesterday');
    assert.equal(readingDayLabel('2026-11-04', '2026-11-04'), 'Today so far');
    assert.equal(readingDayLabel('2026-08-18', '2026-11-04'), 'Tue, 18 Aug');
  });
});

describe('the verdict comes from the policy', () => {
  it('maps the attention band and decision, and a pause in sharing first', () => {
    assert.equal(verdictOf('stable', 'no_action', true), 'good');
    assert.equal(verdictOf('watch', 'no_action', true), 'watch');
    assert.equal(verdictOf('stable', 'gentle_nudge', true), 'watch');
    assert.equal(verdictOf('review', 'gentle_nudge', true), 'review');
    assert.equal(verdictOf('stable', 'coordinator_review', true), 'review');
    assert.equal(verdictOf('review', 'coordinator_review', false), 'paused');
  });

  it('words each verdict without any health words', () => {
    for (const [band, decision, consent] of [
      ['stable', 'no_action', true],
      ['watch', 'gentle_nudge', true],
      ['review', 'coordinator_review', true],
      ['stable', 'no_action', false],
    ] as const) {
      const summary = buildSummary({
        ...base,
        attentionBand: band,
        lastDecision: decision,
        consentActive: consent,
      });
      assert.ok(summary.headline.length > 0);
      assert.doesNotMatch(
        `${summary.headline} ${summary.note}`,
        /ill|sick|health|diagnos|fall|emergency/i,
      );
    }
    assert.equal(buildSummary(base).headline, 'All’s good.');
    assert.equal(buildSummary({ ...base, attentionBand: 'watch' }).headline, 'Keep an eye on it.');
  });

  it('does not compare a day the watch was not worn enough to read', () => {
    // The policy reports such a day as stable with no action; that must not read as "All's good".
    const summary = buildSummary({ ...base, steps: 900, readable: false });
    assert.equal(summary.verdict, 'unread');
    assert.equal(summary.percent, null);
    assert.equal(summary.headline, 'Not enough watch wear to compare.');
    assert.doesNotMatch(summary.note, /usual range|ill|sick|health/i);
    // A pause in sharing still comes first.
    assert.equal(
      buildSummary({ ...base, readable: false, consentActive: false }).verdict,
      'paused',
    );
  });
});

describe('the steps line', () => {
  it('compares with her usual day in the same words as Home', () => {
    const summary = buildSummary(base);
    assert.equal(summary.percent, 100);
    assert.equal(summary.compare, 'about the same as a usual day');
    assert.equal(summary.dayLabel, 'Yesterday');
    assert.equal(buildSummary({ ...base, usual: 0 }).percent, null);
  });
});

describe('what matters today', () => {
  it('lists visits, open tasks, visits that need someone, and a low watch', () => {
    const summary = buildSummary({
      ...base,
      appointmentsToday: [
        { title: 'Doctor’s appointment', start: '10:00', end: '12:00', needsSomeone: true },
      ],
      tasksToday: [
        { title: 'Light stretching', time: '17:00', completed: false },
        { title: 'Vitamin D', time: '08:00', completed: true },
        { title: 'Blood pressure tablet', time: '08:00', completed: false },
      ],
      unhelpedSoon: [{ title: 'Grocery shopping', date: '2026-11-06' }],
      battery: { percent: 12, charging: false },
    });
    assert.deepEqual(
      summary.todo.map((item) => item.icon),
      ['calendar', 'checklist', 'hand', 'battery'],
    );
    assert.match(
      summary.todo[0].text,
      /Doctor’s appointment, 10:00 am – 12:00 pm · no one going yet/,
    );
    assert.match(
      summary.todo[1].text,
      /^2 tasks to do today, starting with Blood pressure tablet at 8:00 am/,
    );
    assert.match(summary.todo[2].text, /Grocery shopping on Fri, 6 Nov still needs someone/);
    assert.match(summary.todo[3].text, /12%/);
  });

  it('says when every task is done, counts several unhelped visits, and skips a charging watch', () => {
    const summary = buildSummary({
      ...base,
      tasksToday: [{ title: 'Vitamin D', time: '08:00', completed: true }],
      unhelpedSoon: [
        { title: 'A', date: '2026-11-05' },
        { title: 'B', date: '2026-11-06' },
      ],
      battery: { percent: 5, charging: true },
    });
    assert.deepEqual(
      summary.todo.map((item) => item.text),
      [
        'Every task for today is done',
        '2 visits in the next 3 days still need someone to go along',
      ],
    );
  });

  it('does not repeat a visit that is already listed for today', () => {
    const summary = buildSummary({
      ...base,
      appointmentsToday: [
        { title: 'Eye check-up', start: '09:30', end: '10:30', needsSomeone: true },
      ],
      unhelpedSoon: [{ title: 'Eye check-up', date: '2026-11-04' }],
    });
    assert.equal(summary.todo.length, 1);
  });
});
