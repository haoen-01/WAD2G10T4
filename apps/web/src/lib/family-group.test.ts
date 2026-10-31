import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { calendarSourceFor, homeSeniorOf, seniorOf, taskOwnerOf } from './family-group';

const linked = { group_id: 'grp_1', person_id: 'person-1' };
const unlinked = { group_id: 'grp_2', person_id: null };

describe('seniorOf', () => {
  it('is the linked senior, or null before one is linked', () => {
    assert.equal(seniorOf(linked), 'person-1');
    assert.equal(seniorOf(unlinked), null);
    assert.equal(seniorOf(null), null);
    assert.equal(seniorOf(undefined), null);
  });
});

describe('homeSeniorOf', () => {
  it('reads the current group’s senior', () => {
    assert.equal(homeSeniorOf(linked, 'mdm-lim'), 'person-1');
  });

  it('reads nobody for a group with no senior, never the fallback', () => {
    assert.equal(homeSeniorOf(unlinked, 'mdm-lim'), null);
  });

  it('keeps the fallback senior when there is no group at all', () => {
    assert.equal(homeSeniorOf(null, 'mdm-lim'), 'mdm-lim');
  });
});

describe('taskOwnerOf', () => {
  it('keys tasks by the senior once linked, else by the group', () => {
    assert.equal(taskOwnerOf(linked, 'mdm-lim'), 'person-1');
    assert.equal(taskOwnerOf(unlinked, 'mdm-lim'), 'grp_2');
  });

  it('falls back only when there is neither', () => {
    assert.equal(taskOwnerOf(null, 'mdm-lim'), 'mdm-lim');
    assert.equal(taskOwnerOf({ group_id: null, person_id: null }, 'mdm-lim'), 'mdm-lim');
  });
});

describe('calendarSourceFor', () => {
  it('gives a senior their own calendar', () => {
    assert.deepEqual(
      calendarSourceFor({ role: 'senior', person_id: 'person-9' }, linked, 'mdm-lim'),
      { kind: 'person', personId: 'person-9' },
    );
  });

  it('gives a family member their group’s calendar, linked or not', () => {
    const family = { role: 'family', person_id: null };
    assert.deepEqual(calendarSourceFor(family, linked, 'mdm-lim'), {
      kind: 'group',
      groupId: 'grp_1',
    });
    assert.deepEqual(calendarSourceFor(family, unlinked, 'mdm-lim'), {
      kind: 'group',
      groupId: 'grp_2',
    });
  });

  it('keeps the fallback senior’s calendar with no group (the demo)', () => {
    assert.deepEqual(calendarSourceFor(null, null, 'mdm-lim'), {
      kind: 'person',
      personId: 'mdm-lim',
    });
    assert.deepEqual(calendarSourceFor({ role: 'family' }, null, 'mdm-lim'), {
      kind: 'person',
      personId: 'mdm-lim',
    });
  });
});
