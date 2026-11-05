<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import { sameSpan, type Span, STRETCH_MS, stretchSpan } from '@/lib/nav-bubble';
import { LABEL_ROOM, pillLeft, tabRows } from '@/lib/tab-rows';

/**
 * The main menu, in three looks:
 * - `tabs` (the family, phone): a bottom tab bar, `position: fixed`, so the layout renders it
 *   outside the sticky header (a filtered ancestor would trap a fixed child). Its labels grow with
 *   the text size like everything else; when they no longer fit side by side (a narrow phone at a
 *   large text size), the bar takes a second row rather than shrinking them, and tells the page
 *   how tall it now is through `--sl-tabbar-core`, so content and toasts stay clear of it.
 * - `pill` (the family, wide screens): a pill in the middle of the header row.
 *   Both slide one glass bubble (with a rainbow rim) behind the current link. On the pill it also
 *   follows the mouse or keyboard focus, stretching like liquid between links, and goes back to
 *   the current link when they leave the menu.
 * - `bar` (the senior): the plain links inside the top bar; the current one is the glass bubble.
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
/** True while the mouse or focus is on a link (the bubble shows there even with no current link). */
const pointing = ref(false);
/** True for the moment the bubble is stretched between two links. */
const stretching = ref(false);
let resizeObserver: ResizeObserver | null = null;
/** Tab bar only: the rows it is using, and how many tabs to a row. */
const rows = ref(1);
const perRow = ref(props.links.length);
/** The tab bar's one-row height, read from theme.css before this bar changes it. */
let rowHeight = '';
let stretchTimer = 0;
let measureFrame = 0;
/** Where the bubble is now, so the next move can stretch from it. */
let shown: Span | null = null;

const reducedMotion = () =>
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

/**
 * Sets the bubble's place (CSS turns these two numbers into its position and width). The tab bar's
 * pill has a width of its own, centred on the tab and held inside the bar (`pillLeft`).
 */
function place(span: Span) {
  const el = list.value;
  if (!el) return;
  el.style.setProperty('--ind-x', `${span.x}px`);
  el.style.setProperty('--ind-w', `${span.w}px`);
  if (props.variant === 'tabs') {
    const pill = el.querySelector<HTMLElement>('.mainnav-indicator')?.offsetWidth ?? 0;
    el.style.setProperty('--ind-left', `${pillLeft(span.x, span.w, pill, el.clientWidth)}px`);
  }
}

/**
 * Moves the bubble under `link`. With `stretch`, it first covers both the old and the new link,
 * then shrinks onto the new one `STRETCH_MS` later; CSS's springy transition does the rest.
 */
function moveTo(link: HTMLElement, stretch = false) {
  window.clearTimeout(stretchTimer);
  stretching.value = false;
  // Tab bar on two rows: the pill also moves down to the current tab's row.
  list.value?.style.setProperty('--ind-y', `${link.offsetTop}px`);
  const target = { x: link.offsetLeft, w: link.offsetWidth };
  if (stretch && ready.value && shown && !sameSpan(shown, target) && !reducedMotion()) {
    stretching.value = true;
    place(stretchSpan(shown, target));
    stretchTimer = window.setTimeout(() => {
      stretching.value = false;
      place(target);
    }, STRETCH_MS);
  } else {
    place(target);
  }
  shown = target;
}

/**
 * Tab bar: one row if every label fits its tab whole, else as many rows as it takes. The labels are
 * measured at their real size (never shrunk), so this follows the zoom setting.
 */
function fitRows() {
  const el = list.value;
  if (!el || props.variant !== 'tabs') return;
  const widths = [...el.querySelectorAll<HTMLElement>('.mainnav-label')].map(
    (label) => label.getBoundingClientRect().width,
  );
  const fit = tabRows(widths, el.clientWidth, LABEL_ROOM);
  rows.value = fit.rows;
  perRow.value = fit.perRow;
  const root = document.documentElement.style;
  if (fit.rows > 1) root.setProperty('--sl-tabbar-core', `calc(${fit.rows} * ${rowHeight})`);
  else root.removeProperty('--sl-tabbar-core');
}

/** Watch the bar, and its labels: a new text size changes their width even when the bar's does not. */
function observeAll() {
  const el = list.value;
  if (!resizeObserver || !el) return;
  resizeObserver.disconnect();
  resizeObserver.observe(el);
  for (const label of el.querySelectorAll('.mainnav-label')) resizeObserver.observe(label);
}

