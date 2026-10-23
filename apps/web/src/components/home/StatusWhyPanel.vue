<script setup lang="ts">
import type { PersonState } from '@silverloop/api-client';
import { computed } from 'vue';

import Icon from '@/components/ui/Icon.vue';

/**
 * Why Care+ says today's status, in one line: the API's own first reason, plus the context it
 * weighed (rain, air quality, a public holiday) as a few words. The full list lives in the API's
 * record; Home only needs the gist.
 */
const props = defineProps<{ person: PersonState }>();

const line = computed(() => {
  const context = props.person.signal.context;
  const parts = [props.person.rationale[0] ?? props.person.signal.quality.reasons[0] ?? ''];
  if (context.rainy) parts.push('rainy day');
  if (context.air_quality && context.air_quality !== 'normal') {
    parts.push(`air quality ${context.air_quality}`);
  }
  if (context.holiday) parts.push('public holiday');
  return parts.filter(Boolean).join(' · ');
});
</script>

<template>
  <p v-if="line" class="why-line mb-0">
    <Icon name="info" class="me-1 flex-shrink-0" /><span
      ><span class="visually-hidden">Why: </span>{{ line }}</span
    >
  </p>
</template>

<style scoped>
.why-line {
  display: flex;
  align-items: center;
  color: var(--sl-ink-soft);
  font-weight: 600;
}
</style>
