<script setup lang="ts">
import type { PersonState } from '@silverloop/api-client';
import { computed } from 'vue';

import Icon, { type IconName } from '@/components/ui/Icon.vue';
import { compareWords, percentOfUsual } from '@/lib/activity';
import { formatIsoDay } from '@/lib/format-date';

/**
 * The one status line at the top of the senior's screen: how today compares with a usual day, in
 * plain words with an icon. Describes the numbers only; it never reads them as a health sign.
 */
const props = defineProps<{
  person: PersonState;
  /** This device's today, `YYYY-MM-DD`, to tell whether the latest readings are today's. */
  today: string;
}>();

interface Status {
  words: string;
  /** A friendly emoji after the words; decoration only. */
  emoji?: string;
  /** An Icon.vue icon for the badge, or an emoji where Icon.vue has nothing that fits. */
  icon: IconName | { emoji: string };
}

// `compareWords` (shared with the family's Home) decides which status applies; this only puts it
// in the senior's own words.
const SENIOR_STATUS: Record<string, Status> = {
  'more than a usual day': { words: 'Keep it up!', emoji: '💪', icon: 'sparkle' },
  'about the same as a usual day': { words: 'All looks good!', emoji: '👍', icon: 'check-circle' },
  'a little less than a usual day': {
    words: 'A bit less active than usual',
    icon: { emoji: '🚶' },
  },
  'well below a usual day': { words: 'A bit less active than usual', icon: { emoji: '🚶' } },
  'not enough data to compare yet': { words: 'Not enough data to compare yet', icon: 'clock' },
};

const status = computed<Status>(() => {
  const words = compareWords(
    percentOfUsual(props.person.signal.current_steps, props.person.baseline.median_steps),
  );
  return SENIOR_STATUS[words] ?? { words, icon: 'info' };
});
// In the demo the readings are a fixed day of replayed data, not this device's today.
const when = computed(() =>
  props.person.current_day === props.today
    ? 'Today so far'
    : `Your latest day: ${formatIsoDay(props.person.current_day).replace(',', '')}`,
);
const iconName = computed(() => (typeof status.value.icon === 'string' ? status.value.icon : null));
const iconEmoji = computed(() =>
  typeof status.value.icon === 'string' ? null : status.value.icon.emoji,
);
</script>

<template>
  <section class="status d-flex align-items-center gap-3 p-3 p-md-4" aria-labelledby="status-words">
    <span class="status-badge" aria-hidden="true">
      <Icon v-if="iconName" :name="iconName" />
      <template v-else>{{ iconEmoji }}</template>
    </span>
    <div class="min-w-0">
      <p class="small fw-semibold mb-1">{{ when }}</p>
      <h2 id="status-words" class="fs-3 fw-semibold lh-sm mb-0" data-testid="activity-status">
        {{ status.words }}
        <span v-if="status.emoji" aria-hidden="true">{{ status.emoji }}</span>
      </h2>
    </div>
  </section>
</template>

<style scoped>
.status {
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
}

/* A filled badge with an icon: nothing spins and nothing is left empty, so it never reads as
   loading. */
.status-badge {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 3.5rem;
  height: 3.5rem;
  border-radius: 50%;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-size: 1.6rem;
}

.status-badge .sl-icon {
  width: 2rem;
  height: 2rem;
}

.min-w-0 {
  min-width: 0;
}
</style>
