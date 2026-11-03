<script setup lang="ts">
import type { DailyMetric } from '@silverloop/api-client';
import { computed, ref, useId, watch } from 'vue';
import { useNow } from '@/composables/useNow';
import { percentOfUsual } from '@/lib/activity';
import { todayIso } from '@/lib/calendar';
import { latestDay, seniorCountedBackLine, seniorDayLabel } from '@/lib/reading-days';
/**
 * The senior's week as bars, drawn with plain HTML and CSS. Each bar is a button: hovering,
 * focusing or tapping one lightens it and shows a small tooltip, and choosing one fills in the box
 * below. Days are counted back from the latest reading ("3 days ago"), and a line under the chart
 * names that day when it is not today: see `lib/reading-days.ts`. Describes the numbers only.
 */
const props = defineProps<{ days: DailyMetric[]; usual: number }>();
const id = useId();
const selected = ref<string | null>(null);
watch(
  () => props.days,
  (days) => {
    selected.value = days.at(-1)?.day ?? null;
  },
  { immediate: true },
);
// The bar whose tooltip shows: the one under the pointer, else the one with focus or just tapped.
const hovered = ref<string | null>(null);
const focused = ref<string | null>(null);
const tipDay = computed(() => hovered.value ?? focused.value);
function dayWords(iso: string) {
  return seniorDayLabel(iso, latestDay(props.days) ?? '');
}
const now = useNow();
const countedBack = computed(() =>
  seniorCountedBackLine(latestDay(props.days), todayIso(now.value)),
);
// The axis under the first bar says what that bar says, so the two never disagree.
const oldestLabel = computed(() => (props.days.length > 1 ? dayWords(props.days[0].day) : ''));
function stepWords(steps: number) {
  return `${Math.round(steps).toLocaleString('en-SG')} steps`;
}
function usualWords(steps: number) {
  const percent = percentOfUsual(steps, props.usual);
  return percent === null ? '' : `${percent}% of your usual day`;
}
// The top of the chart: the busiest day or a fifth above usual, whichever is higher.
const top = computed(() => Math.max(props.usual * 1.2, ...props.days.map((day) => day.steps), 1));
const usualLine = computed(() => `${(props.usual / top.value) * 100}%`);
const bars = computed(() => {
  const count = props.days.length;
  return props.days.map((reading, index) => {
    const ofUsual = usualWords(reading.steps);
    const parts = [dayWords(reading.day), stepWords(reading.steps)];
    if (ofUsual) parts.push(ofUsual);
    const position = (index + 0.5) / count;
    return {
      day: reading.day,
      height: `${Math.max(2, (reading.steps / top.value) * 100)}%`,
      label: parts.join(', '),
      date: dayWords(reading.day),
      steps: stepWords(reading.steps),
      ofUsual,
      align: position < 0.3 ? 'start' : position > 0.7 ? 'end' : 'center',
      left:
        position < 0.3
          ? `${(index / count) * 100}%`
          : position > 0.7
            ? `${((index + 1) / count) * 100}%`
            : `${position * 100}%`,
    };
  });
});
const tip = computed(() => bars.value.find((bar) => bar.day === tipDay.value) ?? null);
const chosen = computed(() => props.days.find((day) => day.day === selected.value) ?? null);
const chosenText = computed(() => {
  if (!chosen.value) return '';
  const ofUsual = usualWords(chosen.value.steps);
  return `${stepWords(chosen.value.steps)}${ofUsual ? ` (${ofUsual})` : ''} and ${chosen.value.active_minutes} active minutes.`;
});
function choose(day: string) {
  selected.value = day;
  focused.value = day;
}
// Arrow keys move between bars, as in any row of options.
const buttons = ref<HTMLButtonElement[]>([]);
function onKey(event: KeyboardEvent, index: number) {
  const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
  if (!step) return;
  event.preventDefault();
  const next = Math.min(bars.value.length - 1, Math.max(0, index + step));
  selected.value = bars.value[next].day;
  buttons.value[next]?.focus();
}
</script>

