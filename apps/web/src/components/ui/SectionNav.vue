<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import { currentSection, type SectionPosition } from '@/lib/section-spy';

/**
 * A row of "jump to" buttons for the top of a long page: Tasks · Calendar · Family. Each one scrolls
 * to the section with that `id`, moves keyboard focus there (so a screen reader carries on reading
 * from the section), and the one for the section you are reading is highlighted as you scroll.
 *
 * Use:
 *   <SectionNav :items="[
 *     { id: 'tasks', label: 'Tasks', icon: 'checklist', tone: 'blue' },
 *     { id: 'week', label: 'This week', icon: 'calendar', tone: 'purple' },
 *   ]" />
 *   ...
 *   <section id="tasks" aria-labelledby="tasks-heading">...</section>
 *
 * Options: `label` (what a screen reader calls the row, default "On this page") and `sticky` (keep
 * the row on screen under the top bar while scrolling). The links are real `#id` links, so they still
 * work without JavaScript. Leave out `tone` and the button is jade.
 */
export interface SectionNavItem {
  /** The `id` of the section to jump to (without `#`). */
  id: string;
  label: string;
  icon?: IconName;
  tone?: 'jade' | 'coral' | 'blue' | 'purple' | 'orange';
}

const props = withDefaults(
  defineProps<{ items: SectionNavItem[]; label?: string; sticky?: boolean }>(),
  { label: 'On this page', sticky: false },
);

/** The section being read right now, highlighted in the row. */
const current = ref<string | null>(null);

function reducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

const root = ref<HTMLElement | null>(null);

/** How much of the top of the screen is covered: the pinned top bar, plus this row if sticky. */
function coveredTop(): number {
  const pinned = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--sl-pinned-height'),
  );
  const own = props.sticky && root.value ? root.value.offsetHeight : 0;
  return (Number.isFinite(pinned) ? pinned : 0) + own;
}

function jump(event: MouseEvent, id: string) {
  const target = document.getElementById(id);
  if (!target) return; // Let the browser follow the plain #link.
  event.preventDefault();
  // Stop just below whatever is pinned at the top, not underneath it.
  const top = target.getBoundingClientRect().top + window.scrollY - coveredTop() - 12;
  window.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? 'auto' : 'smooth' });
  // Focus the section without a second jump, so Tab and screen readers continue from there.
  if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
  target.focus({ preventScroll: true });
  jumpedTo = id;
  current.value = id;
  // Keep the address shareable (…/#tasks) without a router navigation.
  history.replaceState(history.state, '', `#${id}`);
}

/*
 * Highlight the section being read while scrolling: the one whose top most recently passed just
 * under the pinned bar. Sections are looked up on every check, so it works for sections that only
 * appear after the page has loaded its data. After a jump, the chosen section stays highlighted
 * until the reader scrolls again, even if it is too near the bottom to reach the top.
 */
let jumpedTo: string | null = null;
let frame = 0;

function spy() {
  frame = 0;
  const sections: SectionPosition[] = [];
  for (const item of props.items) {
    const rect = document.getElementById(item.id)?.getBoundingClientRect();
    if (rect) sections.push({ id: item.id, top: rect.top, bottom: rect.bottom });
  }
  current.value = currentSection(sections, {
    covered: coveredTop(),
    height: window.innerHeight,
    atBottom: window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2,
    jumpedTo,
  });
}

function scheduleSpy() {
  if (!frame) frame = requestAnimationFrame(spy);
}

/** The reader is scrolling by themselves again: stop holding the jumped-to highlight. */
function release() {
  jumpedTo = null;
}

const RELEASE_EVENTS = ['wheel', 'touchstart', 'keydown'] as const;

onMounted(() => {
  window.addEventListener('scroll', scheduleSpy, { passive: true });
  window.addEventListener('resize', scheduleSpy, { passive: true });
  for (const name of RELEASE_EVENTS) window.addEventListener(name, release, { passive: true });
  scheduleSpy();
});

watch(() => props.items.map((item) => item.id).join(' '), scheduleSpy, { flush: 'post' });

// On a narrow screen the row scrolls sideways: bring the highlighted button into view within the
// row (only the row moves, never the page).
watch(
  current,
  (id) => {
    const list = root.value?.querySelector<HTMLElement>('.section-nav-list');
    const link = id ? list?.querySelector<HTMLElement>(`[href="#${CSS.escape(id)}"]`) : null;
    if (!list || !link) return;
    const start = link.offsetLeft; // the list is the links' offset parent (position: relative)
    const end = start + link.offsetWidth;
    if (start < list.scrollLeft) list.scrollLeft = start - 8;
    else if (end > list.scrollLeft + list.clientWidth) list.scrollLeft = end - list.clientWidth + 8;
  },
  { flush: 'post' },
);

onBeforeUnmount(() => {
  window.removeEventListener('scroll', scheduleSpy);
  window.removeEventListener('resize', scheduleSpy);
  for (const name of RELEASE_EVENTS) window.removeEventListener(name, release);
  if (frame) cancelAnimationFrame(frame);
});
</script>

<template>
  <nav ref="root" class="section-nav" :class="{ 'is-sticky': sticky }" :aria-label="label">
    <ul class="section-nav-list">
      <li v-for="item in items" :key="item.id">
        <a
          class="section-nav-link"
          :class="`sl-tone-${item.tone ?? 'jade'}`"
          :href="`#${item.id}`"
          :aria-current="current === item.id ? 'location' : undefined"
          @click="jump($event, item.id)"
        >
          <Icon v-if="item.icon" :name="item.icon" />
          <span>{{ item.label }}</span>
        </a>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.section-nav {
  margin-bottom: 1.25rem;
}

/* Kept on screen just under the top bar while the page scrolls. */
.section-nav.is-sticky {
  position: sticky;
  z-index: 1010;
  top: var(--sl-pinned-height, 0px);
  margin-right: calc(-0.5 * var(--bs-gutter-x));
  margin-left: calc(-0.5 * var(--bs-gutter-x));
  padding: 0.5rem calc(0.5 * var(--bs-gutter-x));
  background: var(--sl-mist);
}

/* One row; on a narrow screen it scrolls sideways rather than squashing or widening the page. */
.section-nav-list {
  position: relative;
  display: flex;
  gap: 0.5rem;
  margin: 0;
  padding: 0.15rem 0.1rem;
  overflow-x: auto;
  list-style: none;
  scrollbar-width: thin;
}

.section-nav-list li {
  flex: none;
}

.section-nav-link {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  min-height: 2.75rem;
  padding: 0.35rem 0.95rem;
  border: 2px solid var(--sl-line);
  border-radius: 999px;
  background: var(--sl-surface);
  color: var(--sl-ink);
  font-weight: 600;
  line-height: 1.2;
  text-decoration: none;
  white-space: nowrap;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease,
    transform 0.15s var(--sl-ease);
}

/* The icon carries the section's colour; the words stay full-contrast ink. */
.section-nav-link .sl-icon {
  color: var(--tone-deep);
}

.section-nav-link:hover {
  border-color: var(--tone);
  color: var(--sl-ink);
}

.section-nav-link:active {
  transform: scale(0.97);
}

/* The section being read: tinted, outlined in its colour and bold (not colour alone). */
.section-nav-link[aria-current='location'] {
  border-color: var(--tone);
  background: var(--tone-soft);
  color: var(--tone-deep);
  font-weight: 800;
}
</style>
