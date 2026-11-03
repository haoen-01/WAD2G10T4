import type { NotificationItem, NotificationPage } from '@silverloop/api-client';
import { computed, getCurrentInstance, onBeforeUnmount, onMounted, ref } from 'vue';

import { announceFamilyChange, onFamilyChange } from '@/composables/useFamily';
import { viewerKey } from '@/composables/useMe';
import { classifyApiError } from '@/lib/api-errors';
import { markPageRead, mergeNotifications, newNotificationIds } from '@/lib/asks';
import * as api from '@/services/careApi';

/**
 * The bell's notifications (a module singleton, like `useFamilyActivity`), across all of the
 * member's family groups.
 *
 * - State belongs to one person (`key`: the signed-in or demo account, not the group, since the
 *   bell covers every group). What is held for anyone else is never shown, even for the moment
 *   before the re-read, and it is dropped when the last bell goes (sign-out, leaving the demo) and
 *   on a "Viewing as" switch, so Emily never sees Sarah's bell.
 * - While at least one bell is mounted (ref-counted) it re-reads every 30 s while the tab is
 *   visible, when the window gains focus and when the tab comes back, and pauses while hidden. One
 *   timer for the whole app, at most one request in flight; the bell also re-reads on a page change.
 * - Marking read shows at once. A read that was already on its way when something was marked is
 *   thrown away and done again, so it cannot bring the old badge back.
 * - A notification id it has not seen means someone else changed an ask: the calendar, the asks and
 *   the feed are read again (`announceFamilyChange`).
 * - Plain `setInterval` and listeners, no `@vueuse/core`: the layout loads the bell.
 */
const PAGE_SIZE = 20;
const POLL_MS = 30_000;

const empty = (): NotificationPage => ({ items: [], unread_count: 0, next_before: null });
const page = ref<NotificationPage>(empty());
/** Whose page `page` is; `null` before any read. */
const key = ref<string | null>(null);
const mine = computed(() => key.value !== null && key.value === viewerKey());
const items = computed<NotificationItem[]>(() => (mine.value ? page.value.items : []));
const unread = computed(() => (mine.value ? page.value.unread_count : 0));
const loadedFor = ref<string | null>(null);
const loaded = computed(() => loadedFor.value !== null && loadedFor.value === viewerKey());
const loadingMore = ref(false);
const error = ref<string | null>(null);

let known = new Set<string>();
let subscribers = 0;
let inFlight: Promise<void> | null = null;
let rerun = false;
/** Bumped by every mark-read, before and after it is saved (see `readFirstPage`). */
let readEpoch = 0;

function reset(): void {
  page.value = empty();
  known = new Set();
  loadedFor.value = null;
  error.value = null;
}

async function readFirstPage(): Promise<void> {
  const here = viewerKey();
  if (here !== key.value) {
    key.value = here;
    reset();
  }
  const epoch = readEpoch;
  try {
    const first = await api.getNotifications({ limit: PAGE_SIZE });
    if (here !== key.value) return; // Someone else is viewing now.
    if (epoch !== readEpoch) {
      rerun = true; // Marked read meanwhile: this answer may predate it.
      return;
    }
    const fresh = newNotificationIds(known, first.items);
    const wasLoaded = loadedFor.value === here;
    for (const item of first.items) known.add(item.notification_id);
    // Keep any older pages already shown below the first one.
    const older = page.value.items.filter(
      (item) => !first.items.some((next) => next.notification_id === item.notification_id),
    );
    page.value = {
      items: mergeNotifications(older, first.items),
      unread_count: first.unread_count,
      next_before: older.length ? page.value.next_before : first.next_before,
    };
    loadedFor.value = here;
    error.value = null;
    // Something happened elsewhere (asked, answered, closed): show it on every screen.
    if (wasLoaded && fresh.length) void announceFamilyChange();
  } catch (caught) {
    if (loadedFor.value !== here) error.value = classifyApiError(caught).message;
  }
}

/** Reads the first page again. Calls made while a read is in flight share one follow-up read. */
export function refreshNotifications(): Promise<void> {
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

async function showOlder(): Promise<void> {
  const cursor = page.value.next_before;
  if (!cursor || loadingMore.value) return;
  const startedFor = key.value;
  loadingMore.value = true;
  try {
    const older = await api.getNotifications({ limit: PAGE_SIZE, before: cursor });
    if (startedFor !== key.value) return;
    for (const item of older.items) known.add(item.notification_id);
    page.value = {
      items: mergeNotifications(page.value.items, older.items),
      unread_count: older.unread_count,
      next_before: older.next_before,
    };
  } catch (caught) {
    error.value = classifyApiError(caught).message;
  } finally {
    loadingMore.value = false;
  }
}

/**
 * Marks these notifications read at once, then tells the API; a refusal is put right by reading
 * again. Only ids the person has been shown: never "all", which would include ones not seen yet.
 */
async function markRead(ids: readonly string[]): Promise<void> {
  if (ids.length === 0 || !mine.value) return;
  readEpoch += 1;
  page.value = markPageRead(page.value, ids);
  try {
    await api.markNotificationsRead([...ids]);
  } catch {
    void refreshNotifications();
  } finally {
    readEpoch += 1;
  }
}

// ---- One timer and one set of listeners for the whole app ----
let timer: ReturnType<typeof setInterval> | null = null;
let wired = false;

function visible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

function startTimer(): void {
  if (timer === null) timer = setInterval(() => void refreshNotifications(), POLL_MS);
}

function stopTimer(): void {
  if (timer !== null) clearInterval(timer);
  timer = null;
}

function onFocus(): void {
  if (subscribers > 0) void refreshNotifications();
}

function onVisibility(): void {
  if (subscribers === 0) return;
  if (visible()) {
    void refreshNotifications();
    startTimer();
  } else {
    stopTimer();
  }
}

function ensureWiring(): void {
  if (wired) return;
  wired = true;
  window.addEventListener('focus', onFocus);
  document.addEventListener('visibilitychange', onVisibility);
  onFamilyChange((change) => {
    if (change === 'viewer') {
      key.value = null; // Another member: their own bell, from nothing.
      reset();
    }
    if (subscribers > 0) void refreshNotifications();
  });
}

function subscribe(): void {
  ensureWiring();
  subscribers += 1;
  void refreshNotifications();
  if (visible()) startTimer();
}

function unsubscribe(): void {
  subscribers = Math.max(0, subscribers - 1);
  if (subscribers > 0) return;
  stopTimer();
  // No bell left (signed out, left the demo, the senior's view): forget this person's page.
  key.value = null;
  reset();
}

export function useNotifications() {
  if (getCurrentInstance()) {
    onMounted(subscribe);
    onBeforeUnmount(unsubscribe);
  }
  return {
    items,
    unread,
    loaded,
    loadingMore,
    error,
    hasOlder: computed(() => mine.value && page.value.next_before !== null),
    refresh: refreshNotifications,
    showOlder,
    markRead,
  };
}
