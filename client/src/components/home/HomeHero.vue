<script lang="ts">
import type { PersonState, WearableStatus } from '@silverloop/api-client';
import { defineComponent, type PropType } from 'vue';

import NumberTicker from '@/components/motion/NumberTicker.vue';
import StatusWhyPanel from '@/components/home/StatusWhyPanel.vue';
import WatchStatus from '@/components/home/WatchStatus.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import LoopRing from '@/components/ui/LoopRing.vue';
import WalkLink from '@/components/walk/WalkLink.vue';
import { GENTLE_NUDGE_PERCENT, compareWords, formatSteps, percentOfUsual } from '@/lib/activity';
import { todayIso } from '@/lib/calendar';
import { attentionBadge, decisionBadge } from '@/lib/labels';
import { homeReadingWords, isSampleSource } from '@/lib/reading-days';

/**
 * The top of Home: the greeting, how far she walked on the latest reading's day against her usual
 * day (as a sentence and as a ring), her watch (connected, battery), the status badges and, in one line,
 * why Care+ says so (`StatusWhyPanel`).
 */
export default defineComponent({
  name: 'HomeHero',
  components: { LoopRing, NumberTicker, StatusBadge, StatusWhyPanel, WalkLink, WatchStatus },

  props: {
    person: { type: Object as PropType<PersonState | null>, default: null },
    loading: { type: Boolean, required: true },
    /** The senior's watch, or `null` while it is being read (or if reading it failed). */
    wearable: { type: Object as PropType<WearableStatus | null>, default: null },
    wearableFailed: { type: Boolean, default: false },
    now: { type: Date, required: true },
    greeting: { type: String, required: true },
    /** The family member using the app, if one is chosen. */
    viewer: { type: String as PropType<string | null>, default: null },
    elder: { type: String, required: true },
  },

  data() {
    // A smaller loop on a phone, so the facts can sit beside it.
    return { narrow: window.matchMedia('(max-width: 575.98px)').matches };
  },

  computed: {
    /** "Today" only when the latest reading is from today; otherwise that reading's own day. */
    reading() {
      return homeReadingWords(this.person?.current_day ?? '', todayIso(this.now), this.elder);
    },
    /** The latest reading's steps as a percentage of the usual day. */
    percent(): number | null {
      if (!this.person) return null;
      return percentOfUsual(this.person.signal.current_steps, this.person.baseline.median_steps);
    },
    /** Coral below the gentle-nudge line, as on the chart; jade otherwise. */
    low(): boolean {
      return this.percent !== null && this.percent < 100 - GENTLE_NUDGE_PERCENT;
    },
  },

  methods: {
    attentionBadge,
    decisionBadge,
    compareWords,
    formatSteps,
    isSampleSource,
    signed(n: number): string {
      return `${n > 0 ? '+' : ''}${Math.round(n)}%`;
    },
  },
});
</script>

<template>
  <!-- Bootstrap grid: the sentence and the loop side by side from the large breakpoint up,
       stacked (sentence first) below it. -->
  <header class="hero row align-items-center gy-4 gx-lg-5">
    <div class="col-12 col-lg">
      <p class="hero-greeting">
        {{ greeting }}<template v-if="viewer">, {{ viewer }}</template
        >.
      </p>
      <h1 class="hero-title"><span class="visually-hidden">Care+: </span>{{ elder }}’s day</h1>

      <p v-if="person" class="hero-lede">
        {{ reading.ledeStart }} <strong>{{ formatSteps(person.signal.current_steps) }}</strong>
        {{ reading.ledeWhen }}, {{ compareWords(percent) }}.
      </p>
      <p v-else-if="!loading" class="hero-lede">
        {{ elder }}’s activity is not available right now.
      </p>

      <WatchStatus
        class="mt-3"
        role="status"
        :status="wearable"
        :failed="wearableFailed"
        :elder="elder"
        :now="now"
      />
      <WalkLink class="mt-2" />

      <div v-if="person" class="d-flex flex-wrap align-items-center gap-2 mt-2">
        <StatusBadge v-bind="attentionBadge(person.attention_band)" />
        <StatusBadge v-bind="decisionBadge(person.last_decision)" />
        <StatusBadge v-if="!person.consent_active" label="Consent withdrawn" tone="secondary" />
      </div>

      <StatusWhyPanel v-if="person" class="mt-2" :person="person" />
    </div>

    <div v-if="person" class="col-12 col-lg-auto">
      <section class="hero-card sl-panel" aria-labelledby="today-heading">
        <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
          <h2 id="today-heading" class="h5 mb-0">{{ reading.heading }}</h2>
          <span
            v-if="isSampleSource(person.signal.quality.source)"
            class="badge text-bg-secondary"
            data-testid="today-sample"
            >Sample</span
          >
        </div>
        <div class="d-flex flex-nowrap align-items-center gap-3 gap-sm-4">
          <LoopRing
            :value="(percent ?? 0) / 100"
            :size="narrow ? 148 : 196"
            :stroke="narrow ? 14 : 18"
            :color="low ? 'var(--sl-coral)' : 'var(--sl-jade)'"
            :track="low ? 'var(--sl-coral-soft)' : 'var(--sl-jade-soft)'"
          >
            <span class="display-num ring-num"
              ><NumberTicker v-if="percent !== null" :value="percent" /><template v-else>–</template
              ><small>%</small></span
            >
            <span class="ring-caption">of a usual day</span>
          </LoopRing>
          <dl class="ring-facts">
            <div>
              <dt data-testid="hero-steps-label">{{ reading.stepsLabel }}</dt>
              <dd class="tabular">
                {{ formatSteps(person.signal.current_steps) }}
                ({{ signed(person.signal.delta_percent) }} from usual)
              </dd>
            </div>
            <div>
              <dt>Usual day</dt>
              <dd class="tabular">{{ formatSteps(person.baseline.median_steps) }}</dd>
            </div>
          </dl>
        </div>
      </section>
    </div>
  </header>
</template>

<style scoped>
.hero {
  margin-bottom: 2rem;
}

.hero-greeting {
  margin-bottom: 0.25rem;
  color: var(--sl-ink-soft);
  font-size: 1.15rem;
  font-weight: 600;
}

.hero-title {
  margin-bottom: 0.75rem;
  font-size: clamp(2.2rem, 6vw, 3.6rem);
  font-weight: 800;
  letter-spacing: -0.035em;
}

.hero-lede {
  max-width: 34rem;
  margin-bottom: 0;
  font-size: 1.3rem;
  line-height: 1.45;
}

.hero-card {
  box-shadow: var(--sl-float);
  animation: hero-rise var(--sl-dur-slow) var(--sl-ease) both;
}

@keyframes hero-rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
}

.ring-num {
  font-size: 3.2rem;
}

@media (max-width: 575.98px) {
  .ring-num {
    font-size: 2.4rem;
  }
}

.ring-num small {
  font-size: 0.45em;
  font-weight: 700;
}

.ring-caption {
  margin-top: 0.25rem;
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
}

.ring-facts {
  display: grid;
  gap: 0.6rem;
  margin: 0;
}

.ring-facts dt {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
}

.ring-facts dd {
  margin: 0;
  font-weight: 600;
}
</style>
