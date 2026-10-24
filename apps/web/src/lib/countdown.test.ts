import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { expiryLabel } from './countdown';

describe('expiryLabel', () => {
  it('is minutes and seconds in the last hour', () => {
    assert.equal(expiryLabel(600), 'Expires in 10:00');
    assert.equal(expiryLabel(59), 'Expires in 0:59');
    assert.equal(expiryLabel(3599), 'Expires in 59:59');
  });

  it('is coarse above an hour', () => {
    assert.equal(expiryLabel(3600), 'Expires in 1 hour');
    assert.equal(expiryLabel(5 * 3600 + 59), 'Expires in 5 hours');
    assert.equal(expiryLabel(47 * 3600), 'Expires in 47 hours');
    assert.equal(expiryLabel(7 * 86400), 'Expires in 7 days');
  });

  it('says expired at zero, below zero and for nonsense', () => {
    assert.equal(expiryLabel(0), 'Code expired');
    assert.equal(expiryLabel(-5), 'Code expired');
    assert.equal(expiryLabel(Number.NaN), 'Code expired');
  });
});
