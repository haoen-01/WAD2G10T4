import { ApiHttpError, type CurrentUser } from '@silverloop/api-client';
import type { Session } from '@supabase/supabase-js';
import { shallowReactive, toRefs } from 'vue';
import type { Router } from 'vue-router';

import { createApiClient } from '@/lib/client';
import { AUTH_ENABLED } from '@/lib/config';
import { createKeyedOnceLoader } from '@/lib/current-user';
import { attempt, loginPathFor } from '@/lib/route-guard';
import { getSupabase } from '@/lib/supabase';
import { isLoginPath, isViewPath } from '@/lib/view-mode';

/**
 * Who is signed in. A module singleton rather than provide/inject, so the router guard, the API
 * client's 401 hook and any component all read the same state.
 *
 * Supabase is used for the session only (see `lib/supabase.ts`); `GET /v1/auth/me` (through the
 * generated client) says which role that session has. When sign-in is off (the offline demo and the
 * e2e run) nothing here does anything: no session exists and none is needed.
 */
const state = shallowReactive<{
  /** True until the session has been read and, when there is one, the account looked up. */
  loading: boolean;
  session: Session | null;
  currentUser: CurrentUser | null;
}>({ loading: AUTH_ENABLED, session: null, currentUser: null });

/** Module-level, so a read made before a client-side navigation is still shared after it. */
const currentUserLoader = createKeyedOnceLoader<CurrentUser>();
/** The cache key when there is no token to key by (auth disabled, or no session yet). */
const NO_TOKEN_KEY = 'no-token';

let router: Router | null = null;
let started = false;
let resolveReady!: () => void;
/** Resolves once the stored session has been read, so the route guard can decide. */
const ready = new Promise<void>((resolve) => {
  resolveReady = resolve;
});

function readCurrentUser(accessToken: string | null): Promise<CurrentUser> {
  return currentUserLoader.load(accessToken ?? NO_TOKEN_KEY, () =>
    createApiClient(async () => accessToken).me(),
  );
}

export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!AUTH_ENABLED || !supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/**
 * A session can expire while someone sits on a normal-looking page: views fetch on mount and have
 * no way to notice on their own. The shared API client (`composables/useApi.ts`) calls this on any
 * 401, which clears local auth state and sends the person back to sign in. Its identity is stable:
 * it reads the current route when it is called.
 */
export function onUnauthorized(): void {
  const supabase = getSupabase();
  if (!AUTH_ENABLED || !supabase) return;
  currentUserLoader.clear();
  state.session = null;
  state.currentUser = null;
  const here = router?.currentRoute.value.path ?? '/';
  if (isLoginPath(here)) return;
  void supabase.auth.signOut();
  void router?.replace(loginPathFor(here));
}

export async function signOut(): Promise<void> {
  currentUserLoader.clear();
  await getSupabase()?.auth.signOut();
  state.session = null;
  state.currentUser = null;
  // Never leave the previous person's screen up on a shared device.
  if (router && isViewPath(router.currentRoute.value.path)) {
    await router.replace({ name: 'login' });
  }
}

/**
 * `GET /v1/auth/me`, shared: every caller asking with the same access token (the session events
 * below, the login page, a senior page resolving its `person_id`) gets the one read. Defaults to
 * the current session's token; the login page passes the token it just received. Rejects with the
 * client's `ApiHttpError`, and a 401 is reported through `onUnauthorized` exactly as `api.me()`
 * would have.
 */
export async function loadCurrentUser(accessToken?: string): Promise<CurrentUser> {
  const token = accessToken ?? (await getAccessToken());
  try {
    const user = await readCurrentUser(token);
    // Recorded for the nav and the guard too, but only when it is still the current session's
    // account: a read that resolves after a sign-out or a switch of account is not recorded.
    if (token === (state.session?.access_token ?? null) || (!AUTH_ENABLED && !accessToken)) {
      state.currentUser = user;
    }
    return user;
  } catch (caught) {
    // The shared read carries no 401 hook, so the caller that asked gets the same session-expired
    // handling every other call through the client gets.
    if (caught instanceof ApiHttpError && caught.status === 401) onUnauthorized();
    throw caught;
  }
}

let applySequence = 0;

/**
 * Records a session and looks the account up. A failed lookup records no account; the route guard
 * reads it again and tells "signed out" (a 401) from "Care+ can't be reached".
 */
async function apply(session: Session | null): Promise<void> {
  const mine = ++applySequence;
  state.session = session;
  const token = session?.access_token;
  if (!token) {
    state.currentUser = null;
    return;
  }
  const read = await attempt(() => readCurrentUser(token));
  if (mine === applySequence) state.currentUser = read.ok ? read.value : null;
}

/**
 * Read the account again for the current session, e.g. right after it has chosen `senior` or
 * `family`: until then `GET /v1/auth/me` refuses it, so no role was recorded.
 */
export async function refreshCurrentUser(): Promise<void> {
  currentUserLoader.clear();
  await apply(state.session);
}

/** Called once from `main.ts`, before the app mounts. */
export function initAuth(appRouter: Router): void {
  if (started) return;
  started = true;
  router = appRouter;
  const supabase = getSupabase();
  if (!AUTH_ENABLED || !supabase) {
    state.loading = false;
    resolveReady();
    return;
  }
  void supabase.auth.getSession().then(async ({ data }) => {
    // The guard only needs to know whether there is a session, so it is released before the
    // account lookup; `loading` (which the nav and senior pages wait on) stays true until then.
    const initial = apply(data.session);
    resolveReady();
    await initial;
    state.loading = false;
  });
  supabase.auth.onAuthStateChange((_event, session) => {
    void apply(session);
  });
}

export function useAuth() {
  return {
    ...toRefs(state),
    ready,
    signOut,
    getAccessToken,
    onUnauthorized,
    loadCurrentUser,
    refreshCurrentUser,
  };
}
