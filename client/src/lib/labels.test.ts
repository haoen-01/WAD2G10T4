import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  SENIOR_REPLIES,
  activityWords,
  attentionBadge,
  daySummary,
  decisionBadge,
  type DaySummaryInput,
} from './labels';

describe('badges', () => {
  it('names every decision the policy can make in plain words', () => {
    for (const decision of [
      'no_action',
      'gentle_nudge',
      'programme_suggestion',
      'coordinator_review',
      'suppress',
    ]) {
      const { label } = decisionBadge(decision);
      assert.ok(label.length > 0);
      assert.ok(!label.includes('_'), `${decision} leaked a raw code: ${label}`);
    }
  });

  it('never shows a person needing review as a success', () => {
    assert.equal(decisionBadge('coordinator_review').tone, 'warning');
    assert.equal(attentionBadge('review').tone, 'warning');
  });

  it('humanises a value the API adds later instead of rendering a code or nothing', () => {
    assert.deepEqual(decisionBadge('some_new_decision'), {
      label: 'some new decision',
      tone: 'secondary',
    });
  });
});

describe('what the screens offer', () => {
  it('lets a senior say yes, later or no, and thanks them for each', () => {
    assert.deepEqual(
      SENIOR_REPLIES.map((reply) => reply.outcome),
      ['accepted', 'deferred', 'declined'],
    );
    assert.ok(SENIOR_REPLIES.every((reply) => reply.thanks.length > 0));
  });
});

const DECISIONS = [
  'no_action',
  'gentle_nudge',
  'programme_suggestion',
  'coordinator_review',
  'suppress',
] as const;
const BANDS = ['stable', 'watch', 'review'] as const;

const base: DaySummaryInput = {
  elder: 'Mdm Lim',
  decision: 'no_action',
  band: 'stable',
  gate: 'within_range',
  safeToInterpret: true,
  consentActive: true,
  percent: 100,
  pastDay: null,
};

describe('the old jargon is gone', () => {
  it('says "A usual day" and what Care+ is doing, not "Stable" or "No action needed"', () => {
    assert.equal(attentionBadge('stable').label, 'A usual day');
    // About Care+, so it never contradicts the family's own "Needs you" list.
    assert.equal(decisionBadge('no_action').label, 'Care+ isn’t suggesting anything right now');
  });
});

describe('daySummary', () => {
  it('describes every decision and band without claiming she is okay, fine or healthy', () => {
    for (const decision of DECISIONS) {
      for (const band of BANDS) {
        for (const safeToInterpret of [true, false]) {
          const summary = daySummary({ ...base, decision, band, safeToInterpret });
          const words = `${summary.headline} ${summary.detail} ${summary.action}`;
          assert.ok(summary.headline.length > 0);
          assert.ok(summary.action.length > 0);
          assert.doesNotMatch(words, /(okay|ok|fine|healthy|well|safe)/i, words);
          assert.doesNotMatch(words, /urgent|emergency|alert|danger|immediately/i, words);
          assert.doesNotMatch(words, /_/, `raw code in: ${words}`);
        }
      }
    }
  });

  it('never calls a day usual when the watch data cannot be read', () => {
    const summary = daySummary({
      ...base,
      decision: 'suppress',
      gate: 'data_quality',
      safeToInterpret: false,
    });
    assert.equal(summary.headline, 'Not enough watch data today');
    assert.equal(summary.comparable, false);
    assert.doesNotMatch(summary.headline, /usual/);
  });

  it('says not enough data even when the check fails on a stable band', () => {
    const summary = daySummary({ ...base, safeToInterpret: false });
    assert.match(summary.headline, /^Not enough watch data/);
  });

  it('names the reading’s own day instead of today when the data is older', () => {
    const summary = daySummary({ ...base, safeToInterpret: false, pastDay: 'Tue, 18 Aug' });
    assert.equal(summary.headline, 'Not enough watch data on Tue, 18 Aug');
    for (const band of BANDS) {
      const usual = daySummary({ ...base, band, pastDay: 'Tue, 18 Aug' });
      assert.doesNotMatch(`${usual.headline} ${usual.detail}`, /today/i);
      assert.match(usual.headline, /Tue, 18 Aug/);
    }
  });

  it('puts an older reading in the past tense', () => {
    const old = { ...base, pastDay: 'Tue, 18 Aug' };
    assert.equal(daySummary(old).headline, 'Tue, 18 Aug was a usual day for Mdm Lim');
    assert.equal(
      daySummary({ ...old, band: 'watch', percent: 75 }).headline,
      'Tue, 18 Aug was a quieter day than usual for Mdm Lim',
    );
    assert.equal(
      daySummary({ ...old, percent: 125 }).headline,
      'Tue, 18 Aug was a more active day than usual for Mdm Lim',
    );
    assert.equal(
      daySummary({ ...old, band: 'review', percent: 50 }).headline,
      'Mdm Lim had been less active than usual for a few days, up to Tue, 18 Aug',
    );
  });

  it('says a usual day only for a stable band with readable data', () => {
    assert.equal(daySummary(base).headline, 'A usual day for Mdm Lim');
    assert.equal(
      daySummary({ ...base, percent: 125 }).headline,
      'A more active day than usual for Mdm Lim',
    );
    assert.equal(
      daySummary({ ...base, band: 'watch', percent: 75 }).headline,
      'A quieter day than usual for Mdm Lim',
    );
    assert.equal(
      daySummary({ ...base, band: 'review', decision: 'coordinator_review', percent: 50 }).headline,
      'Mdm Lim has been less active than usual for a few days',
    );
  });

  it('puts a coordinator review calmly', () => {
    const summary = daySummary({
      ...base,
      band: 'review',
      decision: 'coordinator_review',
      percent: 50,
    });
    assert.equal(summary.action, 'A coordinator will look over her recent days');
    assert.equal(summary.tone, 'warning');
  });

  it('explains a held-back suggestion by its gate', () => {
    assert.equal(
      daySummary({ ...base, decision: 'suppress', gate: 'contact_cap' }).action,
      'Care+ is giving her a few quiet days',
    );
    const paused = daySummary({
      ...base,
      decision: 'suppress',
      gate: 'consent',
      consentActive: false,
    });
    assert.equal(paused.headline, 'Mdm Lim has withdrawn her consent');
    assert.equal(paused.comparable, false);
  });

  it('is still learning a new person’s usual day', () => {
    const summary = daySummary({ ...base, gate: 'small_baseline' });
    assert.equal(summary.detail, 'Care+ is still learning her usual day');
  });
});

describe('activityWords', () => {
  it('compares only with her own usual day', () => {
    assert.equal(activityWords(120), 'More active than most days');
    assert.equal(activityWords(100), 'About as active as most days');
    assert.equal(activityWords(85), 'A little less active than most days');
    assert.equal(activityWords(50), 'Less active than most days');
    assert.match(activityWords(null), /Not enough readings/);
  });
});
