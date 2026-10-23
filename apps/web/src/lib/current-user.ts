/**
 * One `GET /v1/auth/me` per access token, however many places ask.
 *
 * On a single page load the auth provider reads the session (`getSession`), Supabase then replays
 * the same session as `INITIAL_SESSION`, React's development double-mount runs both twice, and a
 * senior page asks again for its own `person_id`; sign-in adds a `SIGNED_IN` event alongside the
 * login page's own role check. Each of those used to be its own round trip for the same answer.
 *
 * The loader keeps the one latest read, keyed by the token it was made with: a caller asking with
 * the same token shares the in-flight or settled promise, a different token (a refresh, another
 * account) starts a new read, and a failed read is forgotten so the next caller tries again rather
 * than inheriting the failure. `clear()` is for sign-out and a 401.
 *
 * Generic and free of runtime imports so it can be unit-tested without the API client.
 */
export interface KeyedOnceLoader<T> {
  load(key: string, read: () => Promise<T>): Promise<T>;
  clear(): void;
}

export function createKeyedOnceLoader<T>(): KeyedOnceLoader<T> {
  let entry: { key: string; promise: Promise<T> } | null = null;
  return {
    load(key, read) {
      if (entry && entry.key === key) return entry.promise;
      const promise = read();
      const current = { key, promise };
      entry = current;
      // Marks the rejection handled here too; every caller still receives it from `promise`.
      promise.catch(() => {
        if (entry === current) entry = null;
      });
      return promise;
    },
    clear() {
      entry = null;
    },
  };
}
