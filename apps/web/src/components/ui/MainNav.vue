<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';

/**
 * The main menu, in three looks:
 * - `tabs` (the family, phone): a bottom tab bar, `position: fixed`, so the layout renders it
 *   outside the sticky header (a filtered ancestor would trap a fixed child).
 * - `pill` (the family, wide screens): a pill in the middle of the header row.
 *   Both slide one highlight behind the current link.
 * - `bar` (the senior): the plain links inside the top bar, unchanged.
 * `dots` puts a sun-coloured dot on a link (keyed by its path); the value is read out after its label.
 */
const props = defineProps<{
  links: { to: string; label: string; exact: boolean; icon: IconName }[];
  variant: 'tabs' | 'pill' | 'bar';
  dots?: Record<string, string>;
}>();

const route = useRoute();
const list = ref<HTMLElement | null>(null);
/** False until the first measurement is painted, so the highlight appears in place, not sliding in. */
const ready = ref(false);
/** False when no link is current (for example on the group set-up pages), so nothing is highlighted. */
const hasActive = ref(false);
let resizeObserver: ResizeObserver | null = null;

/** Put the highlight under the current link (CSS turns these two numbers into its position). */
function measure() {
  const el = list.value;
  if (!el || props.variant === 'bar') return;
  const active = el.querySelector<HTMLElement>('a.active');
  hasActive.value = !!active;
  if (!active) return;
  el.style.setProperty('--ind-x', `${active.offsetLeft}px`);
  el.style.setProperty('--ind-w', `${active.offsetWidth}px`);
}

onMounted(async () => {
  await nextTick();
  measure();
  // Two frames: let the first position paint with no transition, then enable sliding.
  requestAnimationFrame(() => requestAnimationFrame(() => (ready.value = true)));
  if (typeof ResizeObserver !== 'undefined' && list.value) {
    // Zoom, rotation and web fonts loading all change where the links sit.
    resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(list.value);
  }
  void document.fonts?.ready.then(measure);
});

onBeforeUnmount(() => resizeObserver?.disconnect());

watch(
  () => [route.fullPath, props.links.length],
  async () => {
    await nextTick();
    measure();
  },
);
</script>

<template>
  <nav class="mainnav" :class="`mainnav--${variant}`" aria-label="Main">
    <ul ref="list" class="mainnav-list" :class="{ 'is-ready': ready, 'has-active': hasActive }">
      <li v-for="link in links" :key="link.to">
        <RouterLink
          class="mainnav-link"
          :to="link.to"
          :active-class="link.exact ? '' : 'active'"
          exact-active-class="active"
        >
          <span class="mainnav-icon"><Icon :name="link.icon" /></span>
          <span class="mainnav-label">{{ link.label }}</span>
          <span v-if="dots?.[link.to]" class="mainnav-dot" :data-testid="`${link.to.slice(1)}-dot`"
            ><span class="visually-hidden"> {{ dots[link.to] }}</span></span
          >
        </RouterLink>
      </li>
      <li v-if="variant !== 'bar'" class="mainnav-indicator" aria-hidden="true" />
    </ul>
  </nav>
</template>

<style scoped>
.mainnav-list {
  position: relative;
  display: flex;
  margin: 0;
  padding: 0;
  list-style: none;
}

.mainnav-link {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  color: var(--sl-ink-soft);
  font-weight: 600;
  text-decoration: none;
  transition:
    background-color var(--sl-dur-base) ease,
    color var(--sl-dur-base) ease;
}

/* Something is waiting on this link: a sun-coloured dot (its words are read out too). */
.mainnav-dot {
  position: absolute;
  top: 0.35rem;
  right: 0.45rem;
  width: 0.7rem;
  height: 0.7rem;
  border: 2px solid var(--sl-mist);
  border-radius: 50%;
  background: var(--sl-sun);
}

/* ===== bar (the senior): the links sit in the top bar ===== */
.mainnav--bar .mainnav-list {
  gap: 0.25rem;
}

.mainnav--bar .mainnav-link {
  gap: 0.5rem;
  min-height: 2.75rem;
  padding: 0.4rem 0.9rem;
  border-radius: 999px;
}

.mainnav--bar .mainnav-link:hover {
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink);
}

.mainnav--bar .mainnav-link.active {
  background: var(--sl-jade);
  color: var(--sl-jade-on);
}

.mainnav--bar .mainnav-icon {
  display: inline-flex;
}

@media (min-width: 768px) and (max-width: 991.98px) {
  .mainnav--bar .mainnav-icon {
    display: none;
  }

  .mainnav--bar .mainnav-link {
    padding: 0.4rem 0.75rem;
  }
}

