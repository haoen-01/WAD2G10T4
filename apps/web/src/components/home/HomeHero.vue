<script lang="ts">
/** Set once her day has been shown, so the hero's entrance plays once per visit to the app. */
let heroHasEntered = false;
</script>

<script setup lang="ts">
import type { PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, onMounted, watch } from 'vue';
import { RouterLink } from 'vue-router';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import NumberTicker from '@/components/motion/NumberTicker.vue';
import StatusWhyPanel from '@/components/home/StatusWhyPanel.vue';
import WatchStatus from '@/components/home/WatchStatus.vue';
import Icon from '@/components/ui/Icon.vue';
import LoopRing from '@/components/ui/LoopRing.vue';
import WalkLink from '@/components/walk/WalkLink.vue';
import { formatSteps, percentOfUsual } from '@/lib/activity';
import { todayIso } from '@/lib/calendar';
import { longToday, readingPastDay, readingStamp } from '@/lib/home';
import { daySummary } from '@/lib/labels';

/**
 * The top of family Home, answering "Is she okay today, and is there anything I need to do?" in
 * the family's words: her avatar, today's date, a greeting, one plain sentence built from the
 * policy's own result (`daySummary` in `lib/labels.ts`), how her steps compare with her usual day
 * (and from which day they are), and "Why?" (what Care+ did and the policy's reason) behind a
 * disclosure, so nothing in the hero competes with "Needs you". Her watch is a row of chips. The
 * one "Sample data" notice for the screen sits at the bottom of the hero.
 */
const props = defineProps<{
  person: PersonState | null;
  loading: boolean;
  /** The senior's watch, or `null` while it is being read (or if reading it failed). */
  wearable: WearableStatus | null;
  wearableFailed: boolean;
  now: Date;
  greeting: string;
  /** The family member using the app, if one is chosen. */
  viewer: string | null;
  elder: string;
  /** True when the family group has no senior linked yet. */
  noSenior?: boolean;
  /** The screen's one sample-data sentence, or `null` when nothing shown is sample. */
  sampleNote?: string | null;
}>();

const today = computed(() => todayIso(props.now));
/** The reading's own day when it is not today ("Tue, 18 Aug"), so nothing reads as today. */
const pastDay = computed(() =>
  props.person ? readingPastDay(props.person.current_day, today.value) : null,
);
const percent = computed(() =>
  props.person
    ? percentOfUsual(props.person.signal.current_steps, props.person.baseline.median_steps)
    : null,
);
const summary = computed(() => {
  const person = props.person;
  if (!person) return null;
  return daySummary({
    elder: props.elder,
    decision: person.last_decision,
    band: person.attention_band,
    gate: person.decided_by_gate,
    safeToInterpret: person.signal.quality.safe_to_interpret,
    consentActive: person.consent_active,
    percent: percent.value,
    pastDay: pastDay.value,
  });
});
const stamp = computed(() =>
  props.person ? readingStamp(props.person.current_day, today.value) : '',
);
/**
 * The one entrance on Home: the first time her day is shown in this visit to the app, the headline,
 * the sentence and the ring rise in 60 ms apart (CSS, 200 ms each, transform and opacity only, so
 * nothing shifts). Coming back to Home later shows them at once. Off under reduced motion.
 */
const enter = !heroHasEntered;
const markEntered = () => {
  if (!props.loading && props.person) heroHasEntered = true;
};
onMounted(markEntered);
watch(() => [props.loading, props.person] as const, markEntered);
</script>

