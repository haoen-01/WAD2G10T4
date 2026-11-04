<script lang="ts">
import type { DailyMetric } from '@silverloop/api-client';
import { defineComponent, type PropType } from 'vue';

import ActivityChart from '@/components/home/ActivityChart.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import { isSampleSource } from '@/lib/reading-days';

/**
 * "The last two weeks": the step chart, or what to show while it loads, when it failed (with a
 * Try again that asks Home to fetch it again) and when there is nothing yet.
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
    /** The senior's usual day's steps, for the chart's line. */
    usual: { type: Number, required: true },
    /** The senior's name, for "Mr Tan’s usual day"; empty when it is not known. */
    elder: { type: String, default: '' },
  },

  emits: ['retry'],

  computed: {
    /** Whose usual day and recent days: "Mr Tan’s", or "their" with no name (never a guessed "her"). */
    owner(): string {
      return this.elder ? `${this.elder}’s` : 'their';
    },
    /** Sample readings say so: their days are simulated, not real dates. */
    sample(): boolean {
      return (this.history ?? []).some((day) => isSampleSource(day.source));
    },
  },
});
</script>

<template>
  <BasePanel title="The last two weeks">
    <template v-if="sample" #actions>
      <span class="badge text-bg-secondary" data-testid="fortnight-sample">Sample</span>
    </template>
    <ActivityChart v-if="history && history.length" :days="history" :usual="usual" :owner="owner" />
    <p v-else-if="failed" class="text-body-secondary mb-0">
      <template v-if="elder">{{ elder }}’s recent days</template
      ><template v-else>Recent days</template> could not be loaded.
      <button type="button" class="btn btn-link p-0 align-baseline" @click="$emit('retry')">
        Try again
      </button>
    </p>
    <p v-else-if="history" class="text-body-secondary mb-0">No daily readings yet.</p>
    <div v-else-if="hasPerson" class="placeholder-glow" role="status">
      <span class="visually-hidden"
        >Loading <template v-if="elder">{{ elder }}’s</template> recent days…</span
      >
      <span class="placeholder col-12" style="height: 11rem" aria-hidden="true"></span>
    </div>
    <p v-else class="text-body-secondary mb-0">
      No daily readings yet.
      <template v-if="elder">{{ elder }}’s steps</template><template v-else>Steps</template> show
      here once the watch has sent a few days.
    </p>
  </BasePanel>
</template>
