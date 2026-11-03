<script lang="ts">
import type { DailyMetric } from '@silverloop/api-client';
import { defineComponent, type PropType } from 'vue';

import ActivityChart from '@/components/home/ActivityChart.vue';
import BasePanel from '@/components/ui/BasePanel.vue';

/**
 * "The last two weeks": the step chart, or what to show while it loads, when it failed (with a
 * Try again that asks Home to fetch it again) and when there is nothing yet. Sample readings are
 * labelled once for the whole screen, by the notice in Home's hero.
 */
export default defineComponent({
  name: 'FortnightPanel',
  components: { ActivityChart, BasePanel },

  props: {
    /** The daily readings; null until they have loaded. */
    history: { type: Array as PropType<DailyMetric[] | null>, default: null },
    failed: { type: Boolean, default: false },
    /** Whether the person's status loaded (the chart is only fetched after it). */
    hasPerson: { type: Boolean, default: false },
    /** Her usual day's steps, for the chart's line. */
    usual: { type: Number, required: true },
  },

  emits: ['retry'],
});
</script>

<template>
  <BasePanel title="The last two weeks" heading-tag="h3">
    <ActivityChart v-if="history && history.length" :days="history" :usual="usual" />
    <p v-else-if="failed" class="text-body-secondary mb-0">
      Her recent days could not be loaded.
      <button type="button" class="btn btn-link p-0 align-baseline" @click="$emit('retry')">
        Try again
      </button>
    </p>
    <p v-else-if="history" class="text-body-secondary mb-0">No daily readings yet.</p>
    <div v-else-if="hasPerson" role="status">
      <span class="visually-hidden">Loading her recent days…</span>
      <span class="sl-skeleton" style="height: 11rem" aria-hidden="true"></span>
    </div>
    <p v-else class="text-body-secondary mb-0">
      No daily readings yet. Her steps show here once her watch has sent a few days.
    </p>
  </BasePanel>
</template>
