import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { draftNotes, draftSource } from './appointment-draft';

describe('appointment draft', () => {
  it('says who filled in the form, and never calls a parser or a replay live', () => {
    assert.match(draftSource({ mode: 'agent', source: 'live' }), /assistant/);
    assert.match(draftSource({ mode: 'agent', source: 'recorded' }), /not a live model/);
    for (const mode of ['fallback_disabled', 'fallback_error', 'fallback_no_proposal'] as const) {
      assert.doesNotMatch(draftSource({ mode, source: null }), /assistant/);
    }
  });

  it('lists what is missing, what was guessed and what it clashes with', () => {
    assert.deepEqual(
      draftNotes({ missing: ['date', 'start', 'end'], assumed: ['kind'], clashes: ['Physio'] }),
      [
        'Still to fill in: the day, the start time and the end time.',
        'Guessed, so please check: the category.',
        'At the same time as: Physio.',
        'Nothing is saved until you press Add.',
      ],
    );
  });

  it('always says nothing is saved yet', () => {
    assert.deepEqual(draftNotes({ missing: [], assumed: [], clashes: [] }), [
      'Nothing is saved until you press Add.',
    ]);
  });
});
