<script lang="ts">
import { defineComponent, type PropType } from 'vue';

import LoopRing from '@/components/ui/LoopRing.vue';
import type { Coverage } from '@/lib/coverage';

/**
 * The month ahead at a glance: a ring that closes as visits get someone going (jade once every
 * visit is covered, coral until then), and a sentence that counts what is still open.
 */
export default defineComponent({
  name: 'CoverageSummary',
  components: { LoopRing },

  props: {
    coverage: { type: Object as PropType<Coverage>, required: true },
  },

  computed: {
    complete(): boolean {
      return this.coverage.ratio === 1;
    },
  },
});
</script>

<template>
  <div class="cover">
    <LoopRing
      :value="coverage.ratio"
      :size="44"
      :stroke="6"
      :color="complete ? 'var(--sl-jade)' : 'var(--sl-coral)'"
      :track="complete ? 'var(--sl-jade-soft)' : 'var(--sl-coral-soft)'"
    >
      <span class="visually-hidden">{{ coverage.covered }} of {{ coverage.total }}</span>
    </LoopRing>
    <p class="mb-0 lh-sm">
      <strong v-if="coverage.total === 0">No visits in the next 30 days</strong>
      <strong v-else-if="complete">Every visit has someone going</strong>
      <strong v-else class="tabular" data-testid="coverage-open"
        >{{ coverage.total - coverage.covered }}
        {{ coverage.total - coverage.covered === 1 ? 'visit still needs' : 'visits still need' }}
        someone</strong
      >
      <span class="d-block small text-body-secondary">next 30 days</span>
    </p>
  </div>
</template>

<style scoped>
.cover {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  max-width: 24rem;
}
</style>
