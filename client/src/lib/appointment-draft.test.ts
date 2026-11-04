import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  applyDraft,
  draftFailure,
  draftNotes,
  draftSource,
  type DraftableField,
  type DraftableFields,
} from './appointment-draft';

const BLANK: DraftableFields = {
  title: '',
  kind: 'activity',
  date: '2026-11-03',
  start: '09:00',
  end: '10:00',
  location: '',
  repeat: 'none',
};

const DRAFT = {
  title: 'Dental check',
  kind: 'medical' as const,
  date: '2026-11-06',
  start: '15:00',
  end: '16:00',
  location: 'Bedok Polyclinic',
  repeat: 'none' as const,
};

const DRAFT_NOTES = { missing: [], assumed: [], clashes: [] };

describe('appointment draft', () => {
  it('says who filled in the form, and never calls a parser or a replay live', () => {
    assert.match(draftSource({ mode: 'agent', source: 'live' }), /assistant/);
    assert.match(draftSource({ mode: 'agent', source: 'recorded' }), /not a live model/);
    for (const mode of ['fallback_disabled', 'fallback_error', 'fallback_no_proposal'] as const) {
      assert.doesNotMatch(draftSource({ mode, source: null }), /assistant/);
    }
    assert.match(draftSource({ mode: 'fallback_error', source: null }), /unavailable/);
  });

  it('lists what is missing, what was guessed and what it clashes with', () => {
    assert.deepEqual(
      draftNotes({ missing: ['date', 'start', 'end'], assumed: ['kind'], clashes: ['Physio'] }),
      [
        'Still to fill in: the day, the start time and the end time.',
        'Guessed, so please check: the category.',
        'Same time as the Physio.',
        'Nothing is saved until you press Add.',
      ],
    );
  });

  it('names every clashing appointment in a plain sentence', () => {
    const notes = draftNotes({
      missing: [],
      assumed: [],
      clashes: ['Physio', 'Eye check-up', 'Doctor’s appointment'],
    });
    assert.equal(
      notes[0],
      'Same time as the Physio, the Eye check-up and the Doctor’s appointment.',
    );
  });

  it('always says nothing is saved yet', () => {
    assert.deepEqual(draftNotes({ missing: [], assumed: [], clashes: [] }), [
      'Nothing is saved until you press Add.',
    ]);
  });

  it('fills in every field the description gave', () => {
    const { next, filled, kept } = applyDraft(BLANK, DRAFT, new Set());
    assert.deepEqual(next, { ...DRAFT, repeat: 'none' });
    assert.deepEqual(kept, []);
    assert.equal(filled.length, 6);
  });

  it('never overwrites a field the person typed themselves, and says which it kept', () => {
    const typed = { ...BLANK, title: 'Teeth', location: 'Tampines' };
    const edited = new Set<DraftableField>(['title', 'location']);
    const { next, kept } = applyDraft(typed, DRAFT, edited);
    assert.equal(next.title, 'Teeth');
    assert.equal(next.location, 'Tampines');
    assert.equal(next.date, '2026-11-06');
    assert.deepEqual(kept, ['title', 'location']);
    assert.deepEqual(draftNotes(DRAFT_NOTES, kept, ['date']), [
      'Kept what you had typed for what it is and the place.',
      'Nothing is saved until you press Add.',
    ]);
  });

  it('invents nothing: fields the description left out stay as they were', () => {
    const typed = { ...BLANK, title: 'Kopi', location: 'Void deck', repeat: 'weekly' as const };
    const sparse = { ...DRAFT, date: null, start: null, end: null, location: null, kind: null };
    const { next, filled } = applyDraft(typed, sparse, new Set());
    assert.deepEqual(next, { ...typed, title: 'Dental check' });
    assert.deepEqual(filled, ['title']);
  });

  it('says so when nothing could be picked out', () => {
    const empty = {
      title: null,
      kind: null,
      date: null,
      start: null,
      end: null,
      location: null,
      repeat: 'none' as const,
    };
    const { filled, kept } = applyDraft(BLANK, empty, new Set());
    assert.match(draftNotes(DRAFT_NOTES, kept, filled)[0], /No details could be picked out/);
  });

  it('names what actually went wrong, never a generic failure', () => {
    const failure = (status: number, message = 'x') =>
      Object.assign(new Error(message), { status });
    assert.equal(draftFailure(failure(0, 'timeout of 60000ms exceeded')).kind, 'timeout');
    assert.equal(draftFailure(failure(0, 'Network Error')).kind, 'network');
    assert.equal(draftFailure(failure(401)).kind, 'session');
    assert.equal(draftFailure(failure(404)).kind, 'forbidden');
    assert.equal(draftFailure(failure(422)).kind, 'invalid');
    assert.equal(draftFailure(failure(500)).kind, 'server');
    for (const status of [0, 422, 500]) {
      assert.match(draftFailure(failure(status)).message, /fill in the form below/);
    }
  });
});
