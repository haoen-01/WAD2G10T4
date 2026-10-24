import { useEventListener, useIntervalFn } from '@vueuse/core';
import type { CheckInKind, FamilyActivityEntry } from '@silverloop/api-client';
import { effectScope, getCurrentInstance, onBeforeUnmount, onMounted, ref } from 'vue';

import { onFamilyChange } from '@/composables/useFamily';
import { currentGroup, loadMe } from '@/composables/useMe';
import { demoSub } from '@/composables/useViewMode';
import { classifyApiError } from '@/lib/api-errors';
import { mergeActivity } from '@/lib/family-feed';
import * as api from '@/services/careApi';

/**
 * The family activity feed on Home (a module singleton, like `useFamily`).
 *
 * - State belongs to one group and one demo account (`key`); another group or another "Viewing as"
 *   member starts from an empty feed, so nobody sees the previous person's "You".
 * - While at least one screen uses it (ref-counted), it re-reads the first page every 30 s, when
 *   the window gains focus and when the tab becomes visible again, and pauses while the tab is
 *   hidden. There is one timer for the whole app and at most one request in flight; a refresh asked
 *   for meanwhile runs once when that request ends.
 * - Entries never change, so a re-read is merged by `activity_id`.
 * - Only family screens use it: the family routes refuse a senior.
 */
const PAGE_SIZE = 20;
const POLL_MS = 30_000;

const entries = ref<FamilyActivityEntry[]>([]);
const nextBefore = ref<string | null>(null);
const loaded = ref(false);
const loading = ref(false);
const loadingMore = ref(false);
const error = ref<string | null>(null);
const hasGroup = ref(true);

let key: string | null = null;
let subscribers = 0;
let inFlight: Promise<void> | null = null;
let rerun = false;
let pendingCount = 0;

async function currentKey(): Promise<{ key: string; group: string | null }> {
  await loadMe().catch(() => null);
  const group = currentGroup.value?.group_id ?? null;
  return { key: `${group ?? 'none'}|${demoSub() ?? 'self'}`, group };
}

function reset(): void {
  entries.value = [];
  nextBefore.value = null;
  loaded.value = false;
  error.value = null;
}

async function readFirstPage(): Promise<void> {
  const here = await currentKey();
  if (here.key !== key) {
    key = here.key;
    reset();
  }
  hasGroup.value = here.group !== null;
  if (!here.group) {
    loaded.value = true;
    return;
  }
  loading.value = !loaded.value;
  try {
    const page = await api.getGroupActivity(here.group, { limit: PAGE_SIZE });
    if (key !== here.key) return; // The group or the person changed meanwhile.
    const first = !loaded.value;
    entries.value = mergeActivity(entries.value, page.entries);
    if (first) nextBefore.value = page.next_before;
    loaded.value = true;
    error.value = null;
  } catch (caught) {
    // A failed re-read while entries are showing is not worth interrupting anyone for.
    if (!loaded.value) error.value = classifyApiError(caught).message;
  } finally {
    loading.value = false;
  }
}

/** Reads the first page again. Calls made while a read is in flight share one follow-up read. */
export function refreshActivity(): Promise<void> {
  if (inFlight) {
    rerun = true;
    return inFlight;
  }
  inFlight = (async () => {
    try {
      do {
        rerun = false;
        await readFirstPage();
      } while (rerun);
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

async function showMore(): Promise<void> {
  if (!nextBefore.value || loadingMore.value) return;
  if (inFlight) await inFlight;
  const group = currentGroup.value?.group_id;
  const cursor = nextBefore.value;
  const startedFor = key;
  if (!group || !cursor) return;
  loadingMore.value = true;
  try {
    const page = await api.getGroupActivity(group, { limit: PAGE_SIZE, before: cursor });
    if (key !== startedFor) return;
    entries.value = mergeActivity(entries.value, page.entries);
    nextBefore.value = page.next_before;
  } catch (caught) {
    error.value = classifyApiError(caught).message;
  } finally {
    loadingMore.value = false;
  }
}

/** Says "I called / visited / messaged" to the group. Shows at once; throws if it was refused. */
async function submitCheckIn(
  kind: CheckInKind,
  note: string,
  actor: { id: string; name: string },
): Promise<void> {
  const group = currentGroup.value?.group_id;
  if (!group) throw new Error('Join a family group first.');
  pendingCount += 1;
  const temp: FamilyActivityEntry = {
    activity_id: `pending-${pendingCount}`,
    kind: 'check_in',
    at: new Date().toISOString(),
    actor_member_id: actor.id,
    actor_name: actor.name,
    is_me: true,
    subject_name: null,
    appointment_id: null,
    appointment_title: null,
    appointment_kind: null,
    on_date: null,
    occurrence_id: null,
    check_in_kind: kind,
    note: note || null,
    origin: 'live',
  };
  const startedFor = key;
  entries.value = mergeActivity(entries.value, [temp]);
  try {
    const saved = await api.checkIn(group, { kind, note: note || null });
    if (key === startedFor) {
      entries.value = mergeActivity(
        entries.value.filter((entry) => entry.activity_id !== temp.activity_id),
        [saved],
      );
    }
  } catch (caught) {
    entries.value = entries.value.filter((entry) => entry.activity_id !== temp.activity_id);
    throw caught;
  }
}

// ---- One timer and one set of listeners for the whole app ----
const scope = effectScope(true);
let poll: ReturnType<typeof useIntervalFn> | null = null;

function visible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

function ensureWiring(): void {
  if (poll) return;
  scope.run(() => {
    poll = useIntervalFn(() => void refreshActivity(), POLL_MS, { immediate: false });
    useEventListener(window, 'focus', () => {
      if (subscribers > 0) void refreshActivity();
    });
    useEventListener(document, 'visibilitychange', () => {
      if (subscribers === 0 || !poll) return;
      if (visible()) {
        void refreshActivity();
        poll.resume();
      } else {
        poll.pause();
      }
    });
    onFamilyChange((change) => {
      if (subscribers === 0) return;
      if (change === 'viewer') {
        key = null; // Another member: start from nothing, not from the last person's "You".
        reset();
      }
      void refreshActivity();
    });
  });
}

function subscribe(): void {
  ensureWiring();
  subscribers += 1;
  if (subscribers === 1) {
    void refreshActivity();
    if (visible()) poll?.resume();
  } else {
    void refreshActivity();
  }
}

function unsubscribe(): void {
  subscribers = Math.max(0, subscribers - 1);
  if (subscribers === 0) poll?.pause();
}

/** `subscribe: false` reads and changes the feed without keeping it live (the check-in card). */
export function useFamilyActivity(options: { subscribe?: boolean } = {}) {
  if (options.subscribe !== false && getCurrentInstance()) {
    onMounted(subscribe);
    onBeforeUnmount(unsubscribe);
  }
  return {
    entries,
    nextBefore,
    loaded,
    loading,
    loadingMore,
    error,
    hasGroup,
    refresh: refreshActivity,
    showMore,
    checkIn: submitCheckIn,
  };
}
