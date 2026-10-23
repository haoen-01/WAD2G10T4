<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink, RouterView, useRouter } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import DisplayControls from '@/components/ui/DisplayControls.vue';
import { useAuth } from '@/composables/useAuth';
import { useMe } from '@/composables/useMe';
import { useViewMode } from '@/composables/useViewMode';
import { AUTH_ENABLED } from '@/lib/config';
import { homeFor, isPathInView } from '@/lib/view-mode';

const { loading, currentUser, signOut } = useAuth();
const { mode, leaveDemoView } = useViewMode();
// A family member caring for more than one senior picks whose care the screens show.
const { activeGroups, currentGroup, selectGroup } = useMe();
function pickSenior(event: Event) {
  selectGroup((event.target as HTMLSelectElement).value);
}
const router = useRouter();

const ALL_LINKS: { to: string; label: string; exact: boolean; icon: IconName }[] = [
  { to: '/', label: 'Home', exact: true, icon: 'home' },
  { to: '/senior', label: 'My day', exact: false, icon: 'person' },
  { to: '/calendar', label: 'Calendar', exact: false, icon: 'calendar' },
  { to: '/family', label: 'Family', exact: false, icon: 'users' },
];

// The family sees Home, Calendar and Family; the senior sees only their own screen. Nobody signed
// in sees none, except with sign-in off and no demo view chosen, when every screen is listed. The API enforces each role too, except for
// the calendar and family screens, which hold sample data in the browser and have no API behind
// them.
const links = computed(() => {
  const current = mode.value;
  if (current) return ALL_LINKS.filter((link) => isPathInView(current, link.to));
  return AUTH_ENABLED ? [] : ALL_LINKS;
});

const brandTo = computed(() => (mode.value ? homeFor(mode.value) : '/'));
const VIEW_NAMES = { family: 'Family', senior: 'Senior' } as const;

/** Sign-in off: leave the demo view and go back to choosing one. */
async function leaveDemo() {
  leaveDemoView();
  await router.replace({ name: 'login' });
}

/*
 * Keeping the menu in reach. On a wide screen the whole top bar is one row and stays pinned. On a
 * phone the menu is a second row of the top bar: the brand row scrolls away and the menu row stays
 * pinned at the top. The bar is pinned with a negative `top` equal to the height above the menu
 * (`--sl-tuck`), measured here because it changes with zoom and wrapping. `--sl-pinned-height`
 * (what stays on screen) lets jump links (`SectionNav`) stop below the bar, not under it.
 */
const header = ref<HTMLElement | null>(null);
const nav = ref<HTMLElement | null>(null);
const PHONE = '(max-width: 767.98px)';
let resizeObserver: ResizeObserver | null = null;
let phoneQuery: MediaQueryList | null = null;

function measure() {
  const bar = header.value;
  if (!bar) return;
  const onPhone = phoneQuery?.matches ?? false;
  const tuck = onPhone && nav.value ? nav.value.offsetTop : 0;
  bar.style.setProperty('--sl-tuck', `${tuck}px`);
  document.documentElement.style.setProperty('--sl-pinned-height', `${bar.offsetHeight - tuck}px`);
}

onMounted(() => {
  phoneQuery = window.matchMedia(PHONE);
  phoneQuery.addEventListener('change', measure);
  if (typeof ResizeObserver !== 'undefined' && header.value) {
    resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(header.value);
  }
  measure();
});

onBeforeUnmount(() => {
  phoneQuery?.removeEventListener('change', measure);
  resizeObserver?.disconnect();
  document.documentElement.style.removeProperty('--sl-pinned-height');
});
</script>

