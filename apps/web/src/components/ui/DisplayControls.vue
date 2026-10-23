<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue';
import { useDisplay } from '@/composables/useDisplay';

/** The top bar's display settings: zoom by percentage, and light or dark. */
const display = useDisplay();
const { zoom, theme } = display;
</script>

<template>
  <div class="display">
    <div class="zoom" role="group" aria-label="Zoom">
      <button
        type="button"
        class="zoom-btn"
        aria-label="Zoom out"
        title="Zoom out"
        :disabled="!display.canZoomOut()"
        @click="display.zoomOut()"
      >
        <span aria-hidden="true">−</span>
      </button>
      <button
        type="button"
        class="zoom-value tabular"
        :aria-label="`Zoom ${zoom}%. Reset to 100%`"
        title="Reset to 100%"
        data-testid="zoom-value"
        @click="display.resetZoom()"
      >
        {{ zoom }}%
      </button>
      <button
        type="button"
        class="zoom-btn"
        aria-label="Zoom in"
        title="Zoom in"
        :disabled="!display.canZoomIn()"
        @click="display.zoomIn()"
      >
        <span aria-hidden="true">+</span>
      </button>
    </div>
    <button
      type="button"
      class="theme-btn"
      :aria-label="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'"
      :title="theme === 'dark' ? 'Light mode' : 'Dark mode'"
      :aria-pressed="theme === 'dark'"
      data-testid="theme-toggle"
      @click="display.toggleTheme()"
    >
      <Icon :name="theme === 'dark' ? 'sun' : 'moon'" />
    </button>
  </div>
</template>

<style scoped>
.display {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.zoom {
  display: inline-flex;
  align-items: center;
  padding: 0.15rem;
  border: 2px solid var(--sl-line);
  border-radius: 999px;
  background: var(--sl-surface);
}

.zoom-btn,
.zoom-value,
.theme-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 2.25rem;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--sl-ink);
  font-weight: 700;
  line-height: 1;
  transition: background-color 0.15s ease;
}

.zoom-btn {
  width: 2.25rem;
  font-size: 1.25rem;
}

.zoom-value {
  min-width: 3.4rem;
  padding: 0 0.3rem;
  font-size: 0.9rem;
}

.zoom-btn:hover:not(:disabled),
.zoom-value:hover,
.theme-btn:hover {
  background: var(--bs-tertiary-bg);
}

/* The focus ring hugs each button, so it never covers the percentage beside it. */
.zoom-btn:focus-visible,
.zoom-value:focus-visible {
  outline-offset: -2px;
}

.zoom-btn:disabled {
  color: var(--sl-line);
}

.theme-btn {
  width: 2.6rem;
  height: 2.6rem;
  border: 2px solid var(--sl-line);
  background: var(--sl-surface);
  font-size: 1.15rem;
}
</style>
