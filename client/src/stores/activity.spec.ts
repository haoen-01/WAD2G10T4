import type { DailyMetric, MeResponse, PersonState, WearableStatus } from '@silverloop/api-client';
import { createPinia, setActivePinia, storeToRefs } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick, watch } from 'vue';

import { percentOfUsual } from '@/lib/activity';
import * as api from '@/services/careApi';
import { useActivityStore } from '@/stores/activity';
import { useSessionStore } from '@/stores/session';

// Who is looking (the demo account) and what the API answers, per test.
let viewer = 'demo-family';
vi.mock('@/lib/config', () => ({ AUTH_ENABLED: false }));
vi.mock('@/composables/useViewMode', () => ({ demoSub: () => viewer }));
vi.mock('@/composables/useAuth', () => ({
  getAccessToken: async () => null,
  useAuth: () => ({ currentUser: { value: null } }),
}));
vi.mock('@/services/careApi', () => ({
  getMe: vi.fn(),
  getPersonState: vi.fn(),
  getPersonMetrics: vi.fn(),
  getWearable: vi.fn(),
}));

const mocked = vi.mocked(api);

function group(groupId: string, personId: string | null) {
  return {
    group_id: groupId,
    person_id: personId,
    senior_name: `Senior ${groupId}`,
    my_role: 'owner',
    my_status: 'active',
    member_count: 4,
    last_opened: false,
    unread_count: 0,
  };
}

function meWith(...groups: ReturnType<typeof group>[]): MeResponse {
  return {
    sub: viewer,
    role: 'family',
    display_name: 'Sarah',
    person_id: null,
    needs_onboarding: false,
    groups,
  } as MeResponse;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => (resolve = done));
  return { promise, resolve };
}

