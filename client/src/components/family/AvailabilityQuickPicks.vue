<script setup lang="ts">
import { computed, ref } from 'vue';

import { addDays } from '@/lib/calendar';
import type { AvailabilityEntry } from '@/lib/family';
import { DAY_PARTS } from '@/lib/family';
import { WEEKDAYS_LONG, formatIsoDay, parseIsoDay } from '@/lib/format-date';
import { activeDayParts, type DayPartKey } from '@/lib/planner';

/**
 * "When can you help?" the quick way: for each day of the week, Morning, Afternoon, Evening or All
 * day, each a toggle button (`aria-pressed`). A pick is on only when a saved "free" window matches
 * it exactly (`activeDayParts`), so hours chosen in the exact-hours painter never light one up by
 * accident. The parent saves the change (`useFamily().pickDayPart`).
 */
const props = defineProps<{
  today: string;
  memberId: string;
  availability: AvailabilityEntry[];
}>();
const emit = defineEmits<{ pick: [day: string, part: DayPartKey] }>();

// The parts in the order a day runs, with All day last.
const PARTS = [...DAY_PARTS.filter((part) => part.key !== 'all-day'), DAY_PARTS[0]];

const week = ref(0);
/** The two weeks, as a segmented control: the one shown is pressed, with its dates. */
const WEEKS = computed(() =>
  [0, 1].map((offset) => {
    const start = addDays(props.today, offset * 7);
    const end = addDays(start, 6);
    return {
      offset,
      label: offset === 0 ? 'This week' : 'Next week',
      dates: `${formatIsoDay(start, { weekday: false })} – ${formatIsoDay(end, { weekday: false })}`,
    };
  }),
);
const days = computed(() =>
  Array.from({ length: 7 }, (_, offset) => {
    const iso = addDays(props.today, week.value * 7 + offset);
    const parts = parseIsoDay(iso);
    const name = parts ? `${WEEKDAYS_LONG[parts.weekday]} ${parts.day}` : iso;
    return {
      iso,
      name: iso === props.today ? `Today (${name})` : name,
      on: activeDayParts(props.availability, props.memberId, iso),
    };
  }),
);
</script>

<template>
  <div class="quick" data-testid="quick-picks">
    <div class="quick-week mb-3" role="group" aria-label="Which week">
      <button
        v-for="option in WEEKS"
        :key="option.offset"
        type="button"
        class="quick-week-option"
        :aria-pressed="week === option.offset"
        @click="week = option.offset"
      >
        <span class="quick-week-label">{{ option.label }}</span>
        <span class="quick-week-dates">{{ option.dates }}</span>
      </button>
    </div>
    <ul class="quick-days">
      <li v-for="day in days" :key="day.iso" class="quick-day" :data-day="day.iso">
        <span :id="`quick-${day.iso}`" class="quick-name">{{ day.name }}</span>
        <span class="quick-parts" role="group" :aria-labelledby="`quick-${day.iso}`">
          <button
            v-for="part in PARTS"
            :key="part.key"
            type="button"
            class="sl-chip quick-chip"
            :aria-pressed="day.on.has(part.key)"
            :title="part.label"
            @click="emit('pick', day.iso, part.key)"
          >
            {{ part.short }}
          </button>
        </span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
/* A two-part segmented control: the week shown is the filled half. */
.quick-week {
  display: inline-flex;
  max-width: 100%;
  padding: 0.25rem;
  border-radius: 999px;
  background: var(--sl-raised);
}

.quick-week-option {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 2.75rem;
  padding: 0.3rem 1rem;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--sl-ink);
  line-height: 1.2;
}

.quick-week-label {
  font-weight: 700;
}

.quick-week-dates {
  color: var(--sl-ink-soft);
  font-size: 0.8rem;
}

.quick-week-option[aria-pressed='true'] {
  background: var(--sl-jade);
  color: var(--sl-jade-on);
}

.quick-week-option[aria-pressed='true'] .quick-week-dates {
  color: inherit;
}

@media (hover: hover) and (pointer: fine) {
  .quick-week-option[aria-pressed='false']:hover .quick-week-label {
    text-decoration: underline;
  }
}

.quick-days {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* One row a day: the day's name, then its four picks. They wrap under the name when narrow. */
.quick-day {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
  padding: 0.6rem 0;
  border-top: 1px solid var(--sl-line);
}

.quick-day:first-child {
  border-top: 0;
}

.quick-name {
  flex: 1 1 9rem;
  font-weight: 700;
}

.quick-parts {
  display: grid;
  grid-template-columns: repeat(4, auto);
  gap: 0.4rem;
}

@media (max-width: 575.98px) {
  .quick-parts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }
}

.quick-chip {
  justify-content: center;
  padding-inline: 0.8rem;
}
</style>
