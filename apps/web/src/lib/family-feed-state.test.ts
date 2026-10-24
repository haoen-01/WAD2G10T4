import type { FamilyActivityEntry } from '@silverloop/api-client';
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  addOptimistic,
  applyFirstPage,
  applyOlderPage,
  emptyFeed,
  isStale,
  renderKey,
  rollbackCheckIn,
  settleCheckIn,
  type FeedState,
} from './family-feed-state';

function entry(id: string, at: string, overrides: Partial<FamilyActivityEntry> = {}) {
  return {
    activity_id: id,
    kind: 'check_in',
    at,
    actor_member_id: 'm1',
    actor_name: 'Sarah',
    is_me: true,
    subject_name: null,
    appointment_id: null,
    appointment_title: null,
    appointment_kind: null,
    on_date: null,
    occurrence_id: null,
    check_in_kind: 'called',
    note: null,
    origin: 'live',
    ...overrides,
  } satisfies FamilyActivityEntry as FamilyActivityEntry;
}

const ids = (state: FeedState) => state.entries.map((e) => e.activity_id);
const day = (n: number) => `2026-10-${String(n + 10).padStart(2, '0')}T00:00:00Z`;

describe('applyFirstPage', () => {
  it('takes the page and its cursor on the first read', () => {
    const next = applyFirstPage(emptyFeed(), {
      entries: [entry('b', day(2)), entry('a', day(1))],
      next_before: 'a',
    });
    assert.deepEqual(ids(next), ['b', 'a']);
    assert.equal(next.nextBefore, 'a');
  });

  it('merges a later read and keeps the cursor of what was loaded', () => {
    const first = applyFirstPage(emptyFeed(), {
      entries: [entry('b', day(2)), entry('a', day(1))],
      next_before: 'a',
    });
    const older = applyOlderPage(first, { entries: [entry('z', day(0))], next_before: null });
    const polled = applyFirstPage(older, {
      entries: [entry('c', day(3)), entry('b', day(2))],
      next_before: 'b',
    });
    assert.deepEqual(ids(polled), ['c', 'b', 'a', 'z']);
    assert.equal(polled.nextBefore, null);
  });

  it('restarts from the page when it shares nothing and has older entries (a gap)', () => {
    const first = applyFirstPage(emptyFeed(), {
      entries: [entry('b', day(2)), entry('a', day(1))],
      next_before: 'a',
    });
    const polled = applyFirstPage(first, {
      entries: [entry('f', day(6)), entry('e', day(5))],
      next_before: 'e',
    });
    assert.deepEqual(ids(polled), ['f', 'e']);
    assert.equal(polled.nextBefore, 'e');
  });

  it('does not call it a gap when the page is the end of the feed', () => {
    const first = applyFirstPage(emptyFeed(), { entries: [entry('a', day(1))], next_before: null });
    const polled = applyFirstPage(first, { entries: [entry('b', day(2))], next_before: null });
    assert.deepEqual(ids(polled), ['b', 'a']);
  });

  it('drops an unsaved check-in the page already holds, and the saved one keeps its key', () => {
    const base = applyFirstPage(emptyFeed(), { entries: [entry('a', day(1))], next_before: null });
    const temp = entry('pending-1', day(2), { note: 'hello' });
    const shown = addOptimistic(base, temp);
    const polled = applyFirstPage(shown, {
      entries: [entry('real', day(2), { note: 'hello' }), entry('a', day(1))],
      next_before: null,
    });
    assert.deepEqual(ids(polled), ['real', 'a']);
    assert.equal(renderKey(polled.entries[0], polled.aliases), 'pending-1');
  });

  it('keeps an unsaved check-in the page does not hold yet', () => {
    const shown = addOptimistic(emptyFeed(), entry('pending-1', day(2), { note: 'hello' }));
    const polled = applyFirstPage(shown, { entries: [entry('a', day(1))], next_before: null });
    assert.deepEqual(ids(polled), ['pending-1', 'a']);
  });
});

