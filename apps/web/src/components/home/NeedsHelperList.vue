<script setup lang="ts">
import { RouterLink } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import type { Appointment } from '@/lib/family';
import { visitWhen } from '@/lib/today';

/**
 * "Needs someone to go along": the coming visits nobody has taken yet, each with its actual day and
 * times. The title opens it in the calendar; "I'll go" takes it from here, without the calendar.
 * Home owns the change (`useFamily().volunteer`), so this only emits. When every visit has someone,
 * it says so instead of disappearing.
 */
defineProps<{
  appointments: Appointment[];
  elder: string;
  /** Whether the viewer is in the group and so can take a visit. If not, no button is shown. */
  canVolunteer: boolean;
}>();

defineEmits<{ volunteer: [appointment: Appointment] }>();
</script>

<template>
  <section class="needs" :class="{ covered: !appointments.length }" aria-labelledby="needs-heading">
    <h2 id="needs-heading" class="h4 d-flex align-items-center gap-2 mb-1">
      <Icon :name="appointments.length ? 'user-plus' : 'check-circle'" class="needs-icon" />
      Needs someone to go along
    </h2>

    <p v-if="!appointments.length" class="mb-0">
      Everyone is covered for the next 2 weeks. Thank you!
    </p>

    <template v-else>
      <p class="mb-3 text-body-secondary">
        {{ appointments.length }} {{ appointments.length === 1 ? 'visit' : 'visits' }} · next 2
        weeks
      </p>
      <ul class="needs-list">
        <li v-for="item in appointments" :key="item.id" class="needs-item">
          <RouterLink
            class="needs-link"
            :to="{ path: '/calendar', query: { appointment: item.id } }"
          >
            <span class="needs-title">{{ item.title }}</span>
            <span class="needs-when">
              <Icon name="clock" class="me-1" />{{ visitWhen(item.date, item.start, item.end) }}
            </span>
          </RouterLink>
          <button
            v-if="canVolunteer"
            type="button"
            class="btn btn-primary needs-go"
            :aria-label="`I’ll go with ${elder} to ${item.title}, ${visitWhen(item.date, item.start, item.end)}`"
            @click="$emit('volunteer', item)"
          >
            <Icon name="user-plus" class="me-1" />I’ll go
          </button>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.needs {
  display: flex;
  flex-direction: column;
  padding: 1.25rem;
  border: 1px solid var(--sl-line);
  border-left: 4px solid var(--sl-coral);
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
}

/* Nothing left to cover: calm, not alarming. */
.needs.covered {
  border-color: var(--sl-line);
  border-left-color: var(--sl-jade);
}

.needs-icon {
  width: 1.6rem;
  height: 1.6rem;
  flex: none;
  color: var(--sl-coral);
}

.covered .needs-icon {
  color: var(--sl-jade);
}

.needs-list {
  display: grid;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* Bootstrap cannot express "the link takes the room, the button keeps its size, and the button
   drops under the link when the row gets too narrow". */
.needs-item {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 0.5rem;
  padding: 0.5rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
}

.needs-link {
  display: flex;
  flex: 1 1 14rem;
  flex-direction: column;
  justify-content: center;
  gap: 0.15rem;
  min-height: 2.75rem;
  padding: 0.25rem 0.35rem;
  border-radius: var(--sl-radius-sm);
  color: var(--sl-ink);
  text-decoration: none;
}

.needs-link:hover .needs-title {
  text-decoration: underline;
}

.needs-title {
  font-weight: 700;
}

.needs-when {
  display: inline-flex;
  align-items: center;
  font-size: 0.95rem;
}

.needs-go {
  display: inline-flex;
  flex: none;
  align-items: center;
  align-self: center;
  min-height: 2.75rem;
  font-weight: 700;
}
</style>
