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
import { useNow } from '@/composables/useNow';
import { todayIso } from '@/lib/calendar';
import {
  countedBackNote,
  latestDay,
  oldestReadingLabel,
  readingDayLabel,
} from '@/lib/reading-days';

/**
 * The last fortnight of steps as bars, drawn with plain HTML and CSS. Days are counted back from the
 * latest reading ("3 days ago"), never dated: see `lib/reading-days.ts`. Each bar is a button, so a
 * keyboard, a mouse and a finger can all pick a day. A day's figures pop out above its bar while the
 * mouse is over it or the bar has keyboard focus; a click or tap keeps them showing (another click,
 * or Escape, hides them). Each bar's name says the same in words for screen readers. Two lines give the bars meaning: her usual day, and 20% below it (the first point at which
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

const latest = computed(() => latestDay(props.days) ?? '');
const oldestLabel = computed(() => oldestReadingLabel(props.days));
const dayLabel = (iso: string) => readingDayLabel(iso, latest.value);
const now = useNow();
const countedBack = computed(() => countedBackNote(latestDay(props.days), todayIso(now.value)));
const describe = (day: StepDay) => {
  const percent = percentOfUsual(day.steps, props.usual);
  const parts = [`${dayLabel(day.day)}: ${formatSteps(day.steps)}`];
  if (percent !== null) parts.push(`${percent}% of ${props.owner} usual day`);
  if (!isNearUsual(day.steps, props.usual))
    parts.push(`more than ${GENTLE_NUDGE_PERCENT}% below usual`);
  return parts.join(', ');
};

/** The bar under the mouse, the bar with keyboard focus, and whether a click pinned the chosen one. */
const hovered = ref<string | null>(null);
const focused = ref<string | null>(null);
const pinned = ref(false);

/** The day whose figures pop out, if any: hovering wins, then focus, then a pinned click. */
const shownDay = computed(
  () => hovered.value ?? focused.value ?? (pinned.value ? selected.value : null),
);
const shownIndex = computed(() => props.days.findIndex((day) => day.day === shownDay.value));
const shown = computed(() => props.days[shownIndex.value] ?? null);

function choose(day: string) {
  pinned.value = !(pinned.value && selected.value === day);
  selected.value = day;
}

function hide() {
  pinned.value = false;
  hovered.value = null;
  focused.value = null;
}

/** The pop-out sits over its bar, kept inside the chart at both ends. */
const tipStyle = computed(() => {
  const count = props.days.length;
  const index = shownIndex.value;
  const day = shown.value;
  if (!day || index < 0) return {};
  const centre = ((index + 0.5) / count) * 100;
  const shift = index < 2 ? '-12%' : index > count - 3 ? '-88%' : '-50%';
  return {
    left: `${centre}%`,
    bottom: `calc(${heightOf(day.steps)} + 0.6rem)`,
    '--shift': shift,
    '--arrow': index < 2 ? '12%' : index > count - 3 ? '88%' : '50%',
  };
});

// Arrow keys move between bars, as in any row of options.
const bars = ref<HTMLButtonElement[]>([]);
function onKey(event: KeyboardEvent, index: number) {
  const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
  if (!step) return;
  event.preventDefault();
  const next = Math.min(props.days.length - 1, Math.max(0, index + step));
  selected.value = props.days[next].day;
  bars.value[next]?.focus();
  focused.value = props.days[next].day;
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
      <div class="plot" @mouseleave="hovered = null" @keydown.esc="hide">
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
          :class="{ low: !isNearUsual(day.steps, usual), active: day.day === shownDay }"
          :aria-pressed="day.day === selected"
          :aria-label="describe(day)"
          :tabindex="day.day === selected ? 0 : -1"
          :style="{ '--delay': `${index * 35}ms` }"
          @click="choose(day.day)"
          @mouseenter="hovered = day.day"
          @focus="focused = day.day"
          @blur="focused = null"
          @keydown="onKey($event, index)"
        >
          <span class="bar" :style="{ height: heightOf(day.steps) }"></span>
        </button>

        <!-- The figures for one day, popping out above its bar. The bar's own name says the same,
             so screen readers do not hear it twice. -->
        <Transition name="tip">
          <div
            v-if="shown"
            class="chart-readout chart-tip"
            :class="{ low: !isNearUsual(shown.steps, usual) }"
            :style="tipStyle"
            aria-hidden="true"
            data-testid="chart-tip"
          >
            <strong class="chart-tip-day">{{ dayLabel(shown.day) }}</strong>
            <span class="chart-tip-steps">{{ formatSteps(shown.steps) }}</span>
            <span v-if="percentOfUsual(shown.steps, usual) !== null" class="chart-tip-line">
              {{ percentOfUsual(shown.steps, usual) }}% of {{ owner }} usual day
            </span>
            <span v-if="shown.active_minutes !== undefined" class="chart-tip-line">
              {{ shown.active_minutes }} active minutes
            </span>
            <span v-if="!isNearUsual(shown.steps, usual)" class="chart-tip-warn">
              More than {{ GENTLE_NUDGE_PERCENT }}% below {{ owner }} usual day
            </span>
          </div>
        </Transition>
      </div>
      <div class="labels d-flex justify-content-between gap-2 mt-1" aria-hidden="true">
        <span>{{ oldestLabel }}</span>
        <span class="latest">Latest</span>
      </div>
    </div>

    <p class="sl-note mt-2 mb-0">
      Point at a bar, or tap it, to see that day.
      <span v-if="countedBack" data-testid="counted-back">{{ countedBack }}</span>
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
  color: var(--sl-ink-soft);
  font-size: 0.8rem;
  font-weight: 600;
}

