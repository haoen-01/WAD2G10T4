import { computed, ref } from 'vue';

import { useAuth } from '@/composables/useAuth';
import { AUTH_ENABLED } from '@/lib/config';
import { parseViewMode, viewForRole, type ViewMode } from '@/lib/view-mode';

/**
 * Which view is showing: the family's or the senior's (see `lib/view-mode.ts`).
 *
 * With sign-in on it follows the signed-in account's role. With sign-in off (the offline demo and
 * the e2e run) there is no account, so the sign-in pages offer a "continue as" button instead and
 * the choice is kept in this browser. Until someone chooses, the demo shows every screen, as it
 * always has.
 */
const STORAGE_KEY = 'careplus.demoView.v1';

function readDemoView(): ViewMode | null {
  try {
    return parseViewMode(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return null; // Storage blocked: nobody has chosen.
  }
}

const demoView = ref<ViewMode | null>(readDemoView());

/**
 * Sign-in off only: which demo family member this browser is (the calendar's "Viewing as"). The API
 * seeds all three in Mdm Lim's group; Sarah is the default.
 */
export const DEMO_FAMILY_SUBS: Record<string, string> = {
  Sarah: 'demo-family',
  John: 'demo-john',
  Emily: 'demo-emily',
};
const MEMBER_KEY = 'careplus.demoMember.v1';

function readDemoMember(): string | null {
  try {
    const saved = window.localStorage.getItem(MEMBER_KEY);
    return saved && Object.values(DEMO_FAMILY_SUBS).includes(saved) ? saved : null;
  } catch {
    return null;
  }
}

const demoMember = ref<string | null>(readDemoMember());

/** Sign-in off only: act as another demo family member. */
export function setDemoMember(sub: string | null): void {
  demoMember.value = sub;
  try {
    if (sub) window.localStorage.setItem(MEMBER_KEY, sub);
    else window.localStorage.removeItem(MEMBER_KEY);
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
}

function writeDemoView(mode: ViewMode | null): void {
  demoView.value = mode;
  try {
    if (mode) window.localStorage.setItem(STORAGE_KEY, mode);
    else window.localStorage.removeItem(STORAGE_KEY);
    if (!mode) setDemoMember(null);
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
}

/**
 * Sign-in off only: which demo account the API should act as (`X-Demo-Sub`). The API seeds both:
 * `demo-family` already owns Mdm Lim's family group, and `demo-senior` is Mdm Lim.
 */
export function demoSub(): string | null {
  if (AUTH_ENABLED) return null;
  if (demoView.value === 'senior') return 'demo-senior';
  // Not chosen yet: the API acts as Sarah then too, so "Viewing as" works before choosing.
  return demoMember.value ?? (demoView.value === 'family' ? 'demo-family' : null);
}

/** For the router guard: the view once sign-in has settled, or `null` when nobody is in. */
export async function resolveViewMode(): Promise<ViewMode | null> {
  if (!AUTH_ENABLED) return demoView.value;
  const { ready, session, currentUser, loadCurrentUser } = useAuth();
  await ready;
  if (!session.value) return null;
  const user = currentUser.value ?? (await loadCurrentUser().catch(() => null));
  return viewForRole(user?.role);
}

export function useViewMode() {
  const { currentUser } = useAuth();
  const mode = computed<ViewMode | null>(() =>
    AUTH_ENABLED ? viewForRole(currentUser.value?.role) : demoView.value,
  );
  return {
    mode,
    /** Sign-in off only: enter the demo as the family or the senior. */
    chooseDemoView: (next: ViewMode) => writeDemoView(next),
    /** Sign-in off only: leave the demo view, back to showing every screen. */
    leaveDemoView: () => writeDemoView(null),
  };
}
