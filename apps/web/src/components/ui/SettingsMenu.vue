<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';

/**
 * One quiet round button that opens a small panel of settings (the slot): zoom, light or dark, who
 * to show, Sign out. A disclosure, not an ARIA menu: the panel holds ordinary controls, so Tab walks
 * through them. Escape closes it and returns focus to the button; so does a click outside or Tab
 * leaving the panel. The slot gets `close` for items that should dismiss it.
 */
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const button = ref<HTMLButtonElement | null>(null);
// One id per menu; `aria-controls` points at it only while the panel exists.
const panelId = `settings-${useId()}`;

function close(returnFocus = false) {
  open.value = false;
  if (returnFocus) void nextTick(() => button.value?.focus());
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.stopPropagation();
    close(true);
  }
}

function onFocusout(event: FocusEvent) {
  // Focus moved to something outside the menu (Tab off the end). A null target (a click that did
  // not focus, as on Safari) is left to the outside-click handler.
  const next = event.relatedTarget as Node | null;
  if (open.value && next && !root.value?.contains(next)) close();
}

function onPointerdown(event: PointerEvent) {
  if (open.value && !root.value?.contains(event.target as Node)) close();
}

watch(open, (isOpen) => {
  if (isOpen) document.addEventListener('pointerdown', onPointerdown);
  else document.removeEventListener('pointerdown', onPointerdown);
});
onBeforeUnmount(() => document.removeEventListener('pointerdown', onPointerdown));
</script>

<template>
  <div ref="root" class="settings" @keydown="onKeydown" @focusout="onFocusout">
    <button
      ref="button"
      type="button"
      class="settings-btn"
      aria-label="Settings"
      title="Settings"
      :aria-expanded="open"
      :aria-controls="open ? panelId : undefined"
      @click="open = !open"
    >
      <Icon name="sliders" />
    </button>
    <Transition name="settings-pop">
      <div v-if="open" :id="panelId" class="settings-panel" role="group" aria-label="Settings">
        <slot :close="close" />
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.settings {
  position: relative;
}

.settings-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border: 1px solid var(--sl-glass-border);
  border-radius: 50%;
  background: transparent;
  color: var(--sl-ink-soft);
  font-size: 1.15rem;
  transition:
    background-color var(--sl-dur-base) ease,
    color var(--sl-dur-base) ease;
}

.settings-btn:hover,
.settings-btn[aria-expanded='true'] {
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink);
}

.settings-panel {
  position: absolute;
  z-index: 1;
  top: calc(100% + 0.5rem);
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.75rem;
  width: max-content;
  min-width: 16rem;
  max-width: calc(100vw - 1.5rem);
  padding: 1rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  box-shadow: var(--sl-elev-2);
  transform-origin: top right;
}

.settings-pop-enter-active,
.settings-pop-leave-active {
  transition:
    opacity var(--sl-dur-base) ease,
    transform var(--sl-dur-base) var(--sl-ease);
}

.settings-pop-enter-from,
.settings-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}
</style>