<template>
  <div class="week-chart">
    <div
      class="chart"
      role="group"
      aria-label="Steps on each day. Choose a day for details."
      :aria-describedby="countedBack ? `${id}-hint ${id}-note` : `${id}-hint`"
    >
      <div class="plot" @mouseleave="hovered = null">
        <div class="usual-line" :style="{ bottom: usualLine }" aria-hidden="true">
          <span>Usual day</span>
        </div>

        <button
          v-for="(bar, index) in bars"
          :key="bar.day"
          ref="buttons"
          type="button"
          class="bar-btn"
          :class="{ chosen: bar.day === selected, active: bar.day === tipDay }"
          :aria-pressed="bar.day === selected"
          :aria-label="bar.label"
          :aria-controls="`${id}-detail`"
          @click="choose(bar.day)"
          @mouseenter="hovered = bar.day"
          @focus="focused = bar.day"
          @blur="focused = null"
          @keydown="onKey($event, index)"
        >
          <span class="bar" :style="{ height: bar.height }"></span>
        </button>

        <!-- The tooltip repeats the bar's own label, so it is hidden from screen readers. -->
        <div
          v-if="tip"
          class="chart-tip"
          :class="`tip-${tip.align}`"
          :style="{ left: tip.left }"
          aria-hidden="true"
        >
          <span class="d-block fw-bold">{{ tip.date }}</span>
          <span class="d-block">{{ tip.steps }}</span>
          <span v-if="tip.ofUsual" class="d-block">{{ tip.ofUsual }}</span>
        </div>
      </div>
      <div class="labels d-flex justify-content-between gap-2 mt-1" aria-hidden="true">
        <span>{{ oldestLabel }}</span>
        <span class="latest">Latest day</span>
      </div>
    </div>

    <p :id="`${id}-hint`" class="fs-5 text-body-secondary mt-3 mb-0" data-testid="week-hint">
      Tap a bar to see that day.
    </p>
    <p
      v-if="countedBack"
      :id="`${id}-note`"
      class="fs-5 text-body-secondary mt-1 mb-0"
      data-testid="week-counted-back"
    >
      {{ countedBack }}
    </p>

    <p v-if="chosen" :id="`${id}-detail`" class="chart-detail" aria-live="polite">
      <strong class="d-block">{{ dayWords(chosen.day) }}</strong>
      {{ chosenText }}
    </p>
  </div>
</template>

<style scoped>
.plot {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: 0.3rem;
  height: clamp(10rem, 22vw, 13rem);
  border-bottom: 2px solid var(--sl-line);
}

.labels {
  color: var(--sl-ink-soft);
  font-size: 1rem;
  font-weight: 600;
}

.labels .latest {
  color: var(--sl-ink);
  font-weight: 800;
}

.usual-line {
  position: absolute;
  z-index: 1;
  right: 0;
  left: 0;
  border-top: 2px dashed var(--sl-ink);
  pointer-events: none;
}

.usual-line span {
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

.bar {
  display: block;
  width: 100%;
  border-radius: 0.45rem 0.45rem 0 0;
  background: color-mix(in srgb, var(--sl-jade) 62%, var(--sl-surface));
  transition: background-color 0.15s ease;
}

/* The chosen day is the darkest bar; a hovered, focused or tapped one is lighter. It stays on the
   baseline, so its height still reads true against the Usual day line. */
.bar-btn.chosen .bar {
  background: var(--sl-jade-deep);
}

.bar-btn.active .bar {
  background: color-mix(in srgb, var(--sl-jade) 40%, var(--sl-surface));
}

.bar-btn.chosen.active .bar {
  background: var(--sl-jade);
}

.bar-btn:focus-visible {
  outline: 3px solid var(--sl-ink);
  outline-offset: 2px;
}

.chart-tip {
  position: absolute;
  z-index: 2;
  top: 0.25rem;
  /* Its own width, not what is left beside the bar (which is nothing at the right edge). */
  width: max-content;
  max-width: min(12rem, 100%);
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  color: var(--sl-ink);
  font-size: 0.85rem;
  line-height: 1.3;
  box-shadow: var(--sl-float);
  pointer-events: none;
  animation: tip-in 0.12s ease both;
}

.tip-start {
  transform: translateX(0);
}

.tip-center {
  transform: translateX(-50%);
}

.tip-end {
  transform: translateX(-100%);
}

.chart-detail {
  margin: 1rem 0 0;
  padding: 0.75rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-mist);
}

@keyframes tip-in {
  from {
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .bar,
  .chart-tip {
    transition: none;
    animation: none;
  }
}
</style>
