<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue';
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router';

import AssistantDock from '@/components/assistant/AssistantDock.vue';
import ConnectionProblem from '@/components/layout/ConnectionProblem.vue';
import LivingBackground from '@/components/layout/LivingBackground.vue';
import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import DisplayControls from '@/components/ui/DisplayControls.vue';
import MainNav from '@/components/ui/MainNav.vue';
import SettingsMenu from '@/components/ui/SettingsMenu.vue';
import CheckInBanner from '@/components/walk/CheckInBanner.vue';
import { useAuth } from '@/composables/useAuth';
import { useConnection } from '@/composables/useConnection';
import { useMe } from '@/composables/useMe';
import { useViewMode } from '@/composables/useViewMode';
import { useWalk } from '@/composables/useWalk';
import { AUTH_ENABLED } from '@/lib/config';
import { homeFor, isLoginPath, isPathInView, isSignedIn } from '@/lib/view-mode';
import { clearViewerStores } from '@/stores/reset';

const { loading, session, currentUser, signOut } = useAuth();
// Set by the router guard when it could not reach Care+: the connection panel shows instead of the
// page (and the menu, the bell and Kaki step aside) until a retry gets through.
const { problem } = useConnection();
const { mode, leaveDemoView } = useViewMode();
// A family member caring for more than one senior picks whose care the screens show.
const { activeGroups, currentGroup, selectGroup, loadMe } = useMe();
function pickSenior(event: Event) {
  selectGroup((event.target as HTMLSelectElement).value);
}
const router = useRouter();
const route = useRoute();

// The walk check-in: a banner on the family's screens (not the Walk page, which shows it itself),
// and a dot on the Walk link while one is waiting. A notification click opens the Walk page.
const walk = useWalk();
walk.setNavigator((path) => void router.push(path));
const showCheckIn = computed(
  () => mode.value !== 'senior' && route.path !== '/walk' && !isLoginPath(route.path),
);
const navDots = computed((): Record<string, string> =>
  walk.openAlert.value ? { '/walk': '(a check-in is waiting)' } : {},
);

const ALL_LINKS: { to: string; label: string; exact: boolean; icon: IconName }[] = [
  { to: '/', label: 'Home', exact: true, icon: 'home' },
  { to: '/senior', label: 'My day', exact: false, icon: 'person' },
  { to: '/watch', label: 'Watch', exact: false, icon: 'watch' },
  { to: '/walk', label: 'Walk', exact: false, icon: 'walk' },
  { to: '/calendar', label: 'Calendar', exact: false, icon: 'calendar' },
  { to: '/family', label: 'Family', exact: false, icon: 'users' },
];

// The family sees Home, Watch, Walk, Calendar and Family; the senior sees only their own screen.
// Nobody signed in sees none, except with sign-in off and no demo view chosen, when every screen is
// listed. Hiding a link is only for tidiness: the API checks each person's role and group on every
// call behind these screens (the calendar and family data included).
const links = computed(() => {
  // No menu over the connection panel: none of those screens can load until Care+ is reached.
  if (problem.value) return [];
  const current = mode.value;
  if (current) return ALL_LINKS.filter((link) => isPathInView(current, link.to));
  return AUTH_ENABLED ? [] : ALL_LINKS;
});

const brandTo = computed(() => (mode.value ? homeFor(mode.value) : '/'));
const VIEW_NAMES = { family: 'Family', senior: 'Senior' } as const;

/**
 * Signing out (or leaving the demo view): the shared stores forget this person first, so nothing of
 * theirs (who they are, the senior's readings, the family calendar) is shown to whoever comes next.
 */
function leave() {
  clearViewerStores();
  void (AUTH_ENABLED ? signOut() : leaveDemo());
}

/** Sign-in off: leave the demo view and go back to choosing one. */
async function leaveDemo() {
  leaveDemoView();
  await router.replace({ name: 'login' });
}

