<script setup lang="ts">
import { AnimatePresence, motion, useDragControls, type PanInfo } from 'motion-v';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useFocusTrap } from '@/composables/useFocusTrap';
import { useReducedMotion } from '@/composables/useReducedMotion';
import { DURATION, SPRING, durationFor, shouldDismissSheet } from '@/lib/motion';

/**
 * A modal sheet that rises from the bottom of the screen. It is a real dialog: it moves into
 * `<body>`, traps Tab, closes on Escape, the backdrop or its Close button, puts focus on the heading
 * named by `labelledby` when it opens and gives it back to what opened it when it closes. While open
 * the rest of the app (`#app`) is `inert` and the page cannot scroll; both are undone on close, on
 * unmount and on a route change (the page unmounts).
 *
 * Dragging the top strip down closes it (past 30% of its height, or faster than 500 px/s) or springs
 * it back. Dragging is a shortcut only: the Close button always works. With reduced motion the
 * sheet appears and goes without sliding, and dragging is off.
 *
 *   <BottomSheet :open="selected !== null" labelledby="details-heading" @close="close">…</BottomSheet>
 */
const props = withDefaults(
  defineProps<{
    open: boolean;
    /** The id of the heading inside the slot that names the dialog. */
    labelledby: string;
    closeLabel?: string;
  }>(),
  { closeLabel: 'Close' },
);
const emit = defineEmits<{ close: [] }>();

const reduced = useReducedMotion();
const panel = ref<{ $el?: HTMLElement } | HTMLElement | null>(null);
const panelEl = computed<HTMLElement | null>(() => {
  const value = panel.value;
  if (!value) return null;
  return value instanceof HTMLElement ? value : (value.$el ?? null);
});
const trap = useFocusTrap(panelEl);
const dragControls = useDragControls();

// ---- Side effects of being open: inert page, no scroll, focus in and back out ----
let opener: HTMLElement | null = null;
let savedOverflow = '';
let locked = false;

function appRoot(): HTMLElement | null {
  return document.getElementById('app');
}

function lock() {
  if (locked) return;
  locked = true;
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  savedOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';
  appRoot()?.setAttribute('inert', '');
}

function unlock(restoreFocus: boolean) {
  trap.deactivate();
  if (!locked) return;
  locked = false;
  document.body.style.overflow = savedOverflow;
  appRoot()?.removeAttribute('inert');
  const back = opener;
  opener = null;
  if (restoreFocus) {
    void nextTick(() => {
      if (back && document.contains(back)) back.focus();
    });
  }
}

function focusHeading() {
  const heading = document.getElementById(props.labelledby);
  (heading ?? panelEl.value)?.focus({ preventScroll: true });
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      lock();
      void nextTick(() => {
        trap.activate();
        focusHeading();
      });
    } else {
      unlock(true);
    }
  },
  { immediate: true, flush: 'sync' },
);
// A page that goes away with the sheet open (a route change) must not leave the app inert.
onBeforeUnmount(() => unlock(false));

function close() {
  emit('close');
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) {
    event.preventDefault();
    close();
  }
}
watch(
  () => props.open,
  (open) => {
    if (open) document.addEventListener('keydown', onKeydown);
    else document.removeEventListener('keydown', onKeydown);
  },
  { immediate: true },
);
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown));

// ---- Dragging the top strip down ----
function startDrag(event: PointerEvent) {
  if (reduced.value) return;
  dragControls.start(event);
}

function onDragEnd(_event: PointerEvent, info: PanInfo) {
  const height = panelEl.value?.getBoundingClientRect().height ?? 0;
  if (shouldDismissSheet(info.offset.y, info.velocity.y, height)) close();
  // Otherwise `dragSnapToOrigin` springs it back.
}
</script>

<template>
  <Teleport to="body">
    <AnimatePresence>
      <motion.div
        v-if="open"
        key="backdrop"
        class="sheet-backdrop"
        aria-hidden="true"
        data-testid="sheet-backdrop"
        :initial="{ opacity: 0 }"
        :animate="{ opacity: 1 }"
        :exit="{ opacity: 0 }"
        :transition="{ duration: durationFor(DURATION.base, reduced) }"
        @click="close"
      />
    </AnimatePresence>
    <AnimatePresence>
      <motion.div
        v-if="open"
        key="panel"
        ref="panel"
        class="sheet-panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="labelledby"
        tabindex="-1"
        data-testid="bottom-sheet"
        :initial="reduced ? false : { y: '100%' }"
        :animate="{ y: 0 }"
        :exit="reduced ? undefined : { y: '100%' }"
        :transition="reduced ? { duration: 0 } : SPRING"
        :drag="reduced ? false : 'y'"
        :drag-controls="dragControls"
        :drag-listener="false"
        :drag-constraints="{ top: 0, bottom: 0 }"
        :drag-elastic="{ top: 0, bottom: 0.7 }"
        drag-snap-to-origin
        @drag-end="onDragEnd"
      >
        <div class="sheet-top" @pointerdown="startDrag">
          <span class="sheet-handle" aria-hidden="true"></span>
          <button
            type="button"
            class="btn btn-quiet sheet-close"
            :aria-label="closeLabel"
            @pointerdown.stop
            @click="close"
          >
            <Icon name="x" />
          </button>
        </div>
        <div class="sheet-body">
          <slot />
        </div>
      </motion.div>
    </AnimatePresence>
  </Teleport>
</template>

<style scoped>
/* The bottom tab bar is 1030 and Bootstrap's modals 1055: the sheet sits between, above the bar. */
.sheet-backdrop {
  position: fixed;
  z-index: 1045;
  inset: 0;
  background: rgb(16 42 38 / 45%);
}

.sheet-panel {
  position: fixed;
  z-index: 1046;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  flex-direction: column;
  max-height: 88dvh;
  margin-inline: auto;
  max-width: 40rem;
  border-radius: var(--sl-radius) var(--sl-radius) 0 0;
  background: var(--sl-mist);
  box-shadow: var(--sl-float);
  outline: none;
}

/* The strip you grab: the handle in the middle, the Close button at the right. */
.sheet-top {
  position: relative;
  flex: none;
  display: flex;
  justify-content: center;
  min-height: 3rem;
  padding: 0.7rem 0.5rem 0.4rem;
  cursor: var(--sl-cur-grab);
  touch-action: none;
}

.sheet-handle {
  width: 3rem;
  height: 0.35rem;
  border-radius: 999px;
  background: var(--sl-line);
}

.sheet-close {
  position: absolute;
  top: 0.25rem;
  right: 0.5rem;
  min-width: 2.75rem;
  min-height: 2.75rem;
  cursor: pointer;
}

.sheet-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0.25rem 1.25rem calc(1.25rem + env(safe-area-inset-bottom));
}
</style>
