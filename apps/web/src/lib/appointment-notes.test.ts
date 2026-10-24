import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  NOTE_MAX_LENGTH,
  cleanNote,
  isCurrent,
  isDayFull,
  removeOutcome,
  statusOf,
} from './appointment-notes';

describe('cleanNote', () => {
  it('trims and accepts 1 to 500 characters', () => {
    assert.equal(cleanNote('  Taxi at 9  '), 'Taxi at 9');
    assert.equal(cleanNote('a'), 'a');
    assert.equal(cleanNote('a'.repeat(NOTE_MAX_LENGTH))?.length, NOTE_MAX_LENGTH);
  });

  it('refuses empty, blank and too long notes', () => {
    assert.equal(cleanNote(''), null);
    assert.equal(cleanNote('   \n '), null);
    assert.equal(cleanNote('a'.repeat(NOTE_MAX_LENGTH + 1)), null);
  });
});

describe('failures', () => {
  it('reads a status from an error, and none from anything else', () => {
    assert.equal(statusOf({ status: 409 }), 409);
    assert.equal(statusOf(new Error('x')), null);
    assert.equal(statusOf(null), null);
  });

  it('a 409 on add is a full day', () => {
    assert.equal(isDayFull({ status: 409 }), true);
    assert.equal(isDayFull({ status: 500 }), false);
  });

  it('classifies a failed delete', () => {
    assert.equal(removeOutcome({ status: 404 }), 'gone');
    assert.equal(removeOutcome({ status: 403 }), 'forbidden');
    assert.equal(removeOutcome({ status: 0 }), 'other');
    assert.equal(removeOutcome(undefined), 'other');
  });
});

describe('isCurrent', () => {
  it('is true only for the latest generation', () => {
    assert.equal(isCurrent(3, 3), true);
    assert.equal(isCurrent(2, 3), false);
  });
});
