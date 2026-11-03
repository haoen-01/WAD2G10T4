<script setup lang="ts">
import CoverageSummary from '@/components/calendar/CoverageSummary.vue';
import KindFilter from '@/components/calendar/KindFilter.vue';
import type { Coverage } from '@/lib/coverage';
import type { AppointmentKind } from '@/lib/family';

/** The coverage card and the legend that doubles as filters, on one bar. */
defineProps<{
  coverage: Coverage;
  shown: ReadonlySet<AppointmentKind>;
  onlyOpen: boolean;
  filtersOn: boolean;
}>();
defineEmits<{ toggle: [kind: AppointmentKind]; 'toggle-open': []; clear: [] }>();
</script>

<template>
  <div class="toolbar">
    <CoverageSummary :coverage="coverage" />
    <KindFilter
      :shown="shown"
      :only-open="onlyOpen"
      :filters-on="filtersOn"
      @toggle="$emit('toggle', $event)"
      @toggle-open="$emit('toggle-open')"
      @clear="$emit('clear')"
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem 1.5rem;
  margin-bottom: 1rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
}
</style>
