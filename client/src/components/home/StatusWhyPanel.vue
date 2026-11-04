<script setup lang="ts">
import type { PersonState } from '@silverloop/api-client';
import { computed } from 'vue';

import Icon from '@/components/ui/Icon.vue';

/**
 * "Why?": a disclosure under the hero's sentence. Opened, it says what Care+ did, then the API's
 * own first reason, plus
 * the context it weighed (rain, air quality, a public holiday) as a few words. The reason is the
 * policy's wording, kept verbatim, so it sits behind the plain sentence rather than leading it.
 */
const props = defineProps<{
  person: PersonState;
  /** What Care+ did, in plain words ("Care+ isn't suggesting anything right now"). */
  action?: string;
}>();

const line = computed(() => {
  const context = props.person.signal.context;
  const parts = [props.person.rationale[0] ?? props.person.signal.quality.reasons[0] ?? ''];
  // Says where the weather came from: a live NEA reading for today, or the simulation.
  if (context.rainy) {
    parts.push(
      context.weather_source === 'live' ? 'raining now (live weather)' : 'rainy day (simulated)',
    );
  } else if (context.weather_source === 'unavailable') {
    parts.push('live weather unavailable');
  }
  if (context.air_quality && context.air_quality !== 'normal') {
    parts.push(`air quality ${context.air_quality}`);
  }
  if (context.holiday) parts.push('public holiday');
  return parts.filter(Boolean).join(' · ');
});
</script>

<template>
  <details v-if="line || action" class="why" data-testid="status-why">
    <summary class="why-toggle">Why?<Icon name="chevron-right" class="why-chevron" /></summary>
    <p v-if="action" class="why-action mb-1" data-testid="hero-action">{{ action }}.</p>
    <p v-if="line" class="why-line mb-0">
      <Icon name="info" class="me-2 flex-shrink-0" /><span
        ><span class="visually-hidden">Why: </span>{{ line }}</span
      >
    </p>
  </details>
</template>

<style scoped>
.why-toggle {
  display: inline-flex;
  align-items: center;
  min-height: 2.75rem;
  padding-inline: 0.25rem;
  color: var(--bs-link-color);
  font-weight: 700;
  cursor: pointer;
  list-style: none;
}

.why-toggle::-webkit-details-marker {
  display: none;
}

.why-chevron {
  margin-left: 0.15rem;
  transition: transform var(--sl-dur-base) var(--sl-ease);
}

.why[open] .why-chevron {
  transform: rotate(90deg);
}

@media (hover: hover) and (pointer: fine) {
  .why-toggle:hover {
    text-decoration: underline;
  }
}

.why-action {
  max-width: 40rem;
  font-weight: 700;
}

.why-line {
  display: flex;
  align-items: flex-start;
  max-width: 40rem;
  color: var(--sl-ink-soft);
}

.why-line .sl-icon {
  margin-top: 0.2rem;
}
</style>
