<script setup lang="ts">
import { KIND_LABELS } from '@/lib/family';
import type { AppointmentKind } from '@/lib/family';

/**
 * The calendar's colour legend, made pressable: each event type is a chip in its own colour that
 * shows or hides that type, and one more chip narrows everything to what still needs a helper. Each
 * chip is a toggle button (`aria-pressed`), so its state is announced as well as drawn, and every
 * colour comes with its name, never colour alone.
 *
 * The colours are the shared `.kind-*` ones in `theme.css`, so new event colours there apply here
 * and on the calendar with no change in this file. Tasks are in the legend too (not a filter).
 */
defineProps<{ shown: ReadonlySet<AppointmentKind>; onlyOpen: boolean; filtersOn: boolean }>();
defineEmits<{ toggle: [kind: AppointmentKind]; 'toggle-open': []; clear: [] }>();

const kinds = Object.keys(KIND_LABELS) as AppointmentKind[];
</script>

<template>
  <div class="filters" role="group" aria-label="Event types: show or hide">
    <button
      v-for="kind in kinds"
      :key="kind"
      type="button"
      class="sl-chip kind-chip"
      :class="`kind-${kind}`"
      :aria-pressed="shown.has(kind)"
      @click="$emit('toggle', kind)"
    >
      <span class="sl-chip-swatch" aria-hidden="true"></span>{{ KIND_LABELS[kind] }}
    </button>
    <span class="legend-task kind-task" title="Tasks from Home show with a dashed edge">
      <span class="legend-task-swatch" aria-hidden="true"></span>Task
    </span>
    <button
      type="button"
      class="sl-chip"
      style="--chip: var(--sl-coral)"
      :aria-pressed="onlyOpen"
      @click="$emit('toggle-open')"
    >
      <span class="sl-chip-swatch" aria-hidden="true"></span>Needs helper
    </button>
    <button v-if="filtersOn" type="button" class="btn btn-link btn-sm" @click="$emit('clear')">
      Show all
    </button>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}

/* Lighter, smaller chips than elsewhere: these are a legend first and switches second. */
.sl-chip {
  min-height: 2.25rem;
  padding: 0.2rem 0.75rem;
  border-width: 1px;
  font-size: 0.9rem;
}

/* Each type chip takes its colour from the shared `.kind-*` class. */
.kind-chip {
  --chip: var(--kind);
}

/* Tasks: a legend entry only, drawn like a task chip on the calendar (dashed edge). */
.legend-task {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  min-height: 2.25rem;
  padding: 0.2rem 0.75rem;
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
  font-weight: 600;
}

.legend-task-swatch {
  width: 0.8rem;
  height: 0.8rem;
  border: 2px dashed var(--kind);
  border-radius: 0.15rem;
}
</style>
