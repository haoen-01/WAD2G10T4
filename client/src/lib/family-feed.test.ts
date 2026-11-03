import type { FamilyActivityEntry } from '@silverloop/api-client';
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  feedLine,
  feedLink,
  feedSentence,
  mergeActivity,
  relativeTime,
  withoutUndone,
} from './family-feed';

function entry(overrides: Partial<FamilyActivityEntry> = {}): FamilyActivityEntry {
  return {
    activity_id: 'a1',
    kind: 'check_in',
    at: '2026-10-10T04:00:00Z',
    actor_member_id: 'm1',
    actor_name: 'Sarah',
    is_me: false,
    subject_name: null,
    appointment_id: null,
    appointment_title: null,
    appointment_kind: null,
    on_date: null,
    occurrence_id: null,
    check_in_kind: null,
    note: null,
    origin: 'live',
    ...overrides,
  };
}

const elder = { elder: 'Mdm Lim' };
const physio = { appointment_id: 'p', appointment_title: 'Physio', on_date: '2026-10-28' };

describe('feedSentence', () => {
  it('words every kind', () => {
    const cases: [Partial<FamilyActivityEntry>, string][] = [
      [{ kind: 'group_created' }, 'Sarah started the care group for Mdm Lim'],
      [{ kind: 'member_approved', subject_name: 'John' }, 'Sarah let John into the group'],
      [{ kind: 'member_declined', subject_name: 'John' }, 'Sarah declined John’s request to join'],
      [{ kind: 'appointment_added', ...physio }, 'Sarah added Physio on Wed, 28 Oct'],
      [{ kind: 'appointment_changed', ...physio }, 'Sarah changed Physio on Wed, 28 Oct'],
      [{ kind: 'appointment_removed', ...physio }, 'Sarah removed Physio on Wed, 28 Oct'],
      [{ kind: 'helper_joined', ...physio }, 'Sarah took Physio on Wed, 28 Oct'],
      [{ kind: 'helper_stepped_back', ...physio }, 'Sarah stepped back from Physio on Wed, 28 Oct'],
      [
        { kind: 'availability_updated', on_date: '2026-10-28' },
        'Sarah updated free times for Wed, 28 Oct',
      ],
      [{ kind: 'check_in', check_in_kind: 'called' }, 'Sarah called Mdm Lim'],
      [{ kind: 'check_in', check_in_kind: 'visited' }, 'Sarah visited Mdm Lim'],
      [{ kind: 'check_in', check_in_kind: 'messaged' }, 'Sarah messaged Mdm Lim'],
      [{ kind: 'note_added', ...physio }, 'Sarah added a note on Physio on Wed, 28 Oct'],
      [
        { kind: 'helper_asked', subject_name: 'Emily', ...physio },
        'Sarah asked Emily to go to Physio on Wed, 28 Oct',
      ],
      [{ kind: 'helper_declined', ...physio }, 'Sarah can’t make Physio on Wed, 28 Oct'],
    ];
    for (const [fields, expected] of cases) {
      assert.equal(feedSentence(entry(fields), elder), expected, String(fields.kind));
    }
  });

  it('says You for the viewer and the name for everyone else', () => {
    const mine = entry({ is_me: true, check_in_kind: 'called' });
    assert.equal(feedSentence(mine, elder), 'You called Mdm Lim');
    assert.equal(feedLine(mine).actor, 'You');
    assert.equal(feedLine(entry({ check_in_kind: 'called' })).actor, 'Sarah');
    const asked = entry({ is_me: true, kind: 'helper_asked', subject_name: 'Emily', ...physio });
    assert.equal(feedSentence(asked), 'You asked Emily to go to Physio on Wed, 28 Oct');
    const declined = entry({ is_me: true, kind: 'helper_declined', ...physio });
    assert.equal(feedSentence(declined), 'You can’t make Physio on Wed, 28 Oct');
  });

  it('quotes a note', () => {
    const line = entry({ check_in_kind: 'called', note: ' She sounded cheerful ' });
    assert.equal(feedLine(line, elder).note, 'She sounded cheerful');
    assert.equal(feedSentence(line, elder), 'Sarah called Mdm Lim: “She sounded cheerful”');
  });

  it('words a repeating appointment (no day) as a series', () => {
    const series = { appointment_title: 'Tai chi', on_date: null };
    assert.equal(
      feedSentence(entry({ kind: 'appointment_added', ...series })),
      'Sarah added Tai chi (repeating)',
    );
    assert.equal(
      feedSentence(entry({ kind: 'appointment_removed', ...series })),
      'Sarah removed Tai chi (every day it repeats)',
    );
    assert.equal(
      feedSentence(entry({ kind: 'helper_joined', ...series })),
      'Sarah took Tai chi every time',
    );
  });

  it('falls back to a generic line for an unknown kind', () => {
    const odd = entry({ kind: 'something_new' as FamilyActivityEntry['kind'] });
    assert.equal(feedSentence(odd), 'Sarah updated the group');
  });

  it('words a declined request without a name', () => {
    assert.equal(
      feedSentence(entry({ kind: 'member_declined', subject_name: null })),
      'Sarah declined a request to join',
    );
  });

  it('copes with missing names and titles', () => {
    assert.equal(
      feedSentence(entry({ kind: 'helper_joined', actor_name: '', on_date: null })),
      'A family member took an appointment every time',
    );
    assert.equal(feedSentence(entry({ check_in_kind: null })), 'Sarah checked in with your senior');
  });
});

