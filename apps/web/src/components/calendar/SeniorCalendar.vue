<script setup lang="ts">
import { computed, ref } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamily } from '@/composables/useFamily';
import { addDays } from '@/lib/calendar';
import { needsHelper } from '@/lib/coverage';
import { KIND_LABELS } from '@/lib/family';
import type { FamilyMember } from '@/lib/family';
import { WEEKDAYS_LONG, formatClockTime, formatIsoDay, parseIsoDay } from '@/lib/format-date';

/**
 * The senior's own calendar: a simple, view-only week, in big text. Each day lists what is on,
 * when, and who is coming along. Nothing here can be changed; the family does that on the Calendar
 * page. It reads the family calendar itself (`useFamily`), so the Senior page only has to add:
 *
 *   <SeniorCalendar />
 */
const family = useFamily();
const { today, appointments, state } = family;

/** 0 = this week (today and the next six days), 1 = the week after, and so on. */
const week = ref(0);
const days = computed(() =>
  Array.from({ length: 7 }, (_, offset) => {
    const iso = addDays(today, week.value * 7 + offset);
    const parts = parseIsoDay(iso);
    return {
      iso,
      name:
        iso === today
          ? 'Today'
          : iso === addDays(today, 1)
            ? 'Tomorrow'
            : parts
              ? WEEKDAYS_LONG[parts.weekday]
              : iso,
      date: formatIsoDay(iso),
      items: appointments.filter((appointment) => appointment.date === iso),
    };
  }),
);
const rangeLabel = computed(() =>
  week.value === 0
    ? 'This week'
    : `${formatIsoDay(days.value[0].iso)} to ${formatIsoDay(days.value[6].iso)}`,
);

function helpersOf(appointmentId: string): FamilyMember[] {
  return family
    .helperIdsOf(appointmentId)
    .map((id) => state.members.find((member) => member.id === id))
    .filter((member): member is FamilyMember => member !== undefined);
}

/** Who is coming, in plain words: "Sarah is coming with you", "Sarah and John are coming". */
function comingWords(appointmentId: string): string {
  const names = helpersOf(appointmentId).map((member) => member.name);
  if (names.length === 1) return `${names[0]} is coming with you`;
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)} are coming with you`;
}
</script>

<template>
  <section class="sl-panel senior-cal" aria-labelledby="senior-cal-heading">
    <div class="senior-cal-head">
      <h2 id="senior-cal-heading" class="h3 mb-0">My calendar</h2>
      <div class="senior-cal-nav" role="group" aria-label="Week">
        <button
          type="button"
          class="btn btn-outline-primary"
          aria-label="Earlier week"
          :disabled="week === 0"
          @click="week--"
        >
          <Icon name="chevron-left" />
        </button>
        <span class="fw-bold" aria-live="polite">{{ rangeLabel }}</span>
        <button
          type="button"
          class="btn btn-outline-primary"
          aria-label="Later week"
          :disabled="week >= 3"
          @click="week++"
        >
          <Icon name="chevron-right" />
        </button>
      </div>
    </div>

    <ol class="senior-days">
      <li
        v-for="day in days"
        :key="day.iso"
        class="senior-day"
        :class="{ today: day.iso === today }"
      >
        <h3 class="senior-day-name">
          {{ day.name }} <span class="senior-day-date">{{ day.date }}</span>
        </h3>
        <p v-if="!day.items.length" class="senior-free mb-0">Nothing planned</p>
        <ul v-else class="senior-items">
          <li
            v-for="item in day.items"
            :key="item.id"
            class="senior-item"
            :class="`kind-${item.kind}`"
          >
            <span class="senior-time tabular">
              {{ formatClockTime(item.start) }} – {{ formatClockTime(item.end) }}
            </span>
            <span class="senior-title">{{ item.title }}</span>
            <span class="senior-kind">
              <span class="senior-kind-dot" aria-hidden="true"></span>{{ KIND_LABELS[item.kind] }}
            </span>
            <span v-if="item.location" class="senior-where">
              <Icon name="pin" class="me-1" />{{ item.location }}
            </span>
            <span v-if="helpersOf(item.id).length" class="senior-who">
              <span class="senior-avatars">
                <MemberAvatar
                  v-for="helper in helpersOf(item.id)"
                  :key="helper.id"
                  :name="helper.name"
                  :colour="helper.colour"
                  size="sm"
                />
              </span>
              {{ comingWords(item.id) }}
            </span>
            <span v-else-if="needsHelper(item)" class="senior-who senior-who-open">
              Your family is arranging who comes
            </span>
          </li>
        </ul>
      </li>
    </ol>
  </section>
</template>

<style scoped>
/* Big, calm and readable: an older reader's own week. */
.senior-cal {
  font-size: 1.1rem;
}

.senior-cal-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.senior-cal-nav {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.senior-days {
  display: grid;
  gap: 0.75rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.senior-day {
  padding: 0.85rem 1rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
}

.senior-day.today {
  border: 2px solid var(--sl-jade);
}

.senior-day-name {
  margin-bottom: 0.5rem;
  font-size: 1.25rem;
}

.senior-day-date {
  color: var(--sl-ink-soft);
  font-size: 1rem;
  font-weight: 600;
}

.senior-free {
  color: var(--sl-ink-soft);
}

.senior-items {
  display: grid;
  gap: 0.6rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.senior-item {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.6rem 0.85rem;
  border-left: 6px solid var(--kind);
  border-radius: 0.5rem;
  background: color-mix(in srgb, var(--kind) 9%, var(--sl-surface));
}

.senior-time {
  font-weight: 800;
}

.senior-title {
  font-size: 1.2rem;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.senior-kind,
.senior-where {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--sl-ink-soft);
  font-size: 0.95rem;
}

.senior-kind-dot {
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 50%;
  background: var(--kind);
}

.senior-who {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.2rem;
  font-weight: 600;
}

.senior-who-open {
  color: var(--sl-ink-soft);
  font-weight: 500;
}

.senior-avatars {
  display: inline-flex;
}

.senior-avatars > * + * {
  margin-left: -0.4rem;
  box-shadow: 0 0 0 2px var(--sl-surface);
}
</style>
