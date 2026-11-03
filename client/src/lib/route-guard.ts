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
import { classifyApiError, type ApiErrorKind } from './api-errors';
import {
  GROUP_START_PATH,
  homeFor,
  isPathInView,
  isViewPath,
  viewForRole,
  type ViewMode,
} from './view-mode';

export const PROTECTED_PREFIXES = ['/senior', '/walk', '/calendar', '/family', '/watch'] as const;

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

// ---------------------------------------------------------------------------------------------
// Deciding a navigation, including when the API cannot be reached.
// ---------------------------------------------------------------------------------------------

/** One API read the guard made: the value, or what kind of failure it was (and its status). */
export type Attempt<T> =
  { ok: true; value: T } | { ok: false; kind: ApiErrorKind; status: number | null };

/** Runs one API read and reports its outcome instead of throwing (or hiding the failure). */
export async function attempt<T>(read: () => Promise<T>): Promise<Attempt<T>> {
  try {
    return { ok: true, value: await read() };
  } catch (caught) {
    const status =
      caught &&
      typeof caught === 'object' &&
      typeof (caught as { status?: unknown }).status === 'number'
        ? (caught as { status: number }).status
        : null;
    return { ok: false, kind: classifyApiError(caught).kind, status };
  }
}

/**
 * Whether a failed read means "Care+ cannot be reached or is not working right now" (no response,
 * a 5xx, stored data from an older version), as opposed to an answer about this person (a 401, a
 * 403, a refused request). Only the first kind shows the connection panel.
 */
export function isConnectionProblem(failure: {
  kind: ApiErrorKind;
  status: number | null;
}): boolean {
  if (failure.kind === 'unreachable' || failure.kind === 'stored_state') return true;
  return failure.kind === 'server' && (failure.status === null || failure.status >= 500);
}

/** The parts of `GET /v1/me` the guard reads. */
export interface MeSummary {
  needsOnboarding: boolean;
  activeGroups: number;
}

export interface AccessInput {
  authEnabled: boolean;
  /** Sign-in on: whether a session exists. Sign-in off: ignored. */
  hasSession: boolean;
  path: string;
  /** Sign-in off: the demo view chosen in this browser (or `null`). Sign-in on: ignored. */
  demoView: ViewMode | null;
  /** Sign-in on, with a session: `GET /v1/auth/me`. `null` when it was not asked. */
  currentUser: Attempt<{ role?: string | null }> | null;
  /** `GET /v1/me`, when `needsMe` said to read it; otherwise `null`. */
  me: Attempt<MeSummary> | null;
}

export type AccessDecision =
  | { action: 'allow' }
  | { action: 'redirect'; to: string }
  /** Care+ could not be reached: keep the URL and show the connection panel instead. */
  | { action: 'unreachable'; kind: ApiErrorKind };

const ALLOW: AccessDecision = { action: 'allow' };

/** Which view this navigation is for, from the inputs (sign-in on: the account's role). */
export function viewOf(input: Omit<AccessInput, 'me'>): ViewMode | null {
  if (!input.authEnabled) return input.demoView;
  if (!input.hasSession || !input.currentUser?.ok) return null;
  return viewForRole(input.currentUser.value.role);
}

/** Whether the guard must read `GET /v1/me` before `decideAccess` can decide. */
export function needsMe(input: Omit<AccessInput, 'me'>): boolean {
  if (!isViewPath(input.path)) return false;
  const user = input.currentUser;
  if (input.authEnabled && user && !user.ok) {
    if (user.kind === 'unauthorized' || isConnectionProblem(user)) return false;
  }
  const mode = viewOf(input);
  if (!mode) return input.authEnabled && input.hasSession;
  if (!isPathInView(mode, input.path)) return false;
  return mode === 'family' && input.path.toLowerCase() !== GROUP_START_PATH;
}

/** A failed read that should stop the navigation, or `null` to carry on. */
function failureDecision(read: Attempt<unknown> | null, path: string): AccessDecision | null {
  if (!read || read.ok) return null;
  if (isConnectionProblem(read)) return { action: 'unreachable', kind: read.kind };
  if (read.kind === 'unauthorized') return { action: 'redirect', to: loginPathFor(path) };
  return null;
}

/**
 * Where a navigation goes. Pure: `router/index.ts` gathers the inputs and acts on the answer.
 *
 * - Not one of the views' screens (sign-in, welcome, not found): allowed.
 * - Care+ unreachable, a 5xx, or stored data from an older version: the connection panel, never
 *   the sign-in page and never "join a family group".
 * - A real 401: the sign-in page, carrying `?next=`.
 * - Signed in with no role yet and `/v1/me` says so: finish signing up (`/welcome`).
 * - Another view's screen: your own start page.
 * - A family member: "join or create a family group" only when `/v1/me` really loaded and lists no
 *   active group.
 */
export function decideAccess(input: AccessInput): AccessDecision {
  const { path } = input;
  if (!isViewPath(path)) return ALLOW;

  if (input.authEnabled && input.hasSession) {
    const stop = failureDecision(input.currentUser, path);
    if (stop) return stop;
  }

  const mode = viewOf(input);
  if (!mode) {
    if (!input.authEnabled) return ALLOW;
    if (input.hasSession) {
      const stop = failureDecision(input.me, path);
      if (stop) return stop;
      if (input.me?.ok && input.me.value.needsOnboarding) {
        return { action: 'redirect', to: '/welcome' };
      }
    }
    return { action: 'redirect', to: loginPathFor(path) };
  }

  if (!isPathInView(mode, path)) return { action: 'redirect', to: homeFor(mode) };

  if (mode === 'family' && path.toLowerCase() !== GROUP_START_PATH) {
    const stop = failureDecision(input.me, path);
    if (stop) return stop;
    if (input.me?.ok && input.me.value.activeGroups === 0) {
      return { action: 'redirect', to: GROUP_START_PATH };
    }
  }
  return ALLOW;
}
