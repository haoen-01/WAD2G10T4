import type { MeResponse, MyGroup } from '@silverloop/api-client';
import { defineStore } from 'pinia';
import { computed, ref, shallowRef } from 'vue';

import { getAccessToken } from '@/composables/useAuth';
import { demoSub } from '@/composables/useViewMode';
import { AUTH_ENABLED } from '@/lib/config';
import { getMe } from '@/services/careApi';

/** Who the API sees: the access token, or the demo account when sign-in is off. */
export async function identityKey(): Promise<string> {
  if (AUTH_ENABLED) return (await getAccessToken()) ?? 'signed-out';
  return demoSub() ?? 'demo-default';
}

/** The groups this person is an active member of, in the order they joined. */
export function activeGroups(value: MeResponse | null): MyGroup[] {
  return value?.groups?.filter((group) => group.my_status === 'active') ?? [];
}

// Which senior the family screens show, when someone cares for more than one (the navbar picker).
// Kept per browser; a choice that is no longer one of their groups falls back to the first.
const SELECTED_KEY = 'careplus.selectedGroup.v1';
function readSelected(): string | null {
  try {
    return window.localStorage.getItem(SELECTED_KEY);
  } catch {
    return null;
  }
}

/**
 * The session: `GET /v1/me` (who is signed in, the seniors they care for, whether they still have
 * to finish signing up) and which of those seniors the family screens show. One read per identity
 * (the access token, or the demo account when sign-in is off), so signing out, signing in as
 * someone else or switching demo view reads it again; `loadMe(true)` reads it again after a change
 * (joined, approved, …). No token or password is kept here: only what `/v1/me` returns.
 */
export const useSessionStore = defineStore('session', () => {
  // ---- State ----
  const me = shallowRef<MeResponse | null>(null);
  const selectedGroupId = ref<string | null>(readSelected());
  // The read in flight or done, and whose it was. Not state: a promise is not something to show.
  let cached: { key: string; promise: Promise<MeResponse> } | null = null;

  // ---- Getters ----
  const groups = computed<MyGroup[]>(() => activeGroups(me.value));
  const pendingGroups = computed<MyGroup[]>(
    () => me.value?.groups?.filter((group) => group.my_status === 'pending') ?? [],
  );
  /** The group the family screens show: the chosen one if it is still theirs, else the first. */
  const currentGroup = computed<MyGroup | null>(
    () =>
      groups.value.find((group) => group.group_id === selectedGroupId.value) ??
      groups.value[0] ??
      null,
  );

  // ---- Actions ----
  async function loadMe(force = false): Promise<MeResponse> {
    const key = await identityKey();
    if (force || !cached || cached.key !== key) {
      const current = { key, promise: getMe() };
      cached = current;
      current.promise.then(
        (value) => {
          if (cached === current) me.value = value;
        },
        () => {
          // Forget a failed read, so the next caller tries again rather than inheriting it.
          if (cached === current) cached = null;
        },
      );
    }
    return cached.promise;
  }

  function selectGroup(groupId: string): void {
    selectedGroupId.value = groupId;
    try {
      window.localStorage.setItem(SELECTED_KEY, groupId);
    } catch {
      // Storage blocked: the choice lasts until the page reloads.
    }
  }

  /** Forgets who was signed in (signing out): nothing of theirs is shown to the next person. */
  function clear(): void {
    me.value = null;
    cached = null;
  }

  return {
    me,
    selectedGroupId,
    activeGroups: groups,
    pendingGroups,
    currentGroup,
    loadMe,
    selectGroup,
    clear,
  };
});