/** Lets watchers run and promises settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) await new Promise((done) => setTimeout(done, 0));
}

function me(personId: string | null): MeResponse {
  return {
    sub: viewer,
    role: 'family',
    display_name: 'Sarah',
    person_id: null,
    needs_onboarding: false,
    groups: [
      {
        group_id: 'g1',
        person_id: personId,
        senior_name: 'Mdm Lim',
        my_role: 'owner',
        my_status: 'active',
        member_count: 4,
        last_opened: true,
        unread_count: 0,
      },
    ],
  } as MeResponse;
}

function person(steps: number, usual: number, source = 'synthetic'): PersonState {
  return {
    person_id: 'mdm-lim',
    display_name: 'Mdm Lim',
    current_day: '2026-11-04',
    signal: { current_steps: steps, quality: { source } },
    baseline: { median_steps: usual },
  } as unknown as PersonState;
}

const DAYS: DailyMetric[] = [
  { day: '2026-11-03', steps: 5698, active_minutes: 41, wear_hours: 13, source: 'synthetic' },
  { day: '2026-11-04', steps: 5720, active_minutes: 40, wear_hours: 13.5, source: 'synthetic' },
];
const WATCH: WearableStatus = {
  connected: true,
  last_synced_at: null,
  battery_percent: 36,
  charging: false,
  source: 'synthetic',
};

beforeEach(() => {
  // A fresh Pinia for every test: nothing one test reads is seen by the next.
  setActivePinia(createPinia());
  vi.clearAllMocks();
  viewer = 'demo-family';
  mocked.getMe.mockResolvedValue(me('mdm-lim'));
  mocked.getPersonState.mockResolvedValue(person(5720, 5747));
  mocked.getPersonMetrics.mockResolvedValue(DAYS);
  mocked.getWearable.mockResolvedValue(WATCH);
});

describe('the activity store', () => {
  it('starts empty, with nothing invented', () => {
    const activity = useActivityStore();
    expect(activity.person).toBeNull();
    expect(activity.history).toBeNull();
    expect(activity.loaded).toBe(false);
    expect(activity.steps).toBeNull();
    expect(activity.percentOfUsualDay).toBeNull();
    expect(activity.noSenior).toBe(false);
  });

  it('loads the senior, their fortnight and their watch, and works out the same percentage', async () => {
    const activity = useActivityStore();
    await activity.load();

    expect(mocked.getPersonState).toHaveBeenCalledWith('mdm-lim');
    expect(mocked.getPersonMetrics).toHaveBeenCalledWith('mdm-lim', 14);
    expect(activity.steps).toBe(5720);
    expect(activity.usualSteps).toBe(5747);
    // The very same sum Home's sentence uses, not a copy of it.
    expect(activity.percentOfUsualDay).toBe(percentOfUsual(5720, 5747));
    expect(activity.readingDay).toBe('2026-11-04');
    expect(activity.isSample).toBe(true);
    expect(activity.latestDay?.steps).toBe(5720);
    expect(activity.wearable?.battery_percent).toBe(36);
  });

  it('is one store for every screen: what Home loads, the Watch page sees', async () => {
    const home = useActivityStore();
    const watchPage = useActivityStore();
    const { percentOfUsualDay } = storeToRefs(watchPage);
    const seen: (number | null)[] = [];
    watch(percentOfUsualDay, (value) => seen.push(value));

    await home.load();
    await nextTick();

    expect(watchPage).toBe(home);
    expect(seen).toEqual([100]);
  });

  it('shares a read in flight and reuses a fresh one; force reads again', async () => {
    const activity = useActivityStore();
    await Promise.all([activity.load(), activity.load()]);
    await activity.load();
    expect(mocked.getPersonState).toHaveBeenCalledTimes(1);

    mocked.getPersonState.mockResolvedValue(person(6100, 5747));
    await activity.load({ force: true });
    expect(mocked.getPersonState).toHaveBeenCalledTimes(2);
    expect(activity.steps).toBe(6100);
  });

  it('says why when the status cannot be read, and keeps the parts failing apart', async () => {
    const activity = useActivityStore();
    mocked.getPersonState.mockRejectedValueOnce(new Error('network down'));
    await activity.load();
    expect(activity.person).toBeNull();
    expect(activity.error).toBeTruthy();
    expect(activity.percentOfUsualDay).toBeNull();

    // The status reads again; the fortnight fails on its own and the rest still shows.
    mocked.getPersonMetrics.mockRejectedValueOnce(new Error('timeout'));
    await activity.load({ force: true });
    expect(activity.error).toBeNull();
    expect(activity.steps).toBe(5720);
    expect(activity.historyFailed).toBe(true);
    expect(activity.history).toBeNull();
  });

  it('shows no percentage without a usual day, and reads nothing when no senior is linked', async () => {
    const activity = useActivityStore();
    mocked.getPersonState.mockResolvedValue(person(5720, 0));
    await activity.load();
    expect(activity.steps).toBe(5720);
    expect(activity.percentOfUsualDay).toBeNull();

    mocked.getMe.mockResolvedValue(me(null));
    mocked.getPersonState.mockClear();
    await useSessionStore().loadMe(true);
    await activity.load({ force: true });
    expect(activity.noSenior).toBe(true);
    expect(activity.person).toBeNull();
    expect(mocked.getPersonState).not.toHaveBeenCalled();
  });

  it('starts from empty for another viewer, and reset forgets everything', async () => {
    const activity = useActivityStore();
    await activity.load();
    expect(activity.steps).toBe(5720);

    viewer = 'demo-john';
    mocked.getPersonState.mockResolvedValue(person(4000, 5747));
    await activity.load();
    expect(mocked.getPersonState).toHaveBeenCalledTimes(2);
    expect(activity.steps).toBe(4000);

    activity.reset();
    expect(activity.person).toBeNull();
    expect(activity.history).toBeNull();
    expect(activity.wearable).toBeNull();
    expect(activity.loaded).toBe(false);
  });

  it('follows the senior picked in the session, reading once even when a screen asks too', async () => {
    mocked.getMe.mockResolvedValue(meWith(group('g1', 'mdm-lim'), group('g2', 'mr-tan')));
    mocked.getPersonState.mockImplementation(async (id: string) => ({
      ...person(id === 'mr-tan' ? 3000 : 5720, 5747),
      person_id: id,
    }));
    const activity = useActivityStore();
    await activity.load();
    expect(activity.personId).toBe('mdm-lim');

    useSessionStore().selectGroup('g2');
    await nextTick();
    // Home's own watch asks for the same pick: it shares the store's read.
    void activity.load({ force: true });
    await settle();
    expect(activity.personId).toBe('mr-tan');
    expect(activity.steps).toBe(3000);
    expect(mocked.getPersonState).toHaveBeenCalledTimes(2);
    expect(mocked.getPersonState).toHaveBeenLastCalledWith('mr-tan');
    expect(mocked.getWearable).toHaveBeenLastCalledWith('mr-tan');
  });

  it('an older answer landing last never replaces the newer one', async () => {
    mocked.getMe.mockResolvedValue(meWith(group('g1', 'mdm-lim'), group('g2', 'mr-tan')));
    const first = deferred<PersonState>();
    const second = deferred<PersonState>();
    mocked.getPersonState
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const activity = useActivityStore();
    const s1 = activity.load();
    await settle();
    useSessionStore().selectGroup('g2');
    const s2 = activity.load({ force: true });
    await settle();

    second.resolve({ ...person(3000, 5747), person_id: 'mr-tan' });
    await s2;
    first.resolve({ ...person(5720, 5747), person_id: 'mdm-lim' });
    await s1;
    await settle();
    expect(activity.personId).toBe('mr-tan');
    expect(activity.person?.person_id).toBe('mr-tan');
    expect(activity.steps).toBe(3000);
  });

  it('a read in flight when reset runs writes nothing', async () => {
    const pending = deferred<PersonState>();
    const watchStatus = deferred<WearableStatus>();
    mocked.getPersonState.mockImplementationOnce(() => pending.promise);
    const activity = useActivityStore();
    const run = activity.load();
    await settle();

    activity.reset();
    pending.resolve(person(5720, 5747));
    await run;
    await settle();
    expect(activity.person).toBeNull();
    expect(activity.loaded).toBe(false);
    expect(activity.personId).toBeNull();

    // The same for the watch's status, still on its way when the person signs out.
    mocked.getWearable.mockImplementationOnce(() => watchStatus.promise);
    const again = activity.load();
    await settle();
    activity.reset();
    watchStatus.resolve(WATCH);
    await again;
    expect(activity.wearable).toBeNull();
    expect(activity.history).toBeNull();
  });

  it('after reset, picking another senior reads nothing', async () => {
    mocked.getMe.mockResolvedValue(meWith(group('g1', 'mdm-lim'), group('g2', 'mr-tan')));
    const activity = useActivityStore();
    await activity.load();
    activity.reset();
    mocked.getPersonState.mockClear();
    useSessionStore().selectGroup('g2');
    await settle();
    expect(mocked.getPersonState).not.toHaveBeenCalled();
  });
});
