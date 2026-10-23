<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import {
  GENTLE_NUDGE_PERCENT,
  formatSteps,
  fortnightSentence,
  isNearUsual,
  percentOfUsual,
  summariseDays,
} from '@/lib/activity';
import type { StepDay } from '@/lib/activity';
import { formatIsoDay, parseIsoDay } from '@/lib/format-date';

/**
 * The last fortnight of steps as bars, drawn with plain HTML and CSS. Each bar is a button, so a
 * keyboard, a mouse and a finger can all pick a day; the chosen day is read out in words below the
 * chart. Two lines give the bars meaning: her usual day, and 20% below it (the first point at which
 * Care+ might suggest anything). A bar below that line is drawn in coral and says so in words.
 */
// `owner` is whose usual day it is: "her" for the family, "your" on the senior's own screen.
const props = withDefaults(defineProps<{ days: StepDay[]; usual: number; owner?: string }>(), {
  owner: 'her',
});

const selected = ref<string | null>(null);
watch(
  () => props.days,
  (days) => {
    selected.value = days.at(-1)?.day ?? null;
  },
  { immediate: true },
);

const summary = computed(() => summariseDays(props.days, props.usual));
const sentence = computed(() => fortnightSentence(summary.value, props.owner));

// The top of the chart: the busiest day or a fifth above usual, whichever is higher.
const top = computed(() => Math.max(props.usual * 1.2, ...props.days.map((day) => day.steps), 1));
const heightOf = (steps: number) => `${Math.max(2, (steps / top.value) * 100)}%`;
const usualLine = computed(() => `${(props.usual / top.value) * 100}%`);
const nudgeLine = computed(
  () => `${((props.usual * (100 - GENTLE_NUDGE_PERCENT)) / 100 / top.value) * 100}%`,
);

const dayNumber = (iso: string) => parseIsoDay(iso)?.day ?? '';
const describe = (day: StepDay) => {
  const percent = percentOfUsual(day.steps, props.usual);
  const parts = [`${formatIsoDay(day.day)}: ${formatSteps(day.steps)}`];
  if (percent !== null) parts.push(`${percent}% of ${props.owner} usual day`);
  if (!isNearUsual(day.steps, props.usual))
    parts.push(`more than ${GENTLE_NUDGE_PERCENT}% below usual`);
  return parts.join(', ');
};

const chosen = computed(() => props.days.find((day) => day.day === selected.value) ?? null);

// Arrow keys move between bars, as in any row of options.
const bars = ref<HTMLButtonElement[]>([]);
function onKey(event: KeyboardEvent, index: number) {
  const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
  if (!step) return;
  event.preventDefault();
  const next = Math.min(props.days.length - 1, Math.max(0, index + step));
  selected.value = props.days[next].day;
  bars.value[next]?.focus();
}
</script>

<template>
  <div class="chart-wrap">
    <p class="mb-3">{{ sentence }}</p>

    <div
      class="chart"
      role="group"
      aria-label="Steps on each of the last days. Choose a day for details."
    >
      <div class="plot">
        <div class="chart-line usual" :style="{ bottom: usualLine }" aria-hidden="true">
          <span>Usual day</span>
        </div>
        <div class="chart-line nudge" :style="{ bottom: nudgeLine }" aria-hidden="true">
          <span>{{ GENTLE_NUDGE_PERCENT }}% below usual</span>
        </div>

        <button
          v-for="(day, index) in days"
          :key="day.day"
          ref="bars"
          type="button"
          class="bar-btn"
          :class="{ low: !isNearUsual(day.steps, usual), chosen: day.day === selected }"
          :aria-pressed="day.day === selected"
          :aria-label="describe(day)"
          :tabindex="day.day === selected ? 0 : -1"
          :style="{ '--delay': `${index * 35}ms` }"
          @click="selected = day.day"
          @keydown="onKey($event, index)"
        >
          <span class="bar" :style="{ height: heightOf(day.steps) }"></span>
        </button>
      </div>
      <div class="labels" aria-hidden="true">
        <span v-for="day in days" :key="day.day" :class="{ chosen: day.day === selected }">{{
          dayNumber(day.day)
        }}</span>
      </div>
    </div>

    <p v-if="chosen" class="chart-readout" aria-live="polite">
      <strong>{{ formatIsoDay(chosen.day, { style: 'long' }) }}</strong>
      <span class="d-block">
        {{ formatSteps(chosen.steps) }}
        <template v-if="percentOfUsual(chosen.steps, usual) !== null">
          ({{ percentOfUsual(chosen.steps, usual) }}% of {{ owner }} usual day)</template
        ><template v-if="chosen.active_minutes !== undefined">
          and {{ chosen.active_minutes }} active minutes</template
        >.
        <template v-if="!isNearUsual(chosen.steps, usual)">
          That is more than {{ GENTLE_NUDGE_PERCENT }}% below {{ owner }} usual day.
        </template>
      </span>
    </p>
  </div>
</template>

<style scoped>
.plot {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: 0.3rem;
  /* The main picture on Home: tall on a wide screen, still compact on a phone. */
  height: clamp(10rem, 18vw, 13rem);
  border-bottom: 2px solid var(--sl-line);
}

.labels {
  display: flex;
  gap: 0.3rem;
  margin-top: 0.35rem;
  color: var(--sl-ink-soft);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
}

.labels span {
  flex: 1;
  min-width: 0;
  text-align: center;
}

.labels .chosen {
  color: var(--sl-ink);
  font-weight: 800;
}

.chart-line {
  position: absolute;
  z-index: 1;
  right: 0;
  left: 0;
  border-top: 2px dashed var(--sl-ink);
  pointer-events: none;
}

.chart-line span {
  position: absolute;
  bottom: 0.2rem;
  left: 0;
  padding: 0.05rem 0.45rem;
  border-radius: 0.35rem;
  background: var(--sl-surface);
  color: var(--sl-ink);
  font-size: 0.75rem;
  font-weight: 700;
  box-shadow: 0 0 0 1px var(--sl-line);
}

.chart-line.nudge {
  border-top: 2px dotted var(--sl-coral);
}

.chart-line.nudge span {
  top: 0.25rem;
  bottom: auto;
  color: var(--sl-coral-deep);
}

.bar-btn {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: flex-end;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0.5rem 0.5rem 0 0;
  background: transparent;
}

.bar-btn:hover,
.bar-btn.chosen {
  background: color-mix(in srgb, var(--sl-jade) 8%, transparent);
}

.bar-btn:hover .bar,
.bar-btn.chosen .bar {
  background: var(--sl-jade-deep);
}

.bar {
  display: block;
  width: 100%;
  border-radius: 0.45rem 0.45rem 0 0;
  background: color-mix(in srgb, var(--sl-jade) 62%, var(--sl-surface));
  transform-origin: bottom;
  animation: grow 0.6s var(--sl-ease) both;
  animation-delay: var(--delay);
  transition: background-color 0.15s ease;
}

.bar-btn.low .bar {
  background: color-mix(in srgb, var(--sl-coral) 70%, var(--sl-surface));
}

.bar-btn.low:hover .bar,
.bar-btn.low.chosen .bar {
  background: var(--sl-coral-deep);
}

.chart-readout {
  margin: 1rem 0 0;
  padding: 0.75rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-mist);
}

@keyframes grow {
  from {
    transform: scaleY(0);
  }
}
</style>
