/**
 * Bounding a request that may never answer. A server that accepts a connection and then says
 * nothing would otherwise leave whoever waits on it waiting forever (the router guard, for one,
 * leaving a blank page and no connection panel). Pure and import-free so `lib/timeout.test.ts` can
 * pin it under Node's type stripping.
 */

/**
 * How long to wait for the API before treating it as unreachable: the same 15 s the Axios instance
 * (`services/http.ts`) allows every other call.
 */
export const API_TIMEOUT_MS = 15_000;

/**
 * Thrown when the wait runs out. It carries `status: 0`, the same as a request that got no response
 * at all, so `classifyApiError` (`lib/api-errors.ts`) reads it as `unreachable`.
 */
export class RequestTimeoutError extends Error {
  readonly status = 0;

  constructor(ms: number) {
    super(`No answer within ${ms} ms`);
    this.name = 'RequestTimeoutError';
  }
}

/**
 * `work`'s result, or a `RequestTimeoutError` if it has not settled within `ms`. The timer is cleared
 * as soon as `work` settles either way, so nothing is left pending. The request itself is not
 * cancelled (the caller stops waiting for it; a late answer is ignored).
 */
export function withTimeout<T>(work: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new RequestTimeoutError(ms)), ms);
  });
  return Promise.race([work, expired]).finally(() => clearTimeout(timer));
}
