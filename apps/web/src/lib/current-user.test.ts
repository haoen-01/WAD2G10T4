import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { createKeyedOnceLoader } from './current-user';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('createKeyedOnceLoader', () => {
  it('shares one in-flight read between callers with the same key', async () => {
    const loader = createKeyedOnceLoader<string>();
    let reads = 0;
    const pending = deferred<string>();
    const read = () => {
      reads += 1;
      return pending.promise;
    };
    const first = loader.load('token-a', read);
    const second = loader.load('token-a', read);
    assert.equal(first, second);
    pending.resolve('senior');
    assert.deepEqual(await Promise.all([first, second]), ['senior', 'senior']);
    assert.equal(reads, 1);
  });

  it('reuses a settled read for the same key', async () => {
    const loader = createKeyedOnceLoader<string>();
    let reads = 0;
    const read = async () => {
      reads += 1;
      return 'coordinator';
    };
    await loader.load('token-a', read);
    assert.equal(await loader.load('token-a', read), 'coordinator');
    assert.equal(reads, 1);
  });

  it('reads again for a different key', async () => {
    const loader = createKeyedOnceLoader<string>();
    let reads = 0;
    const read = async () => `read-${++reads}`;
    assert.equal(await loader.load('token-a', read), 'read-1');
    assert.equal(await loader.load('token-b', read), 'read-2');
    assert.equal(reads, 2);
  });

  it('forgets a failed read so the next caller tries again', async () => {
    const loader = createKeyedOnceLoader<string>();
    let reads = 0;
    const failing = async (): Promise<string> => {
      reads += 1;
      throw new Error('offline');
    };
    const first = loader.load('token-a', failing);
    const sharedFailure = loader.load('token-a', failing);
    await assert.rejects(first, /offline/);
    await assert.rejects(sharedFailure, /offline/);
    assert.equal(reads, 1);
    assert.equal(
      await loader.load('token-a', async () => 'senior'),
      'senior',
      'a later caller is not handed the earlier failure',
    );
  });

  it('does not let an older failure evict a newer read', async () => {
    const loader = createKeyedOnceLoader<string>();
    const older = deferred<string>();
    const olderRead = loader.load('token-a', () => older.promise);
    let newerReads = 0;
    const newer = () => {
      newerReads += 1;
      return Promise.resolve('newer');
    };
    await loader.load('token-b', newer);
    older.reject(new Error('expired'));
    await assert.rejects(olderRead, /expired/);
    await loader.load('token-b', newer);
    assert.equal(newerReads, 1);
  });

  it('reads again after clear()', async () => {
    const loader = createKeyedOnceLoader<string>();
    let reads = 0;
    const read = async () => `read-${++reads}`;
    await loader.load('token-a', read);
    loader.clear();
    assert.equal(await loader.load('token-a', read), 'read-2');
  });
});