// While the connection panel shows, the account read itself may be what failed, so a session is
// enough to offer Sign out (never "Sign in" to someone who is signed in).
const signedIn = computed(() =>
  isSignedIn({
    authEnabled: AUTH_ENABLED,
    mode: mode.value,
    connectionProblem: problem.value !== null,
    hasSession: !!session.value,
    hasCurrentUser: !!currentUser.value,
  }),
);

// The notification bell: family view only, once this person is an active member of a group (the
// senior never gets one). Its own chunk, loaded only when it shows, so the layout stays small.
const NotificationBell = defineAsyncComponent(
  () => import('@/components/family/NotificationBell.vue'),
);
const showBell = computed(
  () =>
    mode.value === 'family' &&
    signedIn.value &&
    activeGroups.value.length > 0 &&
    !isLoginPath(route.path) &&
    !problem.value,
);
// Every family screen reads `/v1/me` anyway; this only makes sure the bell knows on any page.
watch(
  [mode, signedIn],
  ([currentMode, isIn]) => {
    if (currentMode === 'family' && isIn) void loadMe().catch(() => null);
  },
  { immediate: true },
);
// Kaki, the Care+ assistant: on every screen once someone is in (senior or family), never on the
// sign-in screens.
const showAssistant = computed(
  () => signedIn.value && !!mode.value && !isLoginPath(route.path) && !problem.value,
);
const ready = computed(() => !AUTH_ENABLED || !loading.value);

/*
 * Keeping the header and menu in reach. Two shells:
 * - The family's (`showTabs`): one slim frosted row that stays pinned. Its menu is a floating pill
 *   inside that row on a wide screen, and a fixed tab bar outside the header on a phone (a backdrop
 *   filter would trap a fixed child). Display settings and Sign out sit in the Settings popover.
 * - The senior's: the plain top bar. On a phone the menu is a second row; the brand row scrolls away
 *   and the menu row stays pinned, using a negative `top` equal to the height above the menu
 *   (`--sl-tuck`, measured here because it changes with zoom and wrapping).
 * `--sl-pinned-height` (what stays on screen) lets in-page jump links stop below the bar.
 */
const showTabs = computed(() => mode.value !== 'senior' && links.value.length > 0);
const header = ref<HTMLElement | null>(null);
const nav = ref<{ $el: HTMLElement } | null>(null);
const PHONE = '(max-width: 767.98px)';
let resizeObserver: ResizeObserver | null = null;
let phoneQuery: MediaQueryList | null = null;
const root = document.documentElement;
// The family's menu is in the header on a wide screen and a bottom bar on a phone.
const wide = ref(window.matchMedia(PHONE).matches === false);

function onViewport() {
  wide.value = !(phoneQuery?.matches ?? false);
  measure();
}

function measure() {
  const bar = header.value;
  if (!bar) return;
  const onPhone = phoneQuery?.matches ?? false;
  const tuck = !showTabs.value && onPhone && nav.value ? nav.value.$el.offsetTop : 0;
  bar.style.setProperty('--sl-tuck', `${tuck}px`);
  root.style.setProperty('--sl-pinned-height', `${bar.offsetHeight - tuck}px`);
}

// Once a retry gets through, the panel (and the Try again button that had focus) goes away; focus
// moves to the page rather than being left on nothing.
watch(problem, async (now, before) => {
  if (!before || now) return;
  await nextTick();
  if (document.activeElement === document.body || document.activeElement === null) {
    document.getElementById('main')?.focus({ preventScroll: true });
  }
});

watch([showTabs, wide], async () => {
  await nextTick();
  measure();
});

onMounted(() => {
  phoneQuery = window.matchMedia(PHONE);
  phoneQuery.addEventListener('change', onViewport);
  if (typeof ResizeObserver !== 'undefined' && header.value) {
    resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(header.value);
  }
  onViewport();
});

onBeforeUnmount(() => {
  phoneQuery?.removeEventListener('change', onViewport);
  resizeObserver?.disconnect();
  root.style.removeProperty('--sl-pinned-height');
});
</script>