<template>
  <div class="shell d-flex flex-column min-vh-100">
    <a class="visually-hidden-focusable" href="#main">Skip to content</a>

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

        <!-- One menu, always in the top bar. On a phone it is a second row that stays pinned. -->
        <nav ref="nav" class="mainnav" aria-label="Main">
          <ul class="mainnav-list">
            <li v-for="link in links" :key="link.to">
              <RouterLink
                class="mainnav-link"
                :to="link.to"
                :active-class="link.exact ? '' : 'active'"
                exact-active-class="active"
              >
                <Icon :name="link.icon" />
                <span>{{ link.label }}</span>
              </RouterLink>
            </li>
          </ul>
        </nav>

        <div class="topbar-tools">
          <DisplayControls />
          <template v-if="!AUTH_ENABLED || !loading">
            <RouterLink
              v-if="AUTH_ENABLED ? !currentUser : !mode"
              class="btn btn-outline-primary"
              to="/login"
            >
              Sign in
            </RouterLink>
            <template v-else>
              <select
                v-if="mode === 'family' && activeGroups.length > 1"
                class="form-select senior-picker"
                aria-label="Whose care to show"
                data-testid="senior-picker"
                :value="currentGroup?.group_id"
                @change="pickSenior"
              >
                <option v-for="group in activeGroups" :key="group.group_id" :value="group.group_id">
                  {{ group.senior_name }}
                </option>
              </select>
              <span v-if="mode" class="role-chip">{{ VIEW_NAMES[mode] }}</span>
              <button
                type="button"
                class="btn btn-outline-secondary signout"
                title="Sign out"
                @click="AUTH_ENABLED ? signOut() : leaveDemo()"
              >
                <Icon name="sign-out" /><span class="signout-label">Sign out</span>
              </button>
            </template>
          </template>
        </div>
      </div>
    </header>

    <main id="main" tabindex="-1" class="container flex-grow-1 py-4 py-md-5">
      <RouterView v-slot="{ Component, route }">
        <Transition name="page">
          <component :is="Component" :key="route.path" />
        </Transition>
      </RouterView>
    </main>

    <footer class="site-footer">
      <div class="container">
        Care+ is a decision-support prototype that runs on synthetic data. It is not a medical or
        emergency service.
      </div>
    </footer>
  </div>
</template>

<style scoped>
.topbar {
  position: sticky;
  z-index: 1020;
  /* 0 on wide screens; on a phone, minus the brand row, so only the menu row stays pinned. */
  top: calc(-1 * var(--sl-tuck, 0px));
  border-bottom: 1px solid var(--sl-line);
  /* Solid, not blurred: a backdrop filter would trap the phone tab bar (position: fixed) inside. */
  background: var(--sl-mist);
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
  color: #9a6200; /* the logo ring's sun, darkened to 4.5:1 on the header */
}

:root[data-bs-theme='dark'] .brand-plus {
  color: var(--sl-sun);
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

/* ---- Main menu: inline beside the brand on wider screens ---- */
.mainnav-list {
  display: flex;
  gap: 0.25rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.mainnav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 2.75rem;
  padding: 0.4rem 0.9rem;
  border-radius: 999px;
  color: var(--sl-ink-soft);
  font-weight: 600;
  text-decoration: none;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}

.mainnav-link:hover {
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink);
}

.mainnav-link.active {
  background: var(--sl-ink);
  color: var(--sl-on-ink);
}

/* ---- Tablet: words only, so the menu and the tools share one line ---- */
@media (min-width: 768px) and (max-width: 991.98px) {
  .mainnav-link .sl-icon {
    display: none;
  }

  .mainnav-link {
    padding: 0.4rem 0.75rem;
  }

  .topbar-inner {
    gap: 0.75rem 1rem;
  }
}

/* ---- On a phone: the menu is the top bar's second row, one equal tab per screen ---- */
@media (max-width: 767.98px) {
  .topbar-inner {
    gap: 0.5rem 0.75rem;
    min-height: 0;
    padding-bottom: 0;
  }

  /* Brand and tools share the first row; the menu takes the whole second row. */
  .mainnav {
    order: 3;
    flex: 1 0 100%;
    margin: 0 calc(-0.5 * var(--bs-gutter-x));
    padding: 0.3rem 0.5rem 0.4rem;
    border-top: 1px solid var(--sl-line);
  }

  .mainnav-list li {
    flex: 1;
    min-width: 0;
  }

  .mainnav-link {
    flex-direction: column;
    gap: 0.1rem;
    width: 100%;
    min-height: 3.25rem;
    padding: 0.3rem 0.25rem;
    border-radius: var(--sl-radius-sm);
    font-size: 0.85rem;
    text-align: center;
  }

  .mainnav-link .sl-icon {
    width: 1.4rem;
    height: 1.4rem;
  }

  /* The current tab: a tint plus a bar underneath, so it is shown by shape as well as colour. */
  .mainnav-link.active {
    background: var(--sl-jade-soft);
    color: var(--sl-jade-deep);
    box-shadow: inset 0 -3px 0 var(--sl-jade-deep);
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

.senior-picker {
  width: auto;
  max-width: 12rem;
}
</style>