/** Put the bubble under the current link. */
function measure() {
  const el = list.value;
  if (!el || props.variant === 'bar') return;
  fitRows();
  const active = el.querySelector<HTMLElement>('a.active');
  hasActive.value = !!active;
  // While the mouse or focus is on a link the bubble stays there; it comes back on leaving.
  if (active && !pointing.value) moveTo(active);
}

/**
 * The ResizeObserver's callback: measures on the next frame instead. Changing the rows resizes the
 * bar it is watching, and doing that while it reports sets off a "ResizeObserver loop" (a web font
 * arriving late on the sign-in page widens only the labels, and the bar takes a second row).
 */
function measureSoon() {
  if (measureFrame) return;
  measureFrame = requestAnimationFrame(() => {
    measureFrame = 0;
    measure();
  });
}

/** The mouse (not a finger) or keyboard focus reached a link: the bubble goes to it. */
function onPoint(event: PointerEvent | FocusEvent) {
  if (props.variant !== 'pill') return;
  if ('pointerType' in event && event.pointerType === 'touch') return;
  pointing.value = true;
  moveTo(event.currentTarget as HTMLElement, true);
}

/** The mouse or focus left the menu: back to the current link. */
function onLeave(event: PointerEvent | FocusEvent) {
  if (props.variant !== 'pill' || !pointing.value) return;
  const next = (event as FocusEvent).relatedTarget as Node | null;
  if (event.type === 'focusout' && next && list.value?.contains(next)) return;
  // The mouse left, but keyboard focus is still on a link in the menu: stay with the focus.
  const focused = document.activeElement as HTMLElement | null;
  if (event.type === 'pointerleave' && focused?.matches('a') && list.value?.contains(focused)) {
    moveTo(focused, true);
    return;
  }
  pointing.value = false;
  const active = list.value?.querySelector<HTMLElement>('a.active');
  if (active) moveTo(active, true);
}

onMounted(async () => {
  if (props.variant === 'tabs') {
    document.documentElement.style.removeProperty('--sl-tabbar-core');
    rowHeight =
      getComputedStyle(document.documentElement).getPropertyValue('--sl-tabbar-core').trim() ||
      '3.5rem';
  }
  await nextTick();
  measure();
  // Two frames: let the first position paint with no transition, then enable sliding.
  requestAnimationFrame(() => requestAnimationFrame(() => (ready.value = true)));
  if (typeof ResizeObserver !== 'undefined' && list.value) {
    // Zoom, rotation and web fonts loading all change where the links sit.
    resizeObserver = new ResizeObserver(measureSoon);
    observeAll();
  }
  void document.fonts?.ready.then(measure);
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  cancelAnimationFrame(measureFrame);
  if (props.variant === 'tabs') document.documentElement.style.removeProperty('--sl-tabbar-core');
  window.clearTimeout(stretchTimer);
});

watch(
  () => [route.fullPath, props.links.length],
  async () => {
    await nextTick();
    observeAll();
    measure();
  },
);
</script>

<template>
  <nav class="mainnav" :class="`mainnav--${variant}`" aria-label="Main">
    <ul
      ref="list"
      class="mainnav-list"
      :class="{
        'is-ready': ready,
        'has-active': hasActive || pointing,
        'is-stretching': stretching,
        'is-rows': rows > 1,
      }"
      :style="variant === 'tabs' ? { '--tab-rows': rows, '--tab-per-row': perRow } : undefined"
      @pointerleave="onLeave"
      @focusout="onLeave"
    >
      <li v-for="link in links" :key="link.to" class="mainnav-item">
        <RouterLink
          class="mainnav-link"
          :to="link.to"
          :active-class="link.exact ? '' : 'active'"
          exact-active-class="active"
          @pointerenter="onPoint"
          @focus="onPoint"
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

/* The senior's current link is the same glass bubble as the family's, standing still. */
.mainnav--bar .mainnav-link.active {
  background: var(--sl-bubble-bg);
  box-shadow: var(--sl-bubble-shadow);
  color: var(--sl-ink);
  font-weight: 700;
}