<template>
  <div class="shell d-flex flex-column min-vh-100" :class="{ 'shell--tabs': showTabs }">
    <a class="visually-hidden-focusable" href="#main">Skip to content</a>
    <LivingBackground />

    <header ref="header" class="topbar">
      <div class="container topbar-inner">
        <RouterLink class="brand" :to="brandTo">
          <svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="11" fill="none" stroke="currentColor" stroke-width="5" />
            <circle
              cx="16"
              cy="16"
              r="11"
              fill="none"
              stroke="var(--sl-sun)"
              stroke-width="5"
              stroke-linecap="round"
              stroke-dasharray="17 52"
              transform="rotate(-90 16 16)"
            />
          </svg>
          <span class="brand-name">Care<span class="brand-plus">+</span></span>
        </RouterLink>

        <!-- The senior's one link stays in the top bar; the family's pill is in the same row. -->
        <MainNav
          v-if="mode === 'senior' && links.length > 0"
          ref="nav"
          variant="bar"
          :links="links"
          :dots="navDots"
        />
        <MainNav v-else-if="showTabs && wide" variant="pill" :links="links" :dots="navDots" />

        <div class="topbar-tools">
          <template v-if="showTabs">
            <RouterLink v-if="ready && !signedIn" class="btn btn-outline-primary" to="/login">
              Sign in
            </RouterLink>
            <NotificationBell v-if="showBell" />
            <SettingsMenu v-slot="{ close }">
              <p v-if="mode" class="menu-view mb-0">{{ VIEW_NAMES[mode] }} view</p>
              <select
                v-if="mode === 'family' && activeGroups.length > 1"
                class="form-select"
                aria-label="Whose care to show"
                data-testid="senior-picker"
                :value="currentGroup?.group_id"
                @change="pickSenior"
              >
                <option v-for="group in activeGroups" :key="group.group_id" :value="group.group_id">
                  {{ group.senior_name }}
                </option>
              </select>
              <DisplayControls />
              <template v-if="ready && signedIn">
                <hr class="menu-divider" />
                <button
                  type="button"
                  class="btn btn-outline-secondary menu-signout"
                  @click="
                    close();
                    leave();
                  "
                >
                  <Icon name="sign-out" />Sign out
                </button>
              </template>
            </SettingsMenu>
          </template>
          <template v-else>
            <DisplayControls />
            <template v-if="ready">
              <RouterLink v-if="!signedIn" class="btn btn-outline-primary" to="/login">
                Sign in
              </RouterLink>
              <template v-else>
                <span v-if="mode" class="role-chip">{{ VIEW_NAMES[mode] }}</span>
                <button
                  type="button"
                  class="btn btn-outline-secondary signout"
                  title="Sign out"
                  @click="leave()"
                >
                  <Icon name="sign-out" /><span class="signout-label">Sign out</span>
                </button>
              </template>
            </template>
          </template>
        </div>
      </div>
    </header>

    <MainNav v-if="showTabs && !wide" variant="tabs" :links="links" :dots="navDots" />

    <main id="main" tabindex="-1" class="container flex-grow-1">
      <!-- The senior's size on their own screen, even when the account read is what failed. -->
      <ConnectionProblem
        v-if="problem"
        :senior="mode === 'senior' || isPathInView('senior', route.path)"
      />
      <template v-else>
        <CheckInBanner v-if="showCheckIn" />
        <RouterView v-slot="{ Component, route: shown }">
          <Transition name="page">
            <component :is="Component" :key="shown.path" />
          </Transition>
        </RouterView>
      </template>
    </main>

    <AssistantDock v-if="showAssistant" />

    <footer class="site-footer">
      <div class="container">
        Care+ is a decision-support prototype that runs on synthetic data. It is not a medical or
        emergency service.
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* Senior and sign-in screens: the plain top bar, now see-through like the family's (no blur: a
   blurred header would trap the senior's fixed elements). */