.labels .latest {
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

.bar-btn.active {
  background: color-mix(in srgb, var(--sl-jade) 8%, transparent);
}

.bar-btn.active .bar {
  background: var(--sl-jade-deep);
  transform: scaleX(1.06);
}

/* The other bars step back a little while one is looked at. */
.plot:hover .bar-btn:not(.active) .bar {
  opacity: 0.6;
}

.bar {
  display: block;
  width: 100%;
  border-radius: 0.45rem 0.45rem 0 0;
  background: color-mix(in srgb, var(--sl-jade) 62%, var(--sl-surface));
  transform-origin: bottom;
  animation: grow 0.6s var(--sl-ease) both;
  animation-delay: var(--delay);
  transition:
    background-color 0.15s ease,
    opacity 0.2s ease,
    transform 0.2s var(--sl-ease);
}

.bar-btn.low .bar {
  background: color-mix(in srgb, var(--sl-coral) 70%, var(--sl-surface));
}

.bar-btn.low.active .bar {
  background: var(--sl-coral-deep);
}

/* ---- The pop-out: a small card above the bar, with an arrow pointing down at it ---- */
.chart-tip {
  position: absolute;
  z-index: 3;
  display: grid;
  gap: 0.1rem;
  width: max-content;
  max-width: 15rem;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  color: var(--sl-ink);
  box-shadow: var(--sl-float);
  font-size: 0.875rem;
  line-height: 1.35;
  pointer-events: none;
  transform: translateX(var(--shift));
  /* Moving from bar to bar, the same card glides along. */
  transition:
    left 0.15s var(--sl-ease),
    bottom 0.15s var(--sl-ease);
}

.chart-tip::after {
  position: absolute;
  top: 100%;
  left: var(--arrow);
  width: 0.7rem;
  height: 0.7rem;
  border-right: 1px solid var(--sl-line);
  border-bottom: 1px solid var(--sl-line);
  background: var(--sl-surface);
  content: '';
  transform: translate(-50%, -50%) rotate(45deg);
}

.chart-tip-day {
  font-size: 0.8rem;
  color: var(--sl-ink-soft);
}

.chart-tip-steps {
  font-size: 1.15rem;
  font-weight: 800;
}

.chart-tip-warn {
  margin-top: 0.2rem;
  color: var(--sl-coral-deep);
  font-weight: 700;
}

.chart-tip.low {
  border-color: color-mix(in srgb, var(--sl-coral) 45%, var(--sl-line));
}

.tip-enter-active,
.tip-leave-active {
  transition:
    opacity 0.15s ease,
    transform 0.15s var(--sl-ease);
}

.tip-enter-from,
.tip-leave-to {
  opacity: 0;
  transform: translateX(var(--shift)) translateY(0.35rem) scale(0.96);
}

@media (prefers-reduced-motion: reduce) {
  .tip-enter-active,
  .tip-leave-active,
  .bar {
    transition: none;
  }

  .bar-btn.active .bar {
    transform: none;
  }
}

@keyframes grow {
  from {
    transform: scaleY(0);
  }
}
</style>
