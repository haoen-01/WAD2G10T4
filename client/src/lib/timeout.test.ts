import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { classifyApiError } from './api-errors';
import { API_TIMEOUT_MS, RequestTimeoutError, withTimeout } from './timeout';

describe('withTimeout', () => {
  it('passes a value through when the work answers in time', async () => {
    assert.equal(await withTimeout(Promise.resolve('me'), 50), 'me');
  });

  it('passes the work’s own failure through unchanged', async () => {
    const failure = Object.assign(new Error('nope'), { status: 401 });
    await assert.rejects(withTimeout(Promise.reject(failure), 50), (caught) => caught === failure);
  });

  it('gives up on work that never answers, as unreachable', async () => {
    const never = new Promise<string>(() => undefined);
    await assert.rejects(withTimeout(never, 5), (caught) => {
      assert.ok(caught instanceof RequestTimeoutError);
      assert.equal((caught as RequestTimeoutError).status, 0);
      assert.equal(classifyApiError(caught).kind, 'unreachable');
      return true;
    });
  });

  it('waits as long as every other API call does', () => {
    assert.equal(API_TIMEOUT_MS, 15_000);
  });
});
