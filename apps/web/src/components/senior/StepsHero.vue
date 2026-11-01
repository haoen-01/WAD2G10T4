<script setup lang="ts">
import type { DailyMetric, PersonState } from '@silverloop/api-client';
import { computed, useId } from 'vue';
import SeniorWeekChart from '@/components/senior/SeniorWeekChart.vue';
import Icon from '@/components/ui/Icon.vue';
import { useNow } from '@/composables/useNow';
import { todayIso } from '@/lib/calendar';
import { isSampleSource, seniorReadingLine } from '@/lib/reading-days';
import { stepProgress, stepWords } from '@/lib/senior-view';
const props = withDefaults(defineProps<{ person: PersonState; week?: DailyMetric[] | null }>(), {
  week: null,
});
const id = useId();
const now = useNow();
const fromLine = computed(() => seniorReadingLine(props.person.current_day, todayIso(now.value)));
const steps = computed(() => Math.round(props.person.signal.current_steps).toLocaleString('en-SG'));
const progress = computed(() =>
  stepProgress(props.person.signal.current_steps, props.person.baseline.median_steps),
);
const status = computed(() =>
  stepWords(props.person.signal.current_steps, props.person.baseline.median_steps),
);
const statusIcon = computed(() =>
  progress.value.percent !== null && progress.value.percent >= 90 ? 'thumbs-up' : 'activity',
);
const percentLabel = computed(() =>
  progress.value.percent === null
    ? 'Usual day not available yet'
    : `${progress.value.percent}% of your usual day`,
);
const activeMinutes = computed(
  () => props.week?.find((day) => day.day === props.person.current_day)?.active_minutes ?? null,
);
</script>

<template>
  <section class="sl-panel steps-hero rounded-4 shadow-sm p-4" :aria-labelledby="`${id}-heading`">
    <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
      <h2 :id="`${id}-heading`" class="fs-3 d-flex align-items-center gap-2 mb-0">
        <Icon name="activity" />My steps
      </h2>
      <span
        v-if="isSampleSource(person.signal.quality.source)"
        class="badge text-bg-secondary fs-6"
        data-testid="steps-sample"
        >Sample numbers</span
      >
    </div>
    <div class="row align-items-center g-4">
      <div class="col-md-5 col-lg-4 text-center">
        <div class="step-ring mx-auto" role="img" :aria-label="`${steps} steps. ${percentLabel}`">
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <circle class="ring-track" cx="60" cy="60" r="50" />
            <circle
              class="ring-fill"
              cx="60"
              cy="60"
              r="50"
              pathLength="100"
              stroke-dasharray="100"
              :stroke-dashoffset="100 - progress.fill"
            />
          </svg>
          <span class="ring-number fw-bold" data-testid="steps-today" aria-hidden="true"
            >{{ steps }}<span class="d-block fs-4 fw-normal">steps</span></span
          >
        </div>
      </div>
      <div class="col-md-7 col-lg-8">
        <p class="fs-3 fw-semibold mb-2" data-testid="activity-status">
          {{ status }} <Icon :name="statusIcon" />
        </p>
        <p class="fs-5 text-body-secondary">{{ percentLabel }}</p>
        <p class="d-inline-flex align-items-center gap-2 rounded-pill minutes-chip px-3 py-2 fs-5">
          <Icon name="clock" />{{
            activeMinutes === null
              ? 'Active minutes unavailable'
              : `${activeMinutes} active minutes`
          }}
        </p>
        <p v-if="person.current_day" class="text-body-secondary fs-5 mb-0" data-testid="steps-from">
          {{ fromLine }}
        </p>
        <p
          v-if="isSampleSource(person.signal.quality.source)"
          class="text-body-secondary fs-5 mb-0 mt-2"
          data-testid="steps-sample-note"
        >
          These are sample numbers, not your own steps.
        </p>
      </div>
    </div>
    <div class="mt-4">
      <h3 class="fs-4 mb-3">Your week</h3>
      <SeniorWeekChart v-if="week?.length" :days="week" :usual="person.baseline.median_steps" />
      <p v-else class="fs-5 text-body-secondary mb-0">Weekly readings aren't available yet.</p>
    </div>
  </section>
</template>

<style scoped>
.steps-hero {
  border-top: 0.35rem solid var(--sl-jade-deep);
}
.step-ring {
  position: relative;
  width: min(100%, 17rem);
  aspect-ratio: 1;
}
.step-ring svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.step-ring circle {
  fill: none;
  stroke-width: 9;
}
.ring-track {
  stroke: var(--sl-jade-soft);
}
.ring-fill {
  stroke: var(--sl-jade-deep);
  stroke-linecap: round;
}
.ring-number {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: clamp(2rem, 5vw, 3rem);
}
.minutes-chip {
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}
@media (prefers-reduced-motion: no-preference) {
  .ring-fill {
    animation: fill-ring 0.7s ease-out;
    transition: stroke-dashoffset 0.7s ease-out;
  }
}
@keyframes fill-ring {
  from {
    stroke-dashoffset: 100;
  }
}
</style>
