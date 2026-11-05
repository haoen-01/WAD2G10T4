import type { MeResponse, MyGroup } from '@silverloop/api-client';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '@/services/careApi';
import { useSessionStore } from '@/stores/session';

let viewer = 'demo-family';
vi.mock('@/lib/config', () => ({ AUTH_ENABLED: false }));
vi.mock('@/composables/useViewMode', () => ({ demoSub: () => viewer }));
vi.mock('@/composables/useAuth', () => ({ getAccessToken: async () => null }));
vi.mock('@/services/careApi', () => ({ getMe: vi.fn() }));

const mocked = vi.mocked(api);

function group(id: string, status: MyGroup['my_status'] = 'active'): MyGroup {
  return {
    group_id: id,
    person_id: `senior-${id}`,
    senior_name: `Senior ${id}`,
    my_role: 'member',
    my_status: status,
    member_count: 2,
    last_opened: false,
    unread_count: 0,
  } as MyGroup;
}

function me(groups: MyGroup[]): MeResponse {
  return {
    sub: viewer,
    role: 'family',
    display_name: 'Sarah',
    person_id: null,
    needs_onboarding: false,
    groups,
  } as MeResponse;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  viewer = 'demo-family';
});

describe('the session store', () => {
  it('reads /v1/me once per person, and again for someone else', async () => {
    mocked.getMe.mockResolvedValue(me([group('g1')]));
    const session = useSessionStore();
    await session.loadMe();
    await session.loadMe();
    expect(mocked.getMe).toHaveBeenCalledTimes(1);
    expect(session.me?.display_name).toBe('Sarah');

    viewer = 'demo-john';
    await session.loadMe();
    expect(mocked.getMe).toHaveBeenCalledTimes(2);
  });

  it('shows the chosen senior, else the first, and lists pending groups apart', async () => {
    mocked.getMe.mockResolvedValue(me([group('g1'), group('g2'), group('g3', 'pending')]));
    const session = useSessionStore();
    await session.loadMe();
    expect(session.activeGroups.map((item) => item.group_id)).toEqual(['g1', 'g2']);
    expect(session.pendingGroups.map((item) => item.group_id)).toEqual(['g3']);
    expect(session.currentGroup?.group_id).toBe('g1');

    session.selectGroup('g2');
    expect(session.currentGroup?.group_id).toBe('g2');
    // A choice that is not one of their groups falls back to the first.
    session.selectGroup('gone');
    expect(session.currentGroup?.group_id).toBe('g1');
  });

  it('forgets a failed read, and clear() forgets who was signed in', async () => {
    mocked.getMe.mockRejectedValueOnce(new Error('offline'));
    const session = useSessionStore();
    await expect(session.loadMe()).rejects.toThrow('offline');
    mocked.getMe.mockResolvedValue(me([group('g1')]));
    await session.loadMe();
    expect(mocked.getMe).toHaveBeenCalledTimes(2);

    session.clear();
    expect(session.me).toBeNull();
    expect(session.currentGroup).toBeNull();
  });
});
