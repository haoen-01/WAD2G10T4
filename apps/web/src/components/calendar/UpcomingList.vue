<script lang="ts">
import { defineComponent, type PropType } from 'vue';

import AppointmentCard from '@/components/calendar/AppointmentCard.vue';
import type { Appointment, FamilyMember } from '@/lib/family';

/**
 * "Coming up": the next few appointments after the chosen day. When the filters hide all of
 * them it says so, with a "Show everything" button that emits `clear-filters`.
 */
export default defineComponent({
  name: 'UpcomingList',
  components: { AppointmentCard },

  props: {
    appointments: { type: Array as PropType<Appointment[]>, required: true },
    today: { type: String, required: true },
    filtersOn: { type: Boolean, default: false },
    helpersOf: {
      type: Function as PropType<(appointment: Appointment) => FamilyMember[]>,
      required: true,
    },
  },

  emits: {
    select: (appointment: Appointment) => Boolean(appointment),
    'clear-filters': () => true,
  },

  methods: {
    helperNames(appointment: Appointment): string[] {
      return this.helpersOf(appointment).map((member) => member.name);
    },
  },
});
</script>

<template>
  <section v-if="appointments.length" aria-labelledby="coming-heading">
    <h2 id="coming-heading" class="h4">Coming up</h2>
    <!-- A full-width row: the cards sit side by side, as many as fit. -->
    <div class="cards">
      <AppointmentCard
        v-for="appointment in appointments"
        :key="appointment.id"
        :appointment="appointment"
        :helper-names="helperNames(appointment)"
        :helpers="helpersOf(appointment)"
        :today="today"
        show-date
        @select="$emit('select', appointment)"
      />
    </div>
  </section>
  <p v-else-if="filtersOn" class="empty">
    Nothing coming up matches the filters.
    <button type="button" class="btn btn-link p-0 align-baseline" @click="$emit('clear-filters')">
      Show everything
    </button>
  </p>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
  gap: 0.75rem;
}

/* Each card on its own, not joined like a list. */
.cards :deep(.appointment) {
  height: 100%;
  border: 1px solid var(--sl-line);
  border-left: 4px solid var(--kind);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
}

.empty {
  padding: 1rem 1.25rem;
  border: 2px dashed var(--sl-line);
  border-radius: var(--sl-radius-sm);
  color: var(--sl-ink-soft);
}
</style>
