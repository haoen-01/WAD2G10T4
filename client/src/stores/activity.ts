import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { defineStore } from 'pinia';
import { computed, ref, shallowRef } from 'vue';

import { viewerKey } from '@/composables/useMe';
import { percentOfUsual } from '@/lib/activity';
import { classifyApiError } from '@/lib/api-errors';
import { homeSeniorOf } from '@/lib/family-group';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { isSampleSource } from '@/lib/reading-days';
import { getPersonMetrics, getPersonState, getWearable } from '@/services/careApi';
import { useSessionStore } from '@/stores/session';

/** How long a load is reused by the next screen that asks (Home, then the Watch page). */
export const ACTIVITY_MAX_AGE_MS = 30_000;
const HISTORY_DAYS = 14;

/**
 * The senior's activity, shared by Home (its hero, 3D watch and fortnight chart) and the Watch page,
 * so both show the same reading from one set of requests: their status (`GET /v1/people/{id}/state`,
 * which carries the latest reading and the usual day), the last two weeks of daily readings and the
 * (simulated) watch's status.
 *
 * Read-only server data, never invented here: the steps, the usual day and the reading's own day
 * are the API's; the percentage is `percentOfUsual`, the same sum Home's sentence uses. Each part
 * fails on its own: without the history or the watch, the rest still shows.
 */
export const useActivityStore = defineStore('activity', () => {
  const session = useSessionStore();

  // ---- State ----
  /** The senior whose activity this is; null when the chosen group has no senior linked yet. */
  const personId = ref<string | null>(null);
  const person = shallowRef<PersonState | null>(null);
  /** The last two weeks of daily readings, oldest first; null until read (or when it failed). */
  const history = shallowRef<DailyMetric[] | null>(null);
  const wearable = shallowRef<WearableStatus | null>(null);
  const loading = ref(false);
  const loaded = ref(false);
  /** Why the senior's status could not be read, in plain words; null when it could. */
  const error = ref<string | null>(null);
  const historyFailed = ref(false);
  const wearableFailed = ref(false);
  // Whose view and when it was read, and the read in flight: bookkeeping, not state to show.
  let owner: string | null = null;
  let loadedAt = 0;
  let inFlight: Promise<void> | null = null;

  // ---- Getters ----
  /** True once loaded with no senior to show (the chosen group has none linked yet). */
  const noSenior = computed(() => loaded.value && personId.value === null);
  const steps = computed(() => person.value?.signal.current_steps ?? null);
  const usualSteps = computed(() => person.value?.baseline.median_steps ?? null);
  /** The latest reading as a share of the usual day, or null with no reading or no usual day. */
  const percentOfUsualDay = computed(() =>
    steps.value === null || usualSteps.value === null
      ? null
      : percentOfUsual(steps.value, usualSteps.value),
  );
  /** The day the latest reading is from (YYYY-MM-DD), so a screen can say when it is not today. */
  const readingDay = computed(() => person.value?.current_day ?? null);
  /** Sample (synthetic) readings, which every screen labels as such. */
  const isSample = computed(() => isSampleSource(person.value?.signal.quality.source));
  const latestDay = computed<DailyMetric | null>(
    () => history.value?.[history.value.length - 1] ?? null,
  );

  // ---- Actions ----
  /** Forgets everything read, so nothing of one person's view is shown to the next. */
  function reset(): void {
    personId.value = null;
    person.value = null;
    history.value = null;
    wearable.value = null;
    loading.value = false;
    loaded.value = false;
    error.value = null;
    historyFailed.value = false;
    wearableFailed.value = false;
    owner = null;
    loadedAt = 0;
    inFlight = null;
  }

  async function loadHistory(): Promise<void> {
    historyFailed.value = false;
    const id = personId.value;
    if (!id) return;
    try {
      const days = await getPersonMetrics(id, HISTORY_DAYS);
      if (personId.value === id) history.value = days;
    } catch {
      if (personId.value === id) historyFailed.value = true;
    }
  }

  async function loadWearable(): Promise<void> {
    wearableFailed.value = false;
    const id = personId.value;
    if (!id) {
      wearable.value = null;
      return;
    }
    try {
      const status = await getWearable(id);
      if (personId.value === id) wearable.value = status;
    } catch {
      if (personId.value === id) wearableFailed.value = true;
    }
  }

  /**
   * Reads the chosen senior's activity. A screen opening shares a read in flight, and reuses one
   * finished less than `ACTIVITY_MAX_AGE_MS` ago for the same viewer and senior; `force` always
   * reads again (Try again, or another senior picked). A different viewer starts from empty.
   */
  function load(options: { force?: boolean } = {}): Promise<void> {
    const viewer = viewerKey();
    if (owner !== null && owner !== viewer) reset();
    if (inFlight && !options.force) return inFlight;
    const fresh = loaded.value && Date.now() - loadedAt < ACTIVITY_MAX_AGE_MS;
    if (fresh && !options.force) {
      const wanted = homeSeniorOf(session.currentGroup, DEMO_PERSON_ID);
      if (wanted === personId.value) return Promise.resolve();
    }
    const run = (async () => {
      loading.value = true;
      error.value = null;
      try {
        await session.loadMe().catch(() => null);
        const id = homeSeniorOf(session.currentGroup, DEMO_PERSON_ID);
        if (id !== personId.value) {
          history.value = null;
          wearable.value = null;
        }
        personId.value = id;
        try {
          person.value = id ? await getPersonState(id) : null;
        } catch (caught) {
          person.value = null;
          error.value = classifyApiError(caught).message;
        }
        if (!person.value) history.value = null;
        owner = viewer;
        loadedAt = Date.now();
        loaded.value = true;
      } finally {
        loading.value = false;
      }
      // The extra detail, side by side; either can fail without the other.
      await Promise.all([loadWearable(), person.value ? loadHistory() : Promise.resolve()]);
    })();
    inFlight = run;
    void run.finally(() => {
      if (inFlight === run) inFlight = null;
    });
    return run;
  }

  return {
    // State
    personId,
    person,
    history,
    wearable,
    loading,
    loaded,
    error,
    historyFailed,
    wearableFailed,
    // Getters
    noSenior,
    steps,
    usualSteps,
    percentOfUsualDay,
    readingDay,
    isSample,
    latestDay,
    // Actions
    load,
    loadHistory,
    loadWearable,
    reset,
  };
});
