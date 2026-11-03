import { ref } from 'vue';
import type { LocationQuery, RouteLocationNormalized, Router } from 'vue-router';

import { refreshCurrentUser } from '@/composables/useAuth';
import { loadMe } from '@/composables/useMe';
import type { ApiErrorKind } from '@/lib/api-errors';

/**
 * "Can't connect to Care+ right now". Module-level state, like `useAuth`: the router guard sets it
 * when it could not reach the API (`decideAccess` says `unreachable`) and clears it on every
 * navigation; `AppLayout` shows the connection panel instead of the page while it is set. The URL
 * stays as it was, so "Try again" goes back to the same screen. No motion library here: `AppLayout`
 * must stay free of one.
 */
const problem = ref<ApiErrorKind | null>(null);
const retryTo = ref<{ path: string; query: LocationQuery; hash: string } | null>(null);
const retrying = ref(false);

export function clearConnectionProblem(): void {
  problem.value = null;
}

export function reportConnectionProblem(kind: ApiErrorKind, to: RouteLocationNormalized): void {
  problem.value = kind;
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
  return { problem, retrying, retry: retryConnection };
}
