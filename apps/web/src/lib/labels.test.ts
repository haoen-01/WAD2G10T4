import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { SENIOR_REPLIES, attentionBadge, decisionBadge } from './labels';

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