.topbar {
  position: sticky;
  z-index: var(--sl-header-z);
  /* 0 on wide screens; on a phone, minus the brand row, so only the menu row stays pinned. */
  top: calc(-1 * var(--sl-tuck, 0px));
  border-bottom: 1px solid var(--sl-glass-border);
  background: color-mix(in srgb, var(--sl-mist) 90%, transparent);
}

.topbar-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1.5rem;
  min-height: 4.25rem;
  padding-top: 0.5rem;
  padding-bottom: 0.5rem;
}

main {
  padding-top: 1.5rem;
  padding-bottom: 1.5rem;
}

@media (min-width: 768px) {
  main {
    padding-top: 3rem;
    padding-bottom: 3rem;
  }
}

/* The family's header: one slim frosted row, brand left, menu centred, settings right. The
   frosted bar is safe here because the phone tab bar is outside the header. */
.shell--tabs .topbar {
  border-bottom-color: var(--sl-glass-border);
  background: var(--sl-glass-bg);
  -webkit-backdrop-filter: var(--sl-glass-filter);
  backdrop-filter: var(--sl-glass-filter);
}

.shell--tabs .topbar-inner {
  min-height: 3.75rem;
  padding-top: 0.4rem;
  padding-bottom: 0.4rem;
  gap: 0.4rem 0.75rem;
}

/* Brand and tools share the row equally, so the menu is centred. If the menu cannot fit (high
   zoom), the row wraps rather than clip a tab. */
.shell--tabs .brand,
.shell--tabs .topbar-tools {
  flex: 1 1 0;
  min-width: max-content;
}

.shell--tabs .topbar-tools {
  flex-wrap: nowrap;
  justify-content: flex-end;
}

/* A phone keeps room under the footer for the fixed tab bar. */
@media (max-width: 767.98px) {
  .shell--tabs {
    padding-bottom: var(--sl-tabbar-height);
  }
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  color: var(--sl-jade);
  font-size: 1.3rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  text-decoration: none;
}

.brand:hover {
  color: var(--sl-jade-deep);
}

.brand-mark {
  width: 2rem;
  height: 2rem;
}

.brand-plus {
  margin-left: 0.05em;
  color: var(--sl-sun-deep); /* the logo ring's sun, darkened to 4.5:1 on the header */
}

/* Dark mode: jade is kept dark for button fills, so the name uses the light mint (9:1). */
:root[data-bs-theme='dark'] .brand {
  color: var(--sl-mint);
}

:root[data-bs-theme='dark'] .brand:hover {
  color: var(--sl-jade-deep);
}

.topbar-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
  margin-left: auto;
}

.signout {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.role-chip {
  padding: 0.3rem 0.75rem;
  border-radius: 999px;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-size: 0.875rem;
  font-weight: 700;
}

/* Inside the Settings popover. */
.menu-view {
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
  font-weight: 700;
}

.menu-divider {
  margin: 0.25rem 0;
  border-color: var(--sl-line);
  opacity: 1;
}

.menu-signout {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
}

/* ---- Tablet: a little less space between the senior's bar items, as before ---- */
@media (min-width: 768px) and (max-width: 991.98px) {
  .topbar-inner {
    gap: 0.75rem 1rem;
  }
}

/* ---- On a phone the senior's header is two rows, so its tools stay close ---- */
@media (max-width: 767.98px) {
  .topbar-inner {
    gap: 0.5rem 0.75rem;
    min-height: 0;
    padding-bottom: 0;
  }

  .shell--tabs .topbar-inner {
    min-height: 3.75rem;
    padding-bottom: 0.4rem;
  }

  .topbar-tools {
    gap: 0.4rem;
  }
}

/* ---- Small phones: the sign-out button shows its icon only (its name is still read out) ---- */
@media (max-width: 575.98px) {
  .signout {
    --bs-btn-padding-x: 0.7rem;
  }

  .signout-label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  .role-chip {
    display: none;
  }
}

.site-footer {
  padding: 1.25rem 0;
  border-top: 1px solid var(--sl-line);
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
}
</style>
