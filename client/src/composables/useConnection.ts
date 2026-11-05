import { ref } from 'vue';
import type { LocationQuery, RouteLocationNormalized, Router } from 'vue-router';

import { refreshCurrentUser } from '@/composables/useAuth';
import { loadMe } from '@/composables/useMe';
import type { ApiErrorKind } from '@/lib/api-errors';

/**
 * "Can't connect to Care+ right now". Module-level state, like `useAuth`: the router guard sets it
 * when it could not reach the API (`decideAccess` says `unreachable`), and `AppLayout` shows the
 * connection panel instead of the page while it is set. The URL stays as it was, so "Try again"
 * goes back to the same screen. No motion library here: `AppLayout` must stay free of one.
 *
 * It is cleared only once a navigation the guard let through has been committed
 * (`settleConnectionProblem`, from the router's `afterEach`), never while the guards are still
 * running: clearing it earlier would let the layout render the route that is still current (the
 * one hidden behind the panel), which would mount and fetch before the navigation moved on. A
 * cancelled or failed navigation keeps the panel.
 */
const problem = ref<ApiErrorKind | null>(null);
const retryTo = ref<{ path: string; query: LocationQuery; hash: string } | null>(null);
const retrying = ref(false);
/** How many times "Try again" has failed since the panel appeared (it says "Still can't connect"). */
const failedRetries = ref(0);
/** The navigations the guard found Care+ unreachable for; they keep the panel once committed. */
let unreachableTargets = new WeakSet<RouteLocationNormalized>();

export function clearConnectionProblem(): void {
  problem.value = null;
  failedRetries.value = 0;
  unreachableTargets = new WeakSet();
}

/**
 * From the router's `afterEach`: once a navigation has been committed, the panel gives way unless
 * the guard reported Care+ unreachable for that very navigation. A failed or cancelled navigation
 * (`failed`) leaves everything as it was.
 */
export function settleConnectionProblem(to: RouteLocationNormalized, failed: boolean): void {
  if (failed || !problem.value || unreachableTargets.has(to)) return;
  clearConnectionProblem();
}

export function reportConnectionProblem(kind: ApiErrorKind, to: RouteLocationNormalized): void {
  if (problem.value && retrying.value) failedRetries.value += 1;
  problem.value = kind;
  unreachableTargets.add(to);
  retryTo.value = { path: to.path, query: to.query, hash: to.hash };
}

/** Reads the account and `/v1/me` again, then runs the guard for the same screen once more. */
export async function retryConnection(router: Router): Promise<void> {
  if (retrying.value) return;
  retrying.value = true;
  try {
    await refreshCurrentUser();
    // The guard reads it again and decides; a failure here is its to report.
    await loadMe(true).catch(() => undefined);
    const target = retryTo.value ?? { path: router.currentRoute.value.path, query: {}, hash: '' };
    await router.replace({ ...target, force: true });
  } finally {
    retrying.value = false;
  }
}

export function useConnection() {
  return { problem, retrying, failedRetries, retry: retryConnection };
}
