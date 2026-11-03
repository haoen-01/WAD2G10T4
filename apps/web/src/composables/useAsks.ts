import type { HelperAsk } from '@silverloop/api-client';
import { computed, nextTick, ref } from 'vue';

import { announceFamilyChange, onFamilyChange } from '@/composables/useFamily';
import { currentGroup, loadMe, viewerKey } from '@/composables/useMe';
import { showToast } from '@/composables/useToast';
import { classifyApiError } from '@/lib/api-errors';
import { openAskFor } from '@/lib/asks';
import * as api from '@/services/careApi';

/**
 * The open asks of the family group on screen (a module singleton, like `useFamily`), for the
 * "Asked Emily · waiting" tags and the Yes / Can't go / Withdraw buttons.
 *
 * - State belongs to one group and one account (`key`): another group, or another demo "Viewing
 *   as" member, starts from none, so nobody sees the last person's "asked you".
 * - It is read when a screen that shows it opens, when the calendar's save queue drains or the demo
 *   switches member (`onFamilyChange`), and after every change made here. A change made here also
 *   re-reads the calendar, the bell and the feed (`announceFamilyChange`), since the API moves the
 *   helper and writes notifications in the same step.
 * - Imports nothing from motion or `@vueuse/core`: the bell (loaded from the layout) uses it too.
 * - Only family screens use it: the ask routes refuse a senior.
 */
const asks = ref<HelperAsk[]>([]);
const loaded = ref(false);
/** Whose asks `asks` are (group and person); nothing is shown for anyone else. */
const key = ref<string | null>(null);
let inFlight: Promise<void> | null = null;
let rerun = false;

const keyNow = () => `${currentGroup.value?.group_id ?? 'none'}|${viewerKey()}`;
/** The asks, but only while they belong to whoever is looking now (none mid-switch). */
const shown = computed<HelperAsk[]>(() => (key.value === keyNow() ? asks.value : []));

async function currentKey(): Promise<{ key: string; group: string | null }> {
  await loadMe().catch(() => null);
  return { key: keyNow(), group: currentGroup.value?.group_id ?? null };
}

async function readOnce(): Promise<void> {
  const here = await currentKey();
  if (here.key !== key.value) {
    key.value = here.key;
    asks.value = [];
    loaded.value = false;
  }
  if (!here.group) {
    loaded.value = true;
    return;
  }
  try {
    const open = await api.getOpenAsks(here.group);
    if (here.key !== key.value) return; // The group or the person changed meanwhile.
    asks.value = open;
    loaded.value = true;
  } catch {
    // The tags are extra: without them the day still shows that it needs a helper.
  }
}

/** Reads the open asks again. Calls made while a read is in flight share one follow-up read. */
export function refreshAsks(): Promise<void> {
  if (inFlight) {
    rerun = true;
    return inFlight;
  }
  inFlight = (async () => {
    try {
      do {
        rerun = false;
        await readOnce();
      } while (rerun);
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

onFamilyChange((change) => {
  if (change === 'viewer') {
    key.value = null;
    asks.value = [];
  }
  // Only once something has shown asks: the senior screen loads `useFamily` too.
  if (loaded.value || change === 'viewer') void refreshAsks();
});

/** The open ask for one day of an appointment, if any. Reactive: read it inside a computed. */
export function openAskOf(occurrenceId: string): HelperAsk | null {
  return openAskFor(shown.value, occurrenceId);
}

/**
 * Runs one ask change, then re-reads everything it touches. Resolves `true` when the API took it;
 * a refusal is shown as a toast in the API's own words (a 409 "This ask has already ended" too)
 * and everything is read again, so the screen shows what actually happened.
 */
async function change(work: () => Promise<unknown>, done?: string): Promise<boolean> {
  try {
    await work();
    if (done) showToast(done);
    return true;
  } catch (caught) {
    showToast(classifyApiError(caught).message);
    return false;
  } finally {
    // The calendar, then (through `onFamilyChange('saved')`) these asks, the bell and the feed.
    await announceFamilyChange();
    // And wait for the asks themselves, so the buttons only come back once they are current.
    await refreshAsks();
  }
}

/** Asks a named member to take one day. */
export function askMember(
  occurrenceId: string,
  member: { id: string; name: string },
): Promise<boolean> {
  const group = currentGroup.value?.group_id;
  if (!group) {
    showToast('Only family members in the group can ask someone.');
    return Promise.resolve(false);
  }
  return change(
    () => api.createAsk(group, occurrenceId, member.id),
    `Asked ${member.name}. You’ll see their answer in your bell.`,
  );
}

/** The asked member says yes (`true`) or can't go (`false`). `groupId`: the bell can answer any group's ask. */
export function answerAsk(
  groupId: string,
  askId: string,
  yes: boolean,
  about: { title: string; askerName: string },
): Promise<boolean> {
  return change(
    () => (yes ? api.acceptAsk(groupId, askId) : api.declineAsk(groupId, askId)),
    yes
      ? `You’re going to ${about.title}.`
      : `Thanks. ${about.askerName || 'They'} will know you can’t make it.`,
  );
}

/** The asker takes their ask back. */
export function withdrawAsk(ask: HelperAsk): Promise<boolean> {
  const group = currentGroup.value?.group_id;
  if (!group) return Promise.resolve(false);
  return change(
    () => api.withdrawAsk(group, ask.ask_id),
    `You withdrew your ask to ${ask.asked_name}.`,
  );
}

/**
 * Where focus goes after an ask control has done its job and replaced itself (Ask → Withdraw,
 * Withdraw → Ask someone, a yes → you're going), so it never drops to the page. Call it with the
 * control that was used, before the change; await the result after.
 *
 * - `[data-ask-scope]`: the card the control sat in. Focus goes to its first `[data-ask-focus]`
 *   control (the new Withdraw, Ask someone or Yes), else its `[data-ask-fallback]` (a line that
 *   says who is going), else the card itself.
 * - `[data-ask-region]`: the list or panel around it, for when the card has gone (a day that is now
 *   covered leaves the needs list): its `[data-ask-fallback]` (the heading), else the region.
 */
export function focusAfterAsk(control: Element | null): () => Promise<void> {
  const scope = control?.closest<HTMLElement>('[data-ask-scope]') ?? null;
  const region = control?.closest<HTMLElement>('[data-ask-region]') ?? null;
  return async () => {
    await nextTick();
    const pick = (root: HTMLElement, controls: boolean) =>
      (controls ? root.querySelector<HTMLElement>('[data-ask-focus]:not([disabled])') : null) ??
      root.querySelector<HTMLElement>('[data-ask-fallback]') ??
      root;
    const target = scope?.isConnected
      ? pick(scope, true)
      : region?.isConnected
        ? pick(region, false)
        : null;
    target?.focus();
  };
}

export function useAsks() {
  // Every screen that shows asks reads them fresh when it opens.
  void refreshAsks();
  return {
    asks: shown,
    loaded,
    refresh: refreshAsks,
    openAskOf,
    askMember,
    answerAsk,
    withdrawAsk,
  };
}