describe('optimistic check-ins', () => {
  const base = applyFirstPage(emptyFeed(), { entries: [entry('a', day(1))], next_before: null });

  it('shows at once, newest first', () => {
    assert.deepEqual(ids(addOptimistic(base, entry('pending-1', day(2)))), ['pending-1', 'a']);
  });

  it('is replaced by the saved entry under the same render key', () => {
    const shown = addOptimistic(base, entry('pending-1', day(2)));
    const done = settleCheckIn(shown, 'pending-1', entry('real', day(2)));
    assert.deepEqual(ids(done), ['real', 'a']);
    assert.equal(renderKey(done.entries[0], done.aliases), 'pending-1');
    assert.equal(renderKey(done.entries[1], done.aliases), 'a');
  });

  it('settles cleanly when a poll already swapped it in', () => {
    const shown = addOptimistic(base, entry('pending-1', day(2), { note: 'hi' }));
    const polled = applyFirstPage(shown, {
      entries: [entry('real', day(2), { note: 'hi' }), entry('a', day(1))],
      next_before: null,
    });
    const done = settleCheckIn(polled, 'pending-1', entry('real', day(2), { note: 'hi' }));
    assert.deepEqual(ids(done), ['real', 'a']);
    assert.equal(renderKey(done.entries[0], done.aliases), 'pending-1');
  });

  it('is taken back out when the API refuses it', () => {
    const shown = addOptimistic(base, entry('pending-1', day(2)));
    assert.deepEqual(ids(rollbackCheckIn(shown, 'pending-1')), ['a']);
  });
});

describe('check-ins racing the polls', () => {
  it('does not let an identical second check-in claim an entry the list already holds', () => {
    const base = applyFirstPage(emptyFeed(), { entries: [entry('a', day(1))], next_before: null });
    // The first "Called" was saved as s1 under the key pending-1.
    let state = addOptimistic(base, entry('pending-1', day(2), { note: 'hi' }));
    state = settleCheckIn(state, 'pending-1', entry('s1', day(2), { note: 'hi' }));
    // An identical second one is shown, then a poll returns only s1.
    state = addOptimistic(state, entry('pending-2', day(3), { note: 'hi' }));
    state = applyFirstPage(state, {
      entries: [entry('s1', day(2), { note: 'hi' })],
      next_before: null,
    });
    assert.ok(ids(state).includes('pending-2'));
    const s1 = state.entries.find((e) => e.activity_id === 's1')!;
    assert.equal(renderKey(s1, state.aliases), 'pending-1');
    // When the second POST resolves there are two rows with two different keys.
    state = settleCheckIn(state, 'pending-2', entry('s2', day(3), { note: 'hi' }));
    const keys = state.entries.map((e) => renderKey(e, state.aliases));
    assert.equal(new Set(keys).size, keys.length);
    assert.deepEqual(ids(state), ['s2', 's1', 'a']);
  });

  it('does not reuse a key another entry already wears', () => {
    const state: FeedState = {
      ...emptyFeed(),
      entries: [entry('s1', day(2))],
      aliases: { s1: 'pending-2' },
    };
    const done = settleCheckIn(state, 'pending-2', entry('s2', day(3)));
    assert.equal(
      renderKey(
        done.entries.find((e) => e.activity_id === 's2')!,
        done.aliases,
      ),
      's2',
    );
  });

  it('still takes the first page’s cursor when a check-in settled before it loaded', () => {
    let state = addOptimistic(emptyFeed(), entry('pending-1', day(5)));
    state = settleCheckIn(state, 'pending-1', entry('s1', day(5)));
    assert.equal(state.nextBefore, null);
    state = applyFirstPage(state, {
      entries: [entry('b', day(2)), entry('a', day(1))],
      next_before: 'a',
    });
    assert.equal(state.nextBefore, 'a');
    assert.deepEqual(ids(state), ['s1', 'b', 'a']);
  });
});

describe('isStale', () => {
  it('is true only when the group or person changed', () => {
    assert.equal(isStale('g|u1', 'g|u1'), false);
    assert.equal(isStale('g|u1', 'g|u2'), true);
    assert.equal(isStale('g|u1', null), true);
  });
});
