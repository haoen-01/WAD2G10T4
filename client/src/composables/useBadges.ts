import { computed, nextTick, reactive, ref, watch, type Ref } from 'vue';

import { useMe } from '@/composables/useMe';
import { useWalk } from '@/composables/useWalk';
import {
  addWalk,
  BADGES_KEY,
  badgeState,
  claimTime,
  evaluateBadges,
  finishedWalk,
  isFirstLook,
  mergeStores,
  newlyEarned,
  readBadgeStore,
  saveBadgeStore,
  seenKey,
  withRemembered,
  type Audience,
  type BadgeResult,
  type BadgeState,
  type BadgeStore,
  type StepDay,
} from '@/lib/badges';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { getPersonMetrics } from '@/services/careApi';

/**
 * The walking badges for one senior: the badges worked out from her last 90 days of steps (read
 * through `careApi.ts`, the same readings as Home) and from walks finished on the Walk page, plus
 * which ones she has claimed and every badge she has ever earned (so none is ever taken away).
 *
 * All of that is kept in this browser only (`careplus.badges.v1`), unlike Tasks, which the API
 * stores for the family group. Badges are encouragement, not care data: nothing here is sent
 * anywhere or seen by the policy. Two tabs open at once share it: each joins in what the other
 * saved rather than writing over it.
 */

/** How many days of readings to look at (the API's most). */
export const BADGE_DAYS = 90;

const storage = (): Storage | null => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};
const NO_STORAGE = { getItem: () => null, setItem: () => {} };

const store = reactive<BadgeStore>(readBadgeStore(storage() ?? NO_STORAGE));
const plain = (): BadgeStore => JSON.parse(JSON.stringify(store)) as BadgeStore;

/** True while taking in another tab's save, so it is not written straight back. */
let takingIn = false;
watch(store, () => {
  if (takingIn) return;
  const place = storage();
  if (place) saveBadgeStore(place, mergeStores(readBadgeStore(place), plain()));
});

function takeIn(event: StorageEvent) {
  if (event.key !== BADGES_KEY) return;
  const place = storage();
  if (!place) return;
  takingIn = true;
  Object.assign(store, mergeStores(readBadgeStore(place), plain()));
  void nextTick(() => {
    takingIn = false;
  });
}
if (typeof window !== 'undefined') window.addEventListener('storage', takeIn);

// ---- Walks finished on the Walk page ----

const walk = useWalk();
const { me, currentGroup } = useMe();

/** Whose walk the demo watch is showing: her own when she is signed in, else the senior picked. */
const walker = computed(() =>
  me.value?.role === 'senior' && me.value.person_id
    ? me.value.person_id
    : (currentGroup.value?.person_id ?? DEMO_PERSON_ID),
);

watch(
  () => walk.demoState.value,
  (now, before) => {
    // Only the part she shared counts: the readings are kept only while she shares her walk.
    const done = finishedWalk(
      before,
      now,
      walk.sharing.value,
      walk.summary.value.distanceM,
      Date.now(),
    );
    if (!done) return;
    store.walks[walker.value] = addWalk(store.walks[walker.value] ?? [], done);
  },
);

// ---- Her steps ----

interface Readings {
  days: Ref<StepDay[] | null>;
  loading: Ref<boolean>;
  failed: Ref<boolean>;
  load: () => Promise<void>;
}

const readings = new Map<string, Readings>();

function readingsFor(personId: string): Readings {
  const known = readings.get(personId);
  if (known) return known;
  const days = ref<StepDay[] | null>(null);
  const loading = ref(false);
  const failed = ref(false);
  let inFlight: Promise<void> | null = null;
  const load = () => {
    inFlight ??= (async () => {
      loading.value = true;
      failed.value = false;
      try {
        days.value = (await getPersonMetrics(personId, BADGE_DAYS)).map((metric) => ({
          day: metric.day,
          steps: metric.steps,
        }));
      } catch {
        failed.value = true;
      } finally {
        loading.value = false;
        inFlight = null;
      }
    })();
    return inFlight;
  };
  const made = { days, loading, failed, load };
  readings.set(personId, made);
  return made;
}

export interface ShelfBadge extends BadgeResult {
  state: BadgeState;
  claimedAt: number | null;
}

export function useBadges(personId: Ref<string>) {
  const current = computed(() => readingsFor(personId.value));
  const walks = computed(() => store.walks[personId.value] ?? []);

  // Worked out afresh from the readings; earned ones are remembered below, so a badge earned from
  // days that later roll out of the 90 in view stays earned.
  const results = computed(() =>
    current.value.days.value === null
      ? null
      : evaluateBadges(current.value.days.value, walks.value),
  );
  watch(
    results,
    (now) => {
      // Walk badges count even before (or without) the steps.
      const earnedNow = now ?? evaluateBadges([], walks.value);
      const fresh = newlyEarned(earnedNow, store.earned[personId.value]);
      if (!fresh.length) return;
      store.earned[personId.value] = {
        ...(store.earned[personId.value] ?? {}),
        ...Object.fromEntries(fresh.map((badge) => [badge.id, badge])),
      };
    },
    { immediate: true },
  );

  const badges = computed<ShelfBadge[]>(() => {
    const claims = store.claims[personId.value] ?? {};
    // Until the steps are read (or if they cannot be), only walk badges and those already earned
    // are shown: a step goal is never shown as "0 steps" just because the steps are missing.
    const shown =
      results.value ?? evaluateBadges([], walks.value).filter((badge) => badge.group === 'walk');
    return withRemembered(shown, store.earned[personId.value]).map((badge) => ({
      ...badge,
      state: badgeState(badge, claims[badge.id]),
      claimedAt: badge.earned ? (claims[badge.id] ?? null) : null,
    }));
  });

  const readyCount = computed(() => badges.value.filter((badge) => badge.state === 'ready').length);

  /** Claims an earned badge. Returns false if it is not earned (nothing is claimed early). */
  function claim(id: string, now = Date.now()): boolean {
    const badge = badges.value.find((item) => item.id === id);
    if (!badge || badge.state !== 'ready') return false;
    store.claims[personId.value] = {
      ...(store.claims[personId.value] ?? {}),
      [id]: claimTime(badge, now),
    };
    return true;
  }

  /** Would opening this badge now be its first look since it was claimed? */
  function firstLook(id: string, audience: Audience): boolean {
    const badge = badges.value.find((item) => item.id === id);
    return isFirstLook(badge?.state === 'claimed', store.seen[personId.value], id, audience);
  }

  function markSeen(id: string, audience: Audience, at = Date.now()) {
    store.seen[personId.value] = {
      ...(store.seen[personId.value] ?? {}),
      [seenKey(id, audience)]: at,
    };
  }

  return {
    badges,
    readyCount,
    firstLook,
    markSeen,
    loading: computed(() => current.value.loading.value),
    failed: computed(() => current.value.failed.value),
    loaded: computed(() => current.value.days.value !== null),
    load: () => current.value.load(),
    claim,
  };
}
