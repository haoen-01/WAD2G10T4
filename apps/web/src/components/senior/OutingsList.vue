<script setup lang="ts">
import MemberAvatar from '@/components/family/MemberAvatar.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import type { Appointment, FamilyMember } from '@/lib/family';
import { formatClockTime } from '@/lib/format-date';
import { relativeDay } from '@/lib/today';

/** Her outings (today's, on the senior screen), and who from the family is going with her. */
withDefaults(
  defineProps<{
    appointments: Appointment[];
    today: string;
    title?: string;
    emptyText?: string;
    /** Who is going along to one appointment. */
    companionsOf: (appointmentId: string) => FamilyMember[];
  }>(),
  { title: 'Coming up for you', emptyText: 'Nothing planned.' },
);

/** "Sarah", "Sarah and Emily", "Sarah, John and Emily". */
function joinNames(people: FamilyMember[]): string {
  const names = people.map((person) => person.name);
  return names.length <= 1
    ? names.join('')
    : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
}
</script>

<template>
  <BasePanel heading-class="h3 d-flex align-items-center gap-2">
    <template #title><Icon name="calendar" />{{ title }}</template>
    <p v-if="appointments.length === 0" class="fs-5 mb-0">
      {{ emptyText }}
    </p>
    <ul v-else class="outings">
      <li v-for="item in appointments" :key="item.id" :class="`kind-${item.kind}`">
        <span class="outing-when">
          <span class="d-block fw-bold">{{ relativeDay(item.date, today) }}</span>
          <span class="d-flex align-items-center gap-1 tabular">
            <Icon name="clock" />{{ formatClockTime(item.start) }}
          </span>
        </span>
        <span class="outing-body">
          <span class="d-block fs-5 fw-bold">{{ item.title }}</span>
          <span v-if="item.location" class="d-flex align-items-center gap-1">
            <Icon name="pin" />{{ item.location }}
          </span>
          <span v-if="companionsOf(item.id).length" class="outing-with">
            <MemberAvatar
              v-for="helper in companionsOf(item.id)"
              :key="helper.id"
              :name="helper.name"
              :colour="helper.colour"
              size="sm"
            />
            With {{ joinNames(companionsOf(item.id)) }}
          </span>
          <span v-else class="outing-with">
            <Icon name="users" />Family is arranging a helper
          </span>
        </span>
      </li>
    </ul>
  </BasePanel>
</template>

<style scoped>
.outings {
  display: grid;
  gap: 0.75rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.outings li {
  display: flex;
  gap: 1rem;
  padding: 0.85rem 1rem;
  border-left: 6px solid var(--kind);
  border-radius: var(--sl-radius-sm);
  background: color-mix(in srgb, var(--kind) 7%, var(--sl-surface));
}

.outing-when {
  flex: none;
  width: 6.5rem;
}

.outing-with {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.4rem;
  font-size: 1rem;
  font-weight: 600;
}

@media (max-width: 575.98px) {
  .outings li {
    flex-direction: column;
    gap: 0.25rem;
  }
}
</style>