/* On a phone the bar is the top bar's second row. */
@media (max-width: 767.98px) {
  .mainnav--bar {
    order: 3;
    flex: 1 0 100%;
    margin: 0 calc(-0.5 * var(--bs-gutter-x));
    padding: 0.3rem 0.5rem 0.4rem;
    border-top: 1px solid var(--sl-line);
  }

  .mainnav--bar li {
    flex: 1;
    min-width: 0;
  }

  .mainnav--bar .mainnav-link {
    flex-direction: column;
    gap: 0.1rem;
    width: 100%;
    min-height: 3.25rem;
    padding: 0.3rem 0.25rem;
    border-radius: var(--sl-radius-sm);
    font-size: 0.85rem;
    text-align: center;
  }

  .mainnav--bar .mainnav-icon .sl-icon {
    width: 1.4rem;
    height: 1.4rem;
  }

  /* Shown by shape as well as colour: a pale jade tint plus a jade bar underneath. */
  .mainnav--bar .mainnav-link.active {
    background: var(--sl-jade-soft);
    color: var(--sl-ink);
    box-shadow: inset 0 -3px 0 var(--sl-jade);
  }
}

/* ===== tabs and pill (the family): one highlight that slides to the current link ===== */
.mainnav-indicator {
  position: absolute;
  z-index: 0;
  left: 0;
  border-radius: 999px;
  opacity: 0;
  pointer-events: none;
}

.mainnav-list.has-active .mainnav-indicator {
  opacity: 1;
}

.mainnav-list.is-ready .mainnav-indicator {
  transition:
    transform var(--sl-dur-slow) var(--sl-ease-spring),
    width var(--sl-dur-slow) var(--sl-ease-spring),
    opacity var(--sl-dur-base) ease;
}

/* Phone tab bar: fixed to the bottom edge, icon above label, the highlight a pill behind the icon. */
.mainnav--tabs {
  position: fixed;
  z-index: var(--sl-nav-z);
  right: 0;
  bottom: 0;
  left: 0;
  height: var(--sl-tabbar-height);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  border-top: 1px solid var(--sl-glass-border);
  background: var(--sl-glass-bg);
  -webkit-backdrop-filter: var(--sl-glass-filter);
  backdrop-filter: var(--sl-glass-filter);
  box-shadow: var(--sl-elev-2);
}

.mainnav--tabs .mainnav-list {
  max-width: 32rem;
  height: var(--sl-tabbar-core);
  margin: 0 auto;
}

.mainnav--tabs li:not(.mainnav-indicator) {
  flex: 1 1 0;
  min-width: 0;
}

.mainnav--tabs .mainnav-link {
  flex-direction: column;
  justify-content: flex-start;
  width: 100%;
  height: var(--sl-tabbar-core);
  padding-top: 0.35rem;
  font-size: 0.8rem;
  line-height: 1.2;
  text-align: center;
}

.mainnav--tabs .mainnav-link.active {
  color: var(--sl-ink);
}

/* The current tab's icon sits on the jade pill. */
.mainnav--tabs .mainnav-link.active .mainnav-icon {
  color: var(--sl-jade-on);
}

.mainnav--tabs .mainnav-link.active .mainnav-label {
  font-weight: 700;
}

.mainnav--tabs .mainnav-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 2rem;
}

.mainnav--tabs .mainnav-icon .sl-icon {
  width: 1.5rem;
  height: 1.5rem;
}

.mainnav--tabs .mainnav-label {
  margin-top: 0.1rem;
}

/* On the tab bar the dot sits at the icon's top-right corner. */
.mainnav--tabs .mainnav-dot {
  top: 0.3rem;
  right: calc(50% - 1.1rem);
}

/* The pill is 4rem wide and 2rem tall, centred on the current tab, level with the icons. */
.mainnav--tabs .mainnav-indicator {
  top: 0.35rem;
  width: 4rem;
  height: 2rem;
  background: var(--sl-jade);
  transform: translateX(calc(var(--ind-x, 0px) + (var(--ind-w, 4rem) - 4rem) / 2));
}

/* Wide screens: a pill in the header row. The current link is a solid jade pill (white words in
   light mode, near-black in dark); sky blue stays for each screen's main action. */
.mainnav--pill {
  flex: 0 0 auto;
}

.mainnav--pill .mainnav-list {
  gap: 0.15rem;
  padding: 0.25rem;
  border: 1px solid var(--sl-glass-border);
  border-radius: 999px;
  background: var(--sl-glass-bg);
}

.mainnav--pill .mainnav-link {
  gap: 0.5rem;
  min-height: 2.75rem;
  padding: 0.4rem 1.1rem;
  border-radius: 999px;
  white-space: nowrap;
}

/* The text colour changes in step with the sliding highlight, so white text never sits on the
   light pill mid-slide. */
.mainnav--pill .mainnav-link {
  transition:
    background-color var(--sl-dur-base) ease,
    color var(--sl-dur-slow) var(--sl-ease-spring);
}

.mainnav--pill .mainnav-link:hover:not(.active) {
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink);
}

.mainnav--pill .mainnav-link.active {
  color: var(--sl-jade-on);
}

.mainnav--pill .mainnav-icon {
  display: inline-flex;
}

.mainnav--pill .mainnav-indicator {
  top: 0.25rem;
  bottom: 0.25rem;
  width: var(--ind-w, 0);
  background: var(--sl-jade);
  transform: translateX(var(--ind-x, 0px));
}

/* Tablet widths: words only, so the pill and the header's tools fit with room to spare. */
@media (min-width: 768px) and (max-width: 991.98px) {
  .mainnav--pill .mainnav-icon {
    display: none;
  }

  .mainnav--pill .mainnav-link {
    padding: 0.4rem 0.9rem;
  }
}
</style>
