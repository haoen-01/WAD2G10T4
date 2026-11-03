import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { stepLabel, writtenBy } from './agent';
import { myDaySource, readButtonLabel } from './my-day';

describe('my day', () => {
  it('says who wrote the run-through, and never calls a fallback or a replay live', () => {
    assert.match(myDaySource({ mode: 'agent', source: 'live' }), /assistant/);
    assert.match(myDaySource({ mode: 'agent', source: 'recorded' }), /not a live one/);
    for (const mode of ['fallback_disabled', 'fallback_error', 'fallback_no_proposal'] as const) {
      assert.doesNotMatch(myDaySource({ mode, source: null }), /assistant/);
    }
  });

  it('only counts an agent result as written by a model', () => {
    assert.equal(writtenBy({ mode: 'fallback_error', source: 'live' }), 'care-plus');
    assert.equal(writtenBy({ mode: 'agent', source: 'recorded' }), 'recorded');
    assert.equal(writtenBy({ mode: 'agent', source: 'live' }), 'live');
  });

  it('offers to show the words when the browser cannot speak', () => {
    assert.equal(readButtonLabel(true, false), 'Read my day');
    assert.equal(readButtonLabel(false, false), 'Show my day');
    assert.equal(readButtonLabel(true, true), 'Stop reading');
  });

  it('describes the run-through steps in plain words', () => {
    assert.equal(stepLabel('get_my_reminders_today'), 'Read today’s reminders');
    assert.equal(stepLabel('submit_my_day'), 'Wrote the run-through and had it checked');
  });
});
