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
});
