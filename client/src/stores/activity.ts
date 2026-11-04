import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { defineStore } from 'pinia';
import { computed, ref, shallowRef, watch } from 'vue';

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
  // The senior the read in flight was started for, and whether picking that senior started it (see
  // the watch below): a screen reacting to the same pick then shares it rather than reading twice.
  let inFlightWanted: string | null = null;
  let inFlightFromPick = false;
  // The senior the read in flight is actually reading, once it has looked at the chosen group
  // (after `loadMe`); `undefined` until then, when it will still read whoever is chosen by then.
  let inFlightReading: string | null | undefined = undefined;
  // Bumped by every read and by `reset`: a read that is no longer the latest writes nothing, so an
  // older answer landing last can never show the previous senior (or the previous person's view).
  let generation = 0;

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
    inFlightFromPick = false;
    inFlightReading = undefined;
    generation += 1;
  }

  /** Whether what a read started at `mine` for `id` got back may still be shown. */
  function current(mine: number, id: string): boolean {
    return mine === generation && personId.value === id;
  }

  async function loadHistory(): Promise<void> {
    historyFailed.value = false;
    const id = personId.value;
    if (!id) return;
    const mine = generation;
    try {
      const days = await getPersonMetrics(id, HISTORY_DAYS);
      if (current(mine, id)) history.value = days;
    } catch {
      if (current(mine, id)) historyFailed.value = true;
    }
  }

  async function loadWearable(): Promise<void> {
    wearableFailed.value = false;
    const id = personId.value;
    if (!id) {
      wearable.value = null;
      return;
    }
    const mine = generation;
    try {
      const status = await getWearable(id);
      if (current(mine, id)) wearable.value = status;
    } catch {
      if (current(mine, id)) wearableFailed.value = true;
    }
  }

  /**
   * Reads the chosen senior's activity. A screen opening shares a read in flight, and reuses one
   * finished less than `ACTIVITY_MAX_AGE_MS` ago for the same viewer and senior; `force` always
   * reads again (Try again, or another senior picked), except that it shares a read the store
   * itself started for that same pick. A different viewer starts from empty. Only the latest read
   * writes: an older one still in flight is dropped when it lands.
   */
  function load(options: { force?: boolean } = {}): Promise<void> {
    return start(options.force ?? false, false);
  }

  function start(force: boolean, fromPick: boolean): Promise<void> {
    const viewer = viewerKey();
    if (owner !== null && owner !== viewer) reset();
    const wanted = homeSeniorOf(session.currentGroup, DEMO_PERSON_ID);
    if (inFlight && (!force || (inFlightFromPick && inFlightWanted === wanted))) {
      return inFlight;
    }
    const fresh = loaded.value && Date.now() - loadedAt < ACTIVITY_MAX_AGE_MS;
    if (fresh && !force && wanted === personId.value) return Promise.resolve();
    const mine = ++generation;
    const run = (async () => {
      loading.value = true;
      error.value = null;
      try {
        await session.loadMe().catch(() => null);
        if (mine !== generation) return;
        const id = homeSeniorOf(session.currentGroup, DEMO_PERSON_ID);
        inFlightReading = id;
        if (id !== personId.value) {
          person.value = null;
          history.value = null;
          wearable.value = null;
        }
        personId.value = id;
        let next: PersonState | null = null;
        let problem: string | null = null;
        try {
          next = id ? await getPersonState(id) : null;
        } catch (caught) {
          problem = classifyApiError(caught).message;
        }
        if (mine !== generation) return;
        person.value = next;
        error.value = problem;
        if (!person.value) history.value = null;
        owner = viewer;
        loadedAt = Date.now();
        loaded.value = true;
      } finally {
        if (mine === generation) loading.value = false;
      }
      // The extra detail, side by side; either can fail without the other.
      await Promise.all([loadWearable(), person.value ? loadHistory() : Promise.resolve()]);
    })();
    inFlight = run;
    inFlightWanted = wanted;
    inFlightFromPick = fromPick;
    inFlightReading = undefined;
    void run.finally(() => {
      if (inFlight === run) {
        inFlight = null;
        inFlightFromPick = false;
        inFlightReading = undefined;
      }
    });
    return run;
  }

  // Picking another senior ("Whose care to show", on every page) reads theirs, whichever screen
  // is open, so the Watch page never keeps showing the first senior. Only once something has been
  // read or is being read: a store nobody has used yet reads nothing, and after `reset` (signing
  // out) nothing either. A pick while the first read is still on its way (the Watch page opened
  // first) reads the new senior too, rather than leaving the old one showing.
  watch(
    () => homeSeniorOf(session.currentGroup, DEMO_PERSON_ID),
    (next) => {
      if (inFlight) {
        // A read already on its way for this senior (Home's own watch), or one that has not yet
        // looked at the chosen group and so will read this one, is enough.
        if (inFlightReading === undefined || inFlightReading === next) return;
      } else if (!loaded.value || next === personId.value) {
        return;
      }
      void start(true, true);
    },
  );

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
