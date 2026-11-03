<script setup lang="ts">
import type { DailyMetric, PersonState } from '@silverloop/api-client';
import { computed, ref, useId } from 'vue';
import SeniorWeekChart from '@/components/senior/SeniorWeekChart.vue';
import Icon from '@/components/ui/Icon.vue';
import { useNow } from '@/composables/useNow';
import { todayIso } from '@/lib/calendar';
import { isSampleSource, seniorReadingLine } from '@/lib/reading-days';
import { seniorActivity } from '@/lib/senior-view';

/**
 * "My steps" on the senior's Today tab: one plain sentence with a friendly icon ("You walked about
 * as much as usual."), the step count and its day underneath, and the week's chart behind "See my
 * week". Compared only with their own usual day; nothing here judges their health. CSS only.
 */
const props = withDefaults(defineProps<{ person: PersonState; week?: DailyMetric[] | null }>(), {
  week: null,
});
const id = useId();
const now = useNow();
const fromLine = computed(() => seniorReadingLine(props.person.current_day, todayIso(now.value)));
const steps = computed(() => Math.round(props.person.signal.current_steps).toLocaleString('en-SG'));
const activity = computed(() =>
  seniorActivity(
    props.person.signal.current_steps,
    props.person.baseline.median_steps,
    props.person.signal.quality.safe_to_interpret,
  ),
);
const sample = computed(() => isSampleSource(props.person.signal.quality.source));
const weekOpen = ref(false);
</script>

<template>
  <section class="sl-panel steps-hero" :aria-labelledby="`${id}-heading`">
    <h2 :id="`${id}-heading`" class="fs-3 d-flex align-items-center gap-2 mb-3">
      <Icon name="activity" />My steps
    </h2>

    <div class="steps-main">
      <span class="steps-icon" aria-hidden="true"><Icon :name="activity.icon" /></span>
      <div class="min-w-0">
        <p class="steps-sentence" data-testid="activity-status">{{ activity.sentence }}</p>
        <p class="fs-5 mb-1">
          <span class="fw-bold tabular" data-testid="steps-today">{{ steps }} steps</span>
        </p>
        <p v-if="person.current_day" class="text-body-secondary fs-5 mb-0" data-testid="steps-from">
          {{ fromLine }}
        </p>
        <p v-if="sample" class="steps-sample fs-5 mb-0 mt-2" data-testid="steps-sample">
          <Icon name="info" class="me-1" />Sample numbers. These are not your own steps.
        </p>
      </div>
    </div>

    <button
      type="button"
      class="btn btn-outline-primary btn-lg week-toggle mt-4"
      :aria-expanded="weekOpen"
      :aria-controls="`${id}-week`"
      data-testid="see-my-week"
      @click="weekOpen = !weekOpen"
    >
      <Icon name="chevron-right" class="week-chevron me-2" :class="{ open: weekOpen }" />{{
        weekOpen ? 'Hide my week' : 'See my week'
      }}
    </button>
    <div v-if="weekOpen" :id="`${id}-week`" class="mt-4">
      <h3 class="fs-4 mb-3">Your week</h3>
      <SeniorWeekChart v-if="week?.length" :days="week" :usual="person.baseline.median_steps" />
      <p v-else class="fs-5 text-body-secondary mb-0">Weekly readings aren't available yet.</p>
    </div>
  </section>
</template>

<style scoped>
.steps-hero {
  padding: 1.5rem;
}
.min-w-0 {
  min-width: 0;
}
.steps-main {
  display: flex;
  align-items: flex-start;
  gap: 1.25rem;
}
/* A friendly picture beside the sentence: a pale jade circle with a big icon. */
.steps-icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 4.5rem;
  height: 4.5rem;
  border-radius: 50%;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}
.steps-icon .sl-icon {
  width: 2.25rem;
  height: 2.25rem;
}
.steps-sentence {
  margin-bottom: 0.5rem;
  font-size: clamp(1.6rem, 4vw, 2.1rem);
  font-weight: 800;
  line-height: 1.25;
}
.steps-sample {
  color: var(--sl-ink-soft);
}
.week-toggle {
  display: inline-flex;
  align-items: center;
  min-height: 56px;
}
.week-chevron {
  transition: transform var(--sl-dur-base) var(--sl-ease);
}
.week-chevron.open {
  transform: rotate(90deg);
}
@media (max-width: 575.98px) {
  .steps-icon {
    width: 3.5rem;
    height: 3.5rem;
  }
  .week-toggle {
    width: 100%;
    justify-content: center;
  }
}
</style>
