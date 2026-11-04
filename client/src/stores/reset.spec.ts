import type { FamilyCalendar, MeResponse, PersonState } from '@silverloop/api-client';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '@/services/careApi';
import { useActivityStore } from '@/stores/activity';
import { useCalendarStore } from '@/stores/calendar';
import { clearViewerStores } from '@/stores/reset';
import { useSessionStore } from '@/stores/session';

vi.mock('@/lib/config', () => ({ AUTH_ENABLED: false }));
vi.mock('@/composables/useViewMode', () => ({
  demoSub: () => 'demo-family',
  DEMO_FAMILY_SUBS: {},
  setDemoMember: vi.fn(),
  useViewMode: () => ({ mode: { value: 'family' } }),
}));
vi.mock('@/composables/useMe', () => ({ viewerKey: async () => 'demo-family' }));
vi.mock('@/composables/useAuth', () => ({ getAccessToken: async () => null }));
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }));
vi.mock('@/services/careApi', () => ({
  getMe: vi.fn(),
  getGroupCalendar: vi.fn(),
  getCalendar: vi.fn(),
  getPersonState: vi.fn(),
  getPersonMetrics: vi.fn(),
  getWearable: vi.fn(),
}));

const mocked = vi.mocked(api);

const ME = {
  sub: 'demo-family',
  role: 'family',
  display_name: 'Sarah',
  person_id: null,
  needs_onboarding: false,
  groups: [
    {
      group_id: 'g1',
      person_id: 'mdm-lim',
      senior_name: 'Mdm Lim',
      my_role: 'member',
      my_status: 'active',
      member_count: 2,
      last_opened: false,
      unread_count: 0,
    },
  ],
} as MeResponse;

const CALENDAR = {
  person_id: 'mdm-lim',
  senior_name: 'Mdm Lim',
  group_id: 'g1',
  from_date: '2026-11-01',
  to_date: '2026-12-01',
  members: [],
  appointments: [
    {
      occurrence_id: 'appt-1@2026-11-06',
      appointment_id: 'appt-1',
      title: 'Morning Tai Chi',
      kind: 'activity',
      date: '2026-11-06',
      start: '08:30',
      end: '09:30',
      location: null,
      notes: null,
      repeat: 'none',
    },
  ],
  availability: [],
  assignments: [],
} as unknown as FamilyCalendar;

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mocked.getMe.mockResolvedValue(ME);
  mocked.getGroupCalendar.mockResolvedValue(CALENDAR);
});

describe('clearViewerStores', () => {
  it('clears the session, the activity and the calendar', async () => {
    const session = useSessionStore();
    const activity = useActivityStore();
    const calendar = useCalendarStore();
    await session.loadMe();
    await calendar.refresh();
    activity.$patch({ personId: 'mdm-lim', person: { person_id: 'mdm-lim' } as PersonState });
    activity.$patch({ loaded: true });
    expect(session.me).not.toBeNull();
    expect(calendar.appointments.length).toBe(1);

    clearViewerStores();

    expect(session.me).toBeNull();
    expect(activity.personId).toBeNull();
    expect(activity.person).toBeNull();
    expect(activity.loaded).toBe(false);
    expect(calendar.appointments).toEqual([]);
    expect(calendar.groupId).toBeNull();
    expect(calendar.loaded).toBe(false);

    // The next read is a fresh one, not the previous person's cached answer.
    await session.loadMe();
    expect(mocked.getMe).toHaveBeenCalledTimes(2);
  });

  it('does nothing before Pinia is active', async () => {
    const pinia = await import('pinia');
    setActivePinia(undefined as unknown as ReturnType<typeof createPinia>);
    expect(pinia.getActivePinia()).toBeUndefined();
    expect(() => clearViewerStores()).not.toThrow();
  });
});
