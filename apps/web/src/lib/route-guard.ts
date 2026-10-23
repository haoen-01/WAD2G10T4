/**
 * Which routes need a signed-in session, and where a sign-in sends someone afterwards. Pure and
 * import-free so `lib/route-guard.test.ts` can pin it under Node's type stripping; the router's
 * `beforeEach` (`router/index.ts`) wires it to the auth composable.
 *
 * This is the old Next.js middleware's list, minus the screens that no longer exist (Care Team is
 * gone; `/care-team` redirects to `/calendar`, which is guarded; the Simulator is also gone), plus
 * the calendar and family screens. `/` (Overview) and `/login` are public, exactly as the
 * middleware's matcher had them. The guard is a courtesy, not the security boundary: every API
 * route enforces its own role check.
 */
export const PROTECTED_PREFIXES = ['/senior', '/calendar', '/family'] as const;

/**
 * Whether `pathname` is one of the protected sections or lives under one. Matches whole path
 * segments (so `/senior` covers `/senior/activities`, but a sibling such as `/seniors` is just a
 * 404), and ignores case because the router matches paths case-insensitively.
 */
export function isProtectedPath(pathname: string): boolean {
  const path = pathname.toLowerCase();
  return PROTECTED_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

/**
 * A same-origin absolute path that is safe to send someone back to after sign-in, or `null`.
 * Rejects an empty value, anything not starting with a single `/` (so `//evil.example` and
 * `https://evil.example` fail), a backslash (some browsers read `/\evil.example` as `//`) and
 * control characters (a tab or newline is stripped from a URL before it is parsed).
 */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//')) return null;
  if (/[\\\u0000-\u001f\u007f]/.test(raw)) return null;
  return raw;
}

/**
 * The `?next=` value for a sign-in redirect from `pathname`: the path alone (as the middleware did,
 * so no query string or hash is carried), or `/` when it is not a safe path.
 */
export function nextForPath(pathname: string): string {
  return safeNextPath(pathname) ?? '/';
}

/**
 * Where to send someone who is not signed in: `/login?next=<path>`, with the path percent-encoded
 * the way the old middleware wrote it (`%2Fcare-team`, not `/care-team`), so a bookmarked or shared
 * sign-in link looks the same as it always did. A string, not a `{ name, query }` location, because
 * the router would re-encode the query and leave the `/` bare.
 */
export function loginPathFor(pathname: string): string {
  return `/login?next=${encodeURIComponent(nextForPath(pathname))}`;
}

type QueryValue = string | number | boolean | null | undefined;

/**
 * A query string with every key and value percent-encoded strictly (`encodeURIComponent`), the way
 * `URLSearchParams` and the old Next.js app wrote them: `?next=%2Fcare-team`, never `?next=/care-team`.
 * The router's default leaves `/` bare and writes a space as `+`; both read back the same, but a
 * bookmarked or shared sign-in link should keep looking as it always did. An array repeats the key,
 * `null` writes the bare key, `undefined` is left out, and no query at all (the router may pass
 * none) is an empty string.
 */
export function stringifyStrictQuery(
  query: Record<string, QueryValue | ReadonlyArray<QueryValue>> | null | undefined,
): string {
  const parts: string[] = [];
  for (const [key, raw] of Object.entries(query ?? {})) {
    for (const value of Array.isArray(raw) ? raw : [raw]) {
      if (value === undefined) continue;
      const name = encodeURIComponent(key);
      parts.push(value === null ? name : `${name}=${encodeURIComponent(String(value))}`);
    }
  }
  return parts.join('&');
}