.mainnav--bar .mainnav-link.active::before {
  content: '';
  position: absolute;
  inset: 0;
  padding: 1.5px;
  border-radius: inherit;
  background: var(--sl-bubble-rim);
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask:
    linear-gradient(#000 0 0) content-box exclude,
    linear-gradient(#000 0 0);
  pointer-events: none;
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

  /* Shown by shape as well as colour: a tint plus a bar underneath. */
  .mainnav--bar .mainnav-link.active {
    background: var(--sl-jade-soft);
    color: var(--sl-jade-deep);
    box-shadow: inset 0 -3px 0 var(--sl-jade-deep);
  }

  .mainnav--bar .mainnav-link.active::before {
    display: none;
  }
}

/* ===== tabs and pill (the family): one glass bubble that slides to the current link ===== */
/* The bubble: frosted glass, a rainbow rim (a conic gradient masked to a ring) and a soft glow of
   the same colours behind it. */
.mainnav-indicator {
  position: absolute;
  z-index: 0;
  left: 0;
  border-radius: 999px;
  background: var(--sl-bubble-bg);
  box-shadow: var(--sl-bubble-shadow);
  opacity: 0;
  pointer-events: none;
}

.mainnav-indicator::before,
.mainnav-indicator::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: var(--sl-bubble-rim);
}

.mainnav-indicator::before {
  padding: 1.5px;
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask:
    linear-gradient(#000 0 0) content-box exclude,
    linear-gradient(#000 0 0);
}

.mainnav-indicator::after {
  z-index: -1;
  inset: -3px;
  filter: blur(8px);
  opacity: 0.22;
}

.mainnav-list.has-active .mainnav-indicator {
  opacity: 1;
}

/* A spring that overshoots a little, so it settles with a wobble; squashed while stretched. */
.mainnav-list.is-ready .mainnav-indicator {
  transition:
    transform 0.5s var(--sl-ease-spring),
    width 0.5s var(--sl-ease-spring),
    scale 0.45s var(--sl-ease-spring),
    opacity var(--sl-dur-base) ease;
}

.mainnav-list.is-ready.is-stretching .mainnav-indicator {
  scale: 1 0.84;
  transition:
    transform 0.17s ease-out,
    width 0.17s ease-out,
    scale 0.17s ease-out,
    opacity var(--sl-dur-base) ease;
}

.mainnav-link .mainnav-icon {
  transition: transform 0.35s var(--sl-ease-spring);
}

.mainnav--pill .mainnav-link:hover .mainnav-icon {
  transform: scale(1.15);
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

.mainnav--tabs .mainnav-item {
  flex: 1 1 0;
  min-width: 0;
}

/* Two (or more) rows: tabs of one size, a row's worth each, the last row centred. */
.mainnav--tabs .mainnav-list.is-rows {
  flex-wrap: wrap;
  justify-content: center;
}

.mainnav--tabs .mainnav-list.is-rows .mainnav-item {
  flex: 0 0 calc(100% / var(--tab-per-row));
}

.mainnav--tabs .mainnav-link {
  flex-direction: column;
  justify-content: flex-start;
  width: 100%;
  height: calc(var(--sl-tabbar-core) / var(--tab-rows, 1));
  padding-top: 0.35rem;
  font-size: 0.8rem;
  line-height: 1.2;
  text-align: center;
}

.mainnav--tabs .mainnav-link.active {
  color: var(--sl-jade-deep);
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

/* One line at the chosen text size. It is never shrunk to fit: when the labels would not fit side
   by side, the bar takes another row instead (see `fitRows`). */
.mainnav--tabs .mainnav-label {
  margin-top: 0.1rem;
  white-space: nowrap;
}

/* On the tab bar the dot sits at the icon's top-right corner. */
.mainnav--tabs .mainnav-dot {
  top: 0.3rem;
  right: calc(50% - 1.1rem);
}

/* The pill is 4rem wide and 2rem tall, centred on the current tab (held inside the bar when the
   tab is narrower than the pill; see `place`), level with the icons. */
.mainnav--tabs .mainnav-indicator {
  top: 0.35rem;
  width: 4rem;
  height: 2rem;
  transform: translate(var(--ind-left, 0px), var(--ind-y, 0px));
}

/* Wide screens: a pill in the header row. The current link is a solid jade pill with white text. */
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

/* The bubble shows where the mouse is, so a hovered link needs no fill of its own. */
.mainnav--pill .mainnav-link:hover,
.mainnav--pill .mainnav-link.active {
  color: var(--sl-ink);
}

.mainnav--pill .mainnav-link.active {
  font-weight: 700;
}

.mainnav--pill .mainnav-icon {
  display: inline-flex;
}

.mainnav--pill .mainnav-indicator {
  top: 0.25rem;
  bottom: 0.25rem;
  width: var(--ind-w, 0);
  transform: translateX(var(--ind-x, 0px));
}

/* Tablet widths: words only, so the pill and the header's tools fit with room to spare. */
@media (min-width: 768px) and (max-width: 991.98px) {
  .mainnav--pill .mainnav-icon {
    display: none;
  }

  /* The sides shrink with the screen (never past 0.9rem), so six links still fit at the largest
     text size. */
  .mainnav--pill .mainnav-link {
    padding: 0.4rem min(0.9rem, 1.4vw);
  }
}
</style>
