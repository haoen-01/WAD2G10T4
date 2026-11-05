import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { catchUpHeading, catchUpSource, lastVisitKey, parseLastVisit, stepLabel } from './catch-up';

const NOW = new Date('2026-11-03T10:00:00Z');

describe('catch-up', () => {
  it('remembers each group separately', () => {
    assert.notEqual(lastVisitKey('sarah', 'grp_a'), lastVisitKey('sarah', 'grp_b'));
  });

  it('remembers each person separately, so a shared browser does not mix them up', () => {
    assert.notEqual(lastVisitKey('sarah', 'grp_a'), lastVisitKey('john', 'grp_a'));
    assert.equal(lastVisitKey('sarah', 'grp_a'), lastVisitKey('sarah', 'grp_a'));
    // A viewer whose id contains the separator cannot collide with another viewer and group.
    assert.notEqual(lastVisitKey('a/b', 'c'), lastVisitKey('a', 'b/c'));
  });

  it('reads only a real moment in the past as the last visit', () => {
    assert.equal(parseLastVisit('2026-11-02T08:00:00Z', NOW), '2026-11-02T08:00:00.000Z');
    assert.equal(parseLastVisit(null, NOW), null);
    assert.equal(parseLastVisit('not a date', NOW), null);
    assert.equal(parseLastVisit('2027-01-01T00:00:00Z', NOW), null);
  });

  it('has nothing to be "since" on a first visit', () => {
    assert.equal(catchUpHeading(null), 'Where things stand');
    assert.equal(catchUpHeading('2026-11-02T08:00:00Z'), 'Since you last visited');
  });

  it('never says the assistant wrote a catch-up Care+ assembled itself', () => {
    assert.match(catchUpSource({ mode: 'agent', source: 'live' }), /assistant/);
    for (const mode of ['fallback_disabled', 'fallback_error', 'fallback_no_proposal'] as const) {
      assert.doesNotMatch(catchUpSource({ mode, source: null }), /assistant/);
    }
  });

  it('never calls a replayed recording live', () => {
    const replayed = catchUpSource({ mode: 'agent', source: 'recorded' });
    assert.match(replayed, /recorded/);
    assert.match(replayed, /not a live model/);
  });

  it('describes every agent step in plain words', () => {
    assert.equal(stepLabel('get_todays_tasks'), 'Checked today’s tasks');
    assert.equal(stepLabel('something_new'), 'Looked something up');
  });
});
