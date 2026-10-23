<script setup lang="ts">
import type { DailyMetric, PersonState } from '@silverloop/api-client';
import { computed, ref, useId } from 'vue';

import SeniorWeekChart from '@/components/senior/SeniorWeekChart.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { summariseDays } from '@/lib/activity';
import { formatIsoDay } from '@/lib/format-date';

/**
 * "Your activity": today's steps and active minutes, the last week as three numbers, and the
 * week's bars behind a "See my week" button. Describes the numbers only; nothing here decides
 * anything or reads them as a health sign. The status line lives at the top of the page.
 */
const props = withDefaults(
  defineProps<{
    person: PersonState;
    /** The last week's daily readings, oldest first; null while loading or when they failed. */
    week?: DailyMetric[] | null;
    /** This device's today, `YYYY-MM-DD`, to tell whether the latest readings are today's. */
    today: string;
  }>(),
  { week: null },
);

interface Change {
  words: string;
  /** Decoration only: the words say the same thing. */
  emoji: string;
}

/** A change this small (in %, either way) is "About the same as usual". */
const SAME_BAND = 5;

/** Average steps a day over the readings, leaving out `day` (still in progress); null if none. */
function weekAverage(days: readonly DailyMetric[], day: string): number | null {
  const past = days.filter((reading) => reading.day !== day && Number.isFinite(reading.steps));
  if (past.length === 0) return null;
  return past.reduce((sum, reading) => sum + reading.steps, 0) / past.length;
}

/** Whole-number % change from usual; null with no value or no usual day yet (usual of 0). */
function percentChange(value: number | null, usual: number): number | null {
  if (value === null || !Number.isFinite(value) || !Number.isFinite(usual) || usual <= 0) {
    return null;
  }
  const change = Math.round(((value - usual) / usual) * 100);
  // Math.round(-0.4) is -0, which would print as "−0%".
  return change === 0 ? 0 : change;
}

/** "About the same as usual" within ±5%, otherwise "Up 12%" / "Down 12%" (no sign: the word says it). */
function changeWords(change: number): Change {
  if (Math.abs(change) <= SAME_BAND) return { words: 'About the same as usual', emoji: '➡️' };
  return change > 0
    ? { words: `Up ${change}%`, emoji: '⬆️' }
    : { words: `Down ${Math.abs(change)}%`, emoji: '⬇️' };
}

const id = useId();
const showWeek = ref(false);

const steps = computed(() => props.person.signal.current_steps);
const usual = computed(() => props.person.baseline.median_steps);
// The readings' own latest day. In the demo it is a fixed day of the replayed wearable data, not
// this device's today, so the labels say which day the numbers are from.
const readingsDay = computed(() => props.person.current_day);
const isToday = computed(() => readingsDay.value === props.today);
const dayLabel = computed(() =>
  // "Tue 18 Aug", the same as every other reading date on the page.
  isToday.value ? 'today' : `on ${formatIsoDay(readingsDay.value).replace(',', '')}`,
);
/** The latest day's reading, when the week includes it. */
const dayReading = computed<DailyMetric | null>(() => {
  const last = props.week?.at(-1);
  return last && last.day === readingsDay.value ? last : null;
});

// The last week, leaving out the latest day (still in progress), against a usual day.
const weekSteps = computed(() => weekAverage(props.week ?? [], readingsDay.value));
const change = computed(() => percentChange(weekSteps.value, usual.value));
const changeView = computed<Change | null>(() =>
  change.value === null ? null : changeWords(change.value),
);
// The same rule as the family chart's sentence (every day within 20% of usual), in fewer words.
const weekLine = computed(() => {
  if (!props.week?.length) return '';
  const summary = summariseDays(props.week, usual.value);
  if (summary.total === 0) return '';
  return summary.near === summary.total
    ? 'Your week looks steady.'
    : `${summary.near} of ${summary.total} days were close to usual.`;
});

function count(value: number): string {
  return Math.round(value).toLocaleString('en-SG');
}
</script>

<template>
  <BasePanel heading-class="h3 d-flex align-items-center gap-2">
    <template #title><span aria-hidden="true">👟</span>Your activity</template>

    <dl class="stats">
      <div class="stat">
        <dt><span aria-hidden="true">👟</span>Steps {{ dayLabel }}</dt>
        <dd class="tabular" data-testid="steps-today">{{ count(steps) }}</dd>
      </div>
      <div class="stat">
        <dt><Icon name="clock" />Active minutes {{ dayLabel }}</dt>
        <dd class="tabular">{{ dayReading ? count(dayReading.active_minutes) : '—' }}</dd>
      </div>
    </dl>

    <template v-if="week && week.length">
      <h3 class="h5 d-flex align-items-center gap-2 mt-4 mb-3">
        <Icon name="calendar" />The last week
      </h3>

      <ul class="list-unstyled d-flex flex-wrap gap-2 mb-3" data-testid="week-points">
        <li class="flex-fill d-flex align-items-center gap-3 border rounded-3 p-3">
          <span class="fs-4" aria-hidden="true">👟</span>
          <span>
            <span class="d-block small fw-semibold">Last week</span>
            <span class="d-block fs-5 fw-bold tabular">
              {{ weekSteps === null ? '—' : count(weekSteps) }}
              <span class="small fw-normal">a day</span>
            </span>
          </span>
        </li>
        <li class="flex-fill d-flex align-items-center gap-3 border rounded-3 p-3">
          <Icon name="calendar" class="fs-4" />
          <span>
            <span class="d-block small fw-semibold">Usual</span>
            <span class="d-block fs-5 fw-bold tabular">
              {{ usual > 0 ? count(usual) : '—' }}
              <span class="small fw-normal">a day</span>
            </span>
          </span>
        </li>
        <li class="flex-fill d-flex align-items-center gap-3 border rounded-3 p-3">
          <span class="fs-4" aria-hidden="true">{{ changeView?.emoji ?? '⏳' }}</span>
          <span>
            <span class="d-block small fw-semibold">Change</span>
            <span class="d-block fs-5 fw-bold" data-testid="week-change">
              {{ changeView?.words ?? 'Not yet' }}
            </span>
          </span>
        </li>
      </ul>

      <p v-if="weekLine" class="fs-5 mb-3" data-testid="week-line">{{ weekLine }}</p>

      <button
        type="button"
        class="btn btn-outline-primary d-inline-flex align-items-center gap-2"
        :aria-expanded="showWeek"
        :aria-controls="`${id}-week`"
        data-testid="see-my-week"
        @click="showWeek = !showWeek"
      >
        See my week
        <Icon :name="showWeek ? 'chevron-left' : 'chevron-right'" class="toggle-chevron" />
      </button>
      <div v-show="showWeek" :id="`${id}-week`" class="mt-3">
        <SeniorWeekChart :days="week" :usual="usual" />
      </div>
    </template>
  </BasePanel>
</template>

<style scoped>
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: 0.75rem;
  margin: 0;
}

.stat {
  padding: 0.85rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-jade-soft);
}

.stat dt {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--sl-jade-deep);
  font-size: 1rem;
  font-weight: 700;
}

.stat dd {
  margin: 0.15rem 0 0;
  color: var(--sl-ink);
  font-size: 2rem;
  font-weight: 800;
  line-height: 1.1;
}

/* Points down when closed and up when open, as a disclosure arrow does. */
.toggle-chevron {
  transform: rotate(90deg);
}
</style>
