import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { signInEmail } from './sign-in-email';

describe('signInEmail', () => {
  it('adds the hidden domain to a username', () => {
    assert.equal(signInEmail('sarah'), 'sarah@silverloop.demo');
    assert.equal(signInEmail('demo-operator'), 'demo-operator@silverloop.demo');
  });

  it('uses a full email as it was typed', () => {
    assert.equal(signInEmail('Mei.Tan@Example.com'), 'Mei.Tan@Example.com');
    assert.equal(signInEmail('sarah@silverloop.demo'), 'sarah@silverloop.demo');
  });

  it('trims surrounding spaces from both', () => {
    assert.equal(signInEmail('  sarah \t'), 'sarah@silverloop.demo');
    assert.equal(signInEmail('  mei@example.com '), 'mei@example.com');
  });

  it('leaves a blank value blank instead of inventing an address', () => {
    assert.equal(signInEmail(''), '');
    assert.equal(signInEmail('   '), '');
  });
});
