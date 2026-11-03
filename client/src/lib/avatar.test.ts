import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { avatarAlt, avatarPhoto, initialsOf } from './avatar';

describe('initialsOf', () => {
  it('takes the first letter of the first two words', () => {
    assert.equal(initialsOf('Mdm Lim'), 'ML');
    assert.equal(initialsOf('sarah tan wei ling'), 'ST');
    assert.equal(initialsOf('  Emily  '), 'E');
  });

  it('never draws an empty circle', () => {
    assert.equal(initialsOf(''), '?');
    assert.equal(initialsOf('   '), '?');
  });
});

describe('avatarPhoto', () => {
  it('shows a photo only when one is given and it loaded', () => {
    assert.equal(avatarPhoto('/photos/lim.jpg', false), '/photos/lim.jpg');
    assert.equal(avatarPhoto('/photos/lim.jpg', true), null);
  });

  it('falls back to initials without a photo', () => {
    assert.equal(avatarPhoto(undefined, false), null);
    assert.equal(avatarPhoto(null, false), null);
    assert.equal(avatarPhoto('  ', false), null);
  });
});

describe('avatarAlt', () => {
  it('names the person', () => {
    assert.equal(avatarAlt('Mdm Lim'), 'Photo of Mdm Lim');
    assert.equal(avatarAlt(''), 'Photo');
  });
});
