import type { MeResponse, MyGroup } from '@silverloop/api-client';
import { computed, ref, shallowRef } from 'vue';

import { getAccessToken } from '@/composables/useAuth';
import { demoSub } from '@/composables/useViewMode';
import { AUTH_ENABLED } from '@/lib/config';
import { getMe } from '@/services/careApi';

/**
 * `GET /v1/me`, shared: who is signed in, the seniors they care for and whether they still have to
 * finish signing up. One read per identity (the access token, or the demo account when sign-in is
 * off), so signing out, signing in as someone else or switching demo view reads it again without
 * anyone having to clear it. `loadMe(true)` reads it again after a change (joined, approved, …).
 */
const me = shallowRef<MeResponse | null>(null);
let cached: { key: string; promise: Promise<MeResponse> } | null = null;

/** Who the API sees: the access token, or the demo account when sign-in is off. */
export async function identityKey(): Promise<string> {
  if (AUTH_ENABLED) return (await getAccessToken()) ?? 'signed-out';
  return demoSub() ?? 'demo-default';
}

export async function loadMe(force = false): Promise<MeResponse> {
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
const selectedGroupId = ref<string | null>(readSelected());

export function selectGroup(groupId: string): void {
  selectedGroupId.value = groupId;
  try {
    window.localStorage.setItem(SELECTED_KEY, groupId);
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
}

/** The group the family screens show: the chosen one if it is still theirs, else the first. */
export const currentGroup = computed<MyGroup | null>(() => {
  const groups = activeGroups(me.value);
  return groups.find((group) => group.group_id === selectedGroupId.value) ?? groups[0] ?? null;
});

export function useMe() {
  return {
    me,
    loadMe,
    currentGroup,
    activeGroups: computed<MyGroup[]>(() => activeGroups(me.value)),
    selectGroup,
    pendingGroups: computed<MyGroup[]>(
      () => me.value?.groups?.filter((group) => group.my_status === 'pending') ?? [],
    ),
  };
}
