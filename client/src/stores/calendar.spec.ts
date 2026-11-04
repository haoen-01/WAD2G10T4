import type { FamilyCalendar, MeResponse } from '@silverloop/api-client';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

import * as api from '@/services/careApi';
import { useCalendarStore } from '@/stores/calendar';
import { useSessionStore } from '@/stores/session';

vi.mock('@/lib/config', () => ({ AUTH_ENABLED: false }));
vi.mock('@/composables/useViewMode', () => ({
  demoSub: () => 'demo-family',
  DEMO_FAMILY_SUBS: {},
  setDemoMember: vi.fn(),
  useViewMode: () => ({ mode: { value: 'family' } }),
}));
vi.mock('@/composables/useAuth', () => ({ getAccessToken: async () => null }));
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }));
vi.mock('@/services/careApi', () => ({
  getMe: vi.fn(),
  getGroupCalendar: vi.fn(),
  getCalendar: vi.fn(),
  volunteerFor: vi.fn(),
  updateAppointment: vi.fn(),
}));

const mocked = vi.mocked(api);

function me(groupIds: string[]): MeResponse {
  return {
    sub: 'demo-family',
    role: 'family',
    display_name: 'Sarah',
    person_id: null,
    needs_onboarding: false,
    groups: groupIds.map((id) => ({
      group_id: id,
      person_id: 'mdm-lim',
      senior_name: 'Mdm Lim',
      my_role: 'member',
      my_status: 'active',
      member_count: 2,
      last_opened: false,
      unread_count: 0,
    })),
  } as MeResponse;
}

function calendar(group: string, date = '2026-11-06', assignments: unknown[] = []): FamilyCalendar {
  return {
    person_id: 'mdm-lim',
    senior_name: 'Mdm Lim',
    group_id: group,
    from_date: '2026-11-01',
    to_date: '2026-12-01',
    members: [
      {
        member_id: 'm-sarah',
        display_name: 'Sarah',
        relationship: 'daughter',
        colour: 0,
        role: 'owner',
        status: 'active',
        is_me: true,
      },
    ],
    appointments: [
      {
        occurrence_id: `appt-1@${date}`,
        appointment_id: 'appt-1',
        title: 'Morning Tai Chi',
        kind: 'activity',
        date,
        start: '08:30',
        end: '09:30',
        location: null,
        notes: null,
        repeat: 'none',
      },
    ],
    availability: [],
    assignments,
  } as unknown as FamilyCalendar;
}

/** Lets the save queue drain and its read-back land. */
async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mocked.getMe.mockResolvedValue(me(['g1', 'g2']));
  mocked.getGroupCalendar.mockImplementation(async (group: string) => calendar(group));
  mocked.volunteerFor.mockResolvedValue(undefined as never);
  mocked.updateAppointment.mockResolvedValue(undefined as never);
});

describe('the calendar store', () => {
  it('starts empty and reads the chosen group’s calendar', async () => {
    const store = useCalendarStore();
    expect(store.appointments).toEqual([]);
    expect(store.loaded).toBe(false);

    await store.refresh();
    expect(mocked.getGroupCalendar).toHaveBeenCalledWith('g1');
    expect(store.loaded).toBe(true);
    expect(store.elderName).toBe('Mdm Lim');
    expect(store.appointments.map((item) => item.title)).toEqual(['Morning Tai Chi']);
  });

  it('“I’ll go” shows at once, is saved, and is read back from the API', async () => {
    const store = useCalendarStore();
    await store.refresh();
    store.state.currentMemberId = 'm-sarah';
    const id = store.appointments[0].id;

    store.volunteer(id);
    // Shown before the API has answered.
    expect(store.helperIdsOf(id)).toContain('m-sarah');
    await settle();
    expect(mocked.volunteerFor).toHaveBeenCalledWith('g1', id);
    expect(mocked.getGroupCalendar).toHaveBeenCalledTimes(2); // the read-back
  });

  it('moving an appointment to another day shows at once and saves it by its series', async () => {
    const store = useCalendarStore();
    await store.refresh();
    const appointment = store.appointments[0];
    mocked.getGroupCalendar.mockImplementation(async (group: string) =>
      calendar(group, '2026-11-09'),
    );

    void store.moveAppointment(appointment, '2026-11-09');
    expect(store.appointments[0].date).toBe('2026-11-09');
    await settle();
    expect(mocked.updateAppointment).toHaveBeenCalledWith(
      'g1',
      'appt-1',
      expect.objectContaining({ date: '2026-11-09', start: '08:30' }),
    );
    expect(store.appointments[0].id).toBe('appt-1@2026-11-09');
  });

  it('says why when the calendar cannot be read', async () => {
    mocked.getGroupCalendar.mockRejectedValueOnce(new Error('network down'));
    const store = useCalendarStore();
    await store.refresh();
    expect(store.error).toBeTruthy();
    expect(store.loaded).toBe(false);
  });

  it('picking another senior in the session reads their calendar', async () => {
    const store = useCalendarStore();
    await store.refresh();
    useSessionStore().selectGroup('g2');
    await nextTick();
    await settle();
    expect(mocked.getGroupCalendar).toHaveBeenLastCalledWith('g2');
    expect(store.groupId).toBe('g2');
  });
});