<template>
  <header class="hero sl-hero-field" :aria-busy="loading ? 'true' : undefined">
    <!-- A flat, paler circle in the corner: decoration only. -->
    <span class="hero-blob" aria-hidden="true"></span>
    <MemberAvatar class="hero-avatar" :name="elder" colour="senior" size="xl" />

    <div class="hero-intro">
      <p class="hero-date mb-0">
        <time :datetime="today">{{ longToday(today) }}</time>
      </p>
      <p class="hero-greeting mb-0">
        {{ greeting }}<template v-if="viewer">, {{ viewer }}</template
        >.
      </p>
    </div>

    <div class="hero-body">
      <template v-if="loading">
        <h1 class="visually-hidden">Care+: {{ elder }}’s day</h1>
        <p class="visually-hidden" role="status">Loading {{ elder }}’s day…</p>
        <span class="sl-skeleton sk-title" aria-hidden="true"></span>
        <span class="sl-skeleton sk-line" aria-hidden="true"></span>
        <span class="sl-skeleton sk-meta" aria-hidden="true"></span>
      </template>

      <template v-else-if="person && summary">
        <h1 class="hero-title" :class="{ 'hero-in': enter }" style="--i: 0">
          <span class="visually-hidden">Care+: </span>{{ summary.headline }}
        </h1>
        <p class="hero-lede" :class="{ 'hero-in': enter }" style="--i: 1">
          {{ summary.detail
          }}<template v-if="summary.comparable"
            >:
            <strong class="tabular">{{
              formatSteps(person.signal.current_steps)
            }}</strong></template
          >.
        </p>
        <div class="hero-meta">
          <span class="hero-chip hero-stamp" data-testid="hero-steps-label">{{ stamp }}</span>
          <StatusWhyPanel :person="person" :action="summary.action" />
        </div>
      </template>

      <template v-else>
        <h1 class="hero-title"><span class="visually-hidden">Care+: </span>{{ elder }}’s day</h1>
        <p v-if="noSenior" class="hero-lede">
          No senior is linked to this family group yet. When they show their senior-link PIN on
          their own screen, enter it on the
          <RouterLink to="/family">Family page</RouterLink>.
        </p>
        <p v-else class="hero-lede">
          Her activity can’t be shown right now. The rest of Home still works.
        </p>
      </template>
    </div>

    <div v-if="loading" class="hero-ring" aria-hidden="true">
      <span class="sl-skeleton sk-ring"></span>
    </div>
    <div
      v-else-if="person && summary?.comparable"
      class="hero-ring"
      :class="{ 'hero-in': enter }"
      style="--i: 2"
    >
      <LoopRing
        :value="(percent ?? 0) / 100"
        :size="112"
        :stroke="10"
        color="var(--sl-hero-ring)"
        track="var(--sl-hero-line)"
      >
        <span class="display-num ring-num"
          ><NumberTicker v-if="percent !== null" :value="percent" /><template v-else>–</template
          ><small>%</small></span
        >
      </LoopRing>
      <p class="ring-caption mb-0">
        of her usual day
        <span class="d-block tabular">Usual: {{ formatSteps(person.baseline.median_steps) }}</span>
      </p>
    </div>

    <!-- The quiet facts under the sentence: her watch, her walk, and the screen's sample notice. -->
    <div class="hero-foot">
      <WatchStatus
        v-if="!noSenior"
        class="mt-1"
        role="status"
        :status="wearable"
        :failed="wearableFailed"
        :elder="elder"
        :now="now"
      />
      <WalkLink class="mt-2" />

      <p v-if="sampleNote" class="hero-sample mb-0" data-testid="home-sample">
        <Icon name="info" class="flex-shrink-0" />
        <span><strong>Sample data.</strong> {{ sampleNote }}</span>
      </p>
    </div>
  </header>
</template>

<style scoped>
.hero-in {
  animation: hero-rise 0.2s var(--sl-ease-out) both;
  animation-delay: calc(var(--i) * 60ms);
}

@keyframes hero-rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero-in {
    animation: none;
  }
}

/* The one sunny place on the screen: a flat sun field, no gradient, no border, no shadow. */
.hero {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  display: grid;
  grid-template-areas:
    'avatar intro'
    'body body'
    'ring ring'
    'foot foot';
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 1rem 1.25rem;
  margin-bottom: var(--sl-zone-gap);
  padding: 1.5rem 1.25rem;
  border-radius: var(--sl-radius-lg);
  background: var(--sl-hero);
  color: var(--sl-hero-ink);
  /* Everything on the field (the sentence, Why?, the watch line, the sample note, skeletons)
     takes the field's own inks, never the page's ink-soft. */
  --sl-ink: var(--sl-hero-ink);
  --sl-ink-soft: var(--sl-hero-ink-soft);
  --bs-body-color: var(--sl-hero-ink);
  --bs-heading-color: var(--sl-hero-ink);
  --bs-link-color: var(--sl-hero-ink);
  --bs-link-color-rgb: var(--sl-hero-ink-rgb);
  --bs-link-hover-color: var(--sl-hero-ink);
  --bs-success: var(--sl-hero-ring);
  --bs-warning-text-emphasis: var(--sl-hero-ring);
  --sl-coral-deep: var(--sl-hero-alert);
  --sl-skeleton: var(--sl-hero-line);
}

.hero-blob {
  position: absolute;
  z-index: -1;
  top: -3.5rem;
  right: -3rem;
  width: 13rem;
  height: 13rem;
  border-radius: 50%;
  background: var(--sl-hero-blob);
  pointer-events: none;
}

@media (min-width: 768px) {
  .hero-blob {
    top: -6rem;
    right: -4rem;
    width: 22rem;
    height: 22rem;
  }
}

