import type { MeResponse, MyGroup } from '@silverloop/api-client';
import { storeToRefs } from 'pinia';
import { computed } from 'vue';

import { useAuth } from '@/composables/useAuth';
import { demoSub } from '@/composables/useViewMode';
import { AUTH_ENABLED } from '@/lib/config';
import { activeGroups, identityKey, useSessionStore } from '@/stores/session';

/**
 * `GET /v1/me`, shared. The state lives in the Pinia session store (`stores/session.ts`); this file
 * keeps the names every screen and composable already uses, so they read and change that one store.
 * The module-level values (`currentGroup`) only touch Pinia when read, which is after the app has
 * installed it, so composables that are not components can keep importing them.
 */
export { activeGroups, identityKey };

/**
 * Who is looking right now, known at once (no request): the signed-in account, or the demo
 * account. Reactive, so state kept per person (the bell, the asks) can refuse to show what it
 * holds for someone else in the moment between a sign-out or a "Viewing as" switch and its re-read.
 */
export function viewerKey(): string {
  if (AUTH_ENABLED) return useAuth().currentUser.value?.sub ?? 'signed-out';
  return demoSub() ?? 'demo-default';
}

export function loadMe(force = false): Promise<MeResponse> {
  return useSessionStore().loadMe(force);
}

export function selectGroup(groupId: string): void {
  useSessionStore().selectGroup(groupId);
}

/** The group the family screens show: the chosen one if it is still theirs, else the first. */
export const currentGroup = computed<MyGroup | null>(() => useSessionStore().currentGroup);

export function useMe() {
  const store = useSessionStore();
  const { me, currentGroup, activeGroups, pendingGroups } = storeToRefs(store);
  return {
    me,
    loadMe: store.loadMe,
    currentGroup,
    activeGroups,
    selectGroup: store.selectGroup,
    pendingGroups,
  };
}