describe('feedLink', () => {
  it('links only when the day still exists', () => {
    assert.equal(feedLink(entry()), null);
    assert.equal(
      feedLink(entry({ occurrence_id: 'demo-physio@2026-10-28' })),
      '/calendar?appointment=demo-physio%402026-10-28',
    );
  });
});

describe('relativeTime', () => {
  const now = new Date('2026-10-10T04:00:00Z');
  const ago = (ms: number) => new Date(now.getTime() - ms).toISOString();
  it('counts minutes, hours and days', () => {
    assert.equal(relativeTime(ago(10_000), now), 'just now');
    assert.equal(relativeTime(ago(-5_000), now), 'just now');
    assert.equal(relativeTime(ago(5 * 60_000), now), '5 min ago');
    assert.equal(relativeTime(ago(3 * 3_600_000), now), '3 h ago');
    assert.equal(relativeTime(ago(30 * 3_600_000), now), 'Yesterday');
    assert.equal(relativeTime(ago(3 * 86_400_000), now), '3 days ago');
  });
  it('switches to a date after a week, and tolerates nonsense', () => {
    assert.equal(relativeTime(ago(10 * 86_400_000), now), 'Wed, 30 Sep');
    assert.equal(relativeTime('nope', now), '');
  });
});

describe('mergeActivity', () => {
  it('merges by id, newest first, and the incoming copy wins', () => {
    const old = entry({ activity_id: 'a', at: '2026-10-01T00:00:00Z', note: 'old' });
    const mid = entry({ activity_id: 'b', at: '2026-10-02T00:00:00Z' });
    const fresh = entry({ activity_id: 'c', at: '2026-10-03T00:00:00Z' });
    const merged = mergeActivity([mid, old], [fresh, { ...old, note: 'new' }]);
    assert.deepEqual(
      merged.map((e) => e.activity_id),
      ['c', 'b', 'a'],
    );
    assert.equal(merged[2].note, 'new');
  });

  it('breaks ties by id, descending, and does not mutate its inputs', () => {
    const a = entry({ activity_id: 'a' });
    const b = entry({ activity_id: 'b' });
    const current = [a];
    const merged = mergeActivity(current, [b]);
    assert.deepEqual(
      merged.map((e) => e.activity_id),
      ['b', 'a'],
    );
    assert.equal(current.length, 1);
  });
});

describe('withoutUndone', () => {
  const took = (id: string, at: string, actor = 'm1') =>
    entry({ activity_id: id, kind: 'helper_joined', at, actor_member_id: actor, ...physio });
  const back = (id: string, at: string, actor = 'm1') =>
    entry({ activity_id: id, kind: 'helper_stepped_back', at, actor_member_id: actor, ...physio });
  const ids = (list: FamilyActivityEntry[]) => list.map((item) => item.activity_id);

  it('leaves out an "I’ll go" that was undone straight away, and its step back', () => {
    const feed = [back('b', '2026-10-26T00:31:00Z'), took('t', '2026-10-26T00:30:00Z')];
    assert.deepEqual(ids(withoutUndone(feed)), []);
  });

  it('keeps a step back that came later, so the family knows it needs someone again', () => {
    const feed = [back('b', '2026-10-26T02:00:00Z'), took('t', '2026-10-26T00:30:00Z')];
    assert.deepEqual(ids(withoutUndone(feed)), ['b', 't']);
  });

  it('pairs each step back with one "took", and only for the same member and day', () => {
    const feed = [
      took('t2', '2026-10-26T00:33:00Z'),
      back('b', '2026-10-26T00:32:00Z'),
      took('t1', '2026-10-26T00:31:00Z'),
      took('other', '2026-10-26T00:31:30Z', 'm2'),
    ];
    assert.deepEqual(ids(withoutUndone(feed)), ['t2', 'other']);
  });

  it('never pairs ask lines: an asked and a can’t-make line both stay', () => {
    const feed = [
      entry({ activity_id: 'no', kind: 'helper_declined', at: '2026-10-26T00:31:00Z', ...physio }),
      entry({ activity_id: 'ask', kind: 'helper_asked', at: '2026-10-26T00:30:00Z', ...physio }),
    ];
    assert.deepEqual(ids(withoutUndone(feed)), ['no', 'ask']);
  });
});