/* The hero's facts (the day of the steps, the watch) are ink chips with sun words. */
.hero-chip,
.hero :deep(.watch-part) {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 2rem;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  background: var(--sl-hero-chip);
  color: var(--sl-hero-chip-ink);
  font-size: 0.875rem;
  font-weight: 700;
}

.hero :deep(.watch-line) {
  gap: 0.5rem;
}

.hero :deep(.watch-part .dot),
.hero :deep(.watch-part.on .dot) {
  background: currentcolor;
}

.hero :deep(.watch-part:not(.on) .dot) {
  background: transparent;
  box-shadow: inset 0 0 0 2px currentcolor;
}

/* On a chip the battery keeps the chip's words; "low" is said in words, and a critical battery
   also shows the reminder below. */
.hero :deep(.watch-part.battery) {
  color: var(--sl-hero-chip-ink);
}
/* Links on the field are stone and underlined, so they read as links without jade. */
.hero :deep(a:not(.btn):not(.walk-link)) {
  text-decoration: underline;
  text-underline-offset: 0.2em;
}

@media (min-width: 768px) {
  .hero {
    grid-template-areas:
      'avatar intro ring'
      'avatar body ring'
      'avatar foot foot';
    grid-template-columns: auto 1fr auto;
    align-items: start;
    gap: 0.5rem 2rem;
    padding: 2rem 2.25rem;
  }

  .hero-ring {
    position: relative;
    align-self: center;
    flex-direction: column;
    text-align: center;
  }
}

.hero-avatar {
  grid-area: avatar;
}

.hero-intro {
  grid-area: intro;
  min-width: 0;
}

.hero-body {
  grid-area: body;
  min-width: 0;
}

.hero-foot {
  grid-area: foot;
  min-width: 0;
}

.hero-ring {
  display: flex;
  grid-area: ring;
  align-items: center;
  gap: 1rem;
}

/* Phones: the sentence carries the answer, so the ring steps aside and the hero stays short
   enough for "Needs you" and its first visit to show on the first screen. */
@media (max-width: 767.98px) {
  /* No empty row where the ring was. */
  .hero {
    grid-template-areas:
      'avatar intro'
      'body body'
      'foot foot';
    gap: 0.75rem 1rem;
    margin-bottom: 1.75rem;
    padding: 1.25rem 1rem;
  }

  .hero .hero-avatar {
    width: 3.5rem;
    height: 3.5rem;
    font-size: 1.25rem;
  }

  .hero .hero-ring {
    display: none;
  }

  .hero .hero-title {
    margin: 0 0 0.35rem;
    font-size: 1.55rem;
  }

  .hero .hero-lede {
    margin-bottom: 0;
    font-size: 1.1rem;
  }

  .hero .hero-sample {
    margin-top: 0.5rem;
    font-size: 0.85rem;
  }
}

.hero-date {
  color: var(--sl-ink-soft);
  font-weight: 700;
}

.hero-greeting {
  font-size: 1.15rem;
  font-weight: 600;
}

.hero-title {
  max-width: 30ch;
  margin: 0.25rem 0 0.5rem;
  font-size: 1.75rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  text-wrap: balance;
}

@media (min-width: 768px) {
  .hero-title {
    font-size: 2.25rem;
  }
}

.hero-lede {
  max-width: 40rem;
  margin-bottom: 0.5rem;
  font-size: 1.2rem;
  line-height: 1.45;
}

.hero-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 1rem;
  margin-bottom: 0;
  color: var(--sl-ink-soft);
  font-weight: 600;
}

/* Why?, once open, takes its own line under the sentence instead of opening to the right. */
.hero-meta :deep(.why[open]) {
  flex-basis: 100%;
}

.hero-sample {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  max-width: 40rem;
  margin-top: 1rem;
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
}

.hero-sample .sl-icon {
  margin-top: 0.15rem;
}

/* The ring is drawn in px (LoopRing), so its number is too: at 150% zoom it still fits inside. */
.ring-num {
  font-size: 28px;
}

.ring-num small {
  font-size: 0.5em;
  font-weight: 700;
}

.ring-caption {
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
  font-weight: 700;
}

/* Loading: flat bars at the size of the sentence, the line under it and the ring. */
.sk-title {
  width: min(24rem, 90%);
  height: 2.25rem;
  margin: 0.25rem 0 0.75rem;
}

.sk-line {
  width: min(20rem, 75%);
  height: 1.2rem;
  margin-bottom: 0.6rem;
}

.sk-meta {
  width: min(14rem, 55%);
  height: 1rem;
}

.sk-ring {
  width: 120px;
  height: 120px;
  border-radius: 50%;
}
</style>
