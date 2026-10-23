<script setup lang="ts">
import MemberAvatar from '@/components/family/MemberAvatar.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import Icon from '@/components/ui/Icon.vue';
import { addDays } from '@/lib/calendar';
import { needsHelper } from '@/lib/coverage';
import { KIND_LABELS } from '@/lib/family';
import type { Appointment, FamilyMember } from '@/lib/family';
import { formatClockTime, formatIsoDay } from '@/lib/format-date';

// A button, not a link: choosing an appointment opens its details beside the calendar.
const props = defineProps<{
  appointment: Appointment;
  /** Names of the family members who have taken it, in the order they volunteered. */
  helperNames: string[];
  /** The same people, for their avatars. Optional: the names alone are enough. */
  helpers?: FamilyMember[];
  /** Show the date too, for a list that spans several days. */
  showDate?: boolean;
  /** Today, so a date can say "Tomorrow". */
  today?: string;
}>();
defineEmits<{ select: [] }>();

/** "Today", "Tomorrow", or the date itself: short, and never both. */
function when(iso: string): string {
  if (props.today && iso === props.today) return 'Today';
  if (props.today && iso === addDays(props.today, 1)) return 'Tomorrow';
  return formatIsoDay(iso);
}
</script>

<template>
  <button
    type="button"
    class="appointment list-group-item list-group-item-action"
    :class="`kind-${appointment.kind}`"
    @click="$emit('select')"
  >
    <span class="appt-time">
      <span class="appt-start tabular">{{ formatClockTime(appointment.start) }}</span>
      <span class="appt-end tabular">– {{ formatClockTime(appointment.end) }}</span>
    </span>
    <span class="appt-body">
      <span v-if="showDate" class="appt-date">{{ when(appointment.date) }}</span>
      <span class="appt-title">{{ appointment.title }}</span>
      <span v-if="appointment.location && !showDate" class="appt-where">
        <Icon name="pin" class="me-1" />{{ appointment.location }}
      </span>
      <span class="appt-help">
        <!-- The space sits inside the text "Helping: " because Vue drops whitespace-only text at
             the start of an element and between elements that are on different lines. -->
        <template v-if="helperNames.length">
          <span v-if="helpers?.length" class="appt-avatars">
            <MemberAvatar
              v-for="helper in helpers"
              :key="helper.id"
              :name="helper.name"
              :colour="helper.colour"
              size="sm"
            />
          </span>
          <span class="fw-semibold">{{ helperNames.join(', ') }}</span>
        </template>
        <StatusBadge v-else-if="needsHelper(appointment)" label="Needs helper" tone="warning" />
        <span v-else class="text-body-secondary">No helper needed</span>
      </span>
    </span>
    <span class="appt-kind"
      ><span class="appt-kind-dot" aria-hidden="true"></span
      >{{ KIND_LABELS[appointment.kind] }}</span
    >
  </button>
</template>

<style scoped>
/* The kind's colour runs down the left edge; its name is the badge on the right. */
.appointment {
  display: grid;
  grid-template-columns: 5.5rem minmax(0, 1fr) auto;
  gap: 0.25rem 0.85rem;
  align-items: start;
  padding: 0.75rem 1rem 0.75rem 0.9rem;
  border-left: 4px solid var(--kind);
  transition: background-color 0.15s ease;
}

/* The category, quietly: a dot in its colour and its name, not a solid badge. */
.appt-kind {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--sl-ink-soft);
  font-size: 0.8rem;
  font-weight: 600;
  white-space: nowrap;
}

.appt-kind-dot {
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--kind);
}

.appt-time {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.appt-start {
  font-weight: 800;
}

.appt-end {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
}

.appt-body {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.appt-date {
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
  font-weight: 700;
}

.appt-title {
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.3;
}

.appt-where {
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
}

.appt-help {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.35rem;
  font-size: 0.9rem;
}

.appt-avatars {
  display: inline-flex;
}

.appt-avatars > * + * {
  margin-left: -0.45rem;
  box-shadow: 0 0 0 2px var(--sl-surface);
}

@media (max-width: 575.98px) {
  .appointment {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .appt-time {
    flex-direction: row;
    gap: 0.35rem;
    grid-row: 1;
    grid-column: 1;
  }

  .appt-kind {
    grid-row: 1;
    grid-column: 2;
  }

  .appt-body {
    grid-row: 2;
    grid-column: 1 / -1;
  }
}
</style>
