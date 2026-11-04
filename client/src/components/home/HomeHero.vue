<script lang="ts">
/** Set once her day has been shown, so the hero's entrance plays once per visit to the app. */
let heroHasEntered = false;
</script>

<script setup lang="ts">
import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, onMounted, watch } from 'vue';
import { RouterLink } from 'vue-router';

import HeroWatch from '@/components/home/HeroWatch.vue';
import NumberTicker from '@/components/motion/NumberTicker.vue';
import StatusWhyPanel from '@/components/home/StatusWhyPanel.vue';
import WatchStatus from '@/components/home/WatchStatus.vue';
import Icon from '@/components/ui/Icon.vue';
import WalkLink from '@/components/walk/WalkLink.vue';
import { formatSteps, percentOfUsual } from '@/lib/activity';
import { todayIso } from '@/lib/calendar';
import { crossSplit, longToday, readingPastDay, readingStamp } from '@/lib/home';
import { daySummary } from '@/lib/labels';

/**
 * The top of family Home, set like an editorial cover on a plum field: her day as one large
 * serif headline (built from the policy's own result, `daySummary`), one plain line under it, the
 * page's one action ("What needs you") and a way to hear the family's catch-up read aloud. Her
 * watch stands beside it, live and turnable, with its status chips underneath; the Simulated watch
 * chip opens the full watch page. The greeting, the date, "Why?" and the screen's one sample-data
 * notice sit quietly at the foot. A torn-paper edge hands over to the cream page below.
 */
const props = defineProps<{
  person: PersonState | null;
  loading: boolean;
  /** The senior's watch, or `null` while it is being read (or if reading it failed). */
  wearable: WearableStatus | null;
  wearableFailed: boolean;
  /** Her recent days, for the little chart on the watch's screen. */
  history: DailyMetric[] | null;
  now: Date;
  greeting: string;
  /** The family member using the app, if one is chosen. */
  viewer: string | null;
  elder: string;
  /** True when the family group has no senior linked yet. */
  noSenior?: boolean;
  /** The screen's one sample-data sentence, or `null` when nothing shown is sample. */
  sampleNote?: string | null;
  /** "Hear the catch-up": shown once there is a catch-up to read; `reading` while it is read. */
  listen?: { available: boolean; reading: boolean } | null;
}>();
const emit = defineEmits<{ listen: [] }>();

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
/** Where the orange cross sits inside the headline, if anywhere (`crossSplit`). */
const split = computed(() =>
  summary.value ? crossSplit(summary.value.headline, props.elder) : null,
);
const stamp = computed(() =>
  props.person ? readingStamp(props.person.current_day, today.value) : '',
);
const showWatch = computed(() => !props.noSenior);

/**
 * The one entrance on Home: the first time her day is shown in this visit to the app, the headline,
 * the line under it and the actions rise in 60 ms apart (CSS, 200 ms each, transform and opacity
 * only, so nothing shifts). Coming back to Home later shows them at once. Off under reduced motion.
 */
const enter = !heroHasEntered;
const markEntered = () => {
  if (!props.loading && props.person) heroHasEntered = true;
};
onMounted(markEntered);
watch(() => [props.loading, props.person] as const, markEntered);
</script>

<template>
  <header
    class="hero"
    :class="{ 'hero--solo': !showWatch }"
    :aria-busy="loading ? 'true' : undefined"
  >
    <div class="hero-copy">
      <template v-if="loading">
        <h1 class="visually-hidden">Care+: {{ elder }}’s day</h1>
        <p class="visually-hidden" role="status">Loading {{ elder }}’s day…</p>
        <span class="sl-skeleton sk-title" aria-hidden="true"></span>
        <span class="sl-skeleton sk-title sk-title--short" aria-hidden="true"></span>
        <span class="sl-skeleton sk-line" aria-hidden="true"></span>
      </template>

      <template v-else-if="person && summary">
        <h1 class="hero-title ed-serif" :class="{ 'hero-in': enter }" style="--i: 0">
          <span class="visually-hidden">Care+: </span>
          <template v-if="split"
            >{{ split.before }}
            <svg class="hero-cross" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 2.5h6v6.5h6.5v6H15v6.5H9V15H2.5V9H9z" />
            </svg>
            {{ split.after }}</template
          >
          <template v-else>{{ summary.headline }}</template>
        </h1>
        <p class="hero-lede" :class="{ 'hero-in': enter }" style="--i: 1">
          {{ summary.detail
          }}<template v-if="summary.comparable"
            >: <strong class="tabular">{{ formatSteps(person.signal.current_steps) }}</strong
            ><template v-if="percent !== null"
              >, <strong class="tabular"><NumberTicker :value="percent" />%</strong> of her usual
              day</template
            ></template
          >.
        </p>
      </template>

      <template v-else>
        <h1 class="hero-title ed-serif">
          <span class="visually-hidden">Care+: </span>{{ elder }}’s day
        </h1>
        <p v-if="noSenior" class="hero-lede">
          No senior is linked to this family group yet. When they show their senior-link PIN on
          their own screen, enter it on the
          <RouterLink to="/family">Family page</RouterLink>.
        </p>
        <p v-else class="hero-lede">
          Her activity can’t be shown right now. The rest of Home still works.
        </p>
      </template>

      <div v-if="!loading" class="hero-actions" :class="{ 'hero-in': enter }" style="--i: 2">
        <a class="ed-pill ed-pill--lime" href="#home-needs-you">
          What needs you<Icon name="arrow-right" />
        </a>
        <button
          v-if="listen?.available"
          type="button"
          class="hero-listen"
          :aria-pressed="listen.reading"
          data-testid="hero-listen"
          @click="emit('listen')"
        >
          <span class="hero-listen-disc" aria-hidden="true">
            <Icon :name="listen.reading ? 'stop' : 'play'" />
          </span>
          <span class="hero-listen-words">{{
            listen.reading ? 'Stop reading' : 'Hear the catch-up'
          }}</span>
        </button>
      </div>

      <!-- The quiet facts: who is looking, today, the steps' own day, Why?, and her walk. -->
      <div v-if="!loading" class="hero-meta">
        <p class="hero-greeting mb-0">
          {{ greeting }}<template v-if="viewer">, {{ viewer }}</template
          >. <time class="hero-date" :datetime="today">{{ longToday(today) }}</time>
        </p>
        <template v-if="person && summary">
          <span class="hero-stamp" data-testid="hero-steps-label">{{ stamp }}</span>
          <StatusWhyPanel :person="person" :action="summary.action" />
        </template>
        <WalkLink />
      </div>

      <p v-if="sampleNote" class="hero-sample mb-0" data-testid="home-sample">
        <Icon name="info" class="flex-shrink-0" />
        <span><strong>Sample data.</strong> {{ sampleNote }}</span>
      </p>
    </div>

    <div v-if="showWatch" class="hero-visual">
      <div v-if="loading" class="sk-watch" aria-hidden="true">
        <span class="sl-skeleton sk-watch-body"></span>
      </div>
      <HeroWatch
        v-else
        :person="person"
        :history="history"
        :wearable="wearable"
        :now="now"
        :day-label="pastDay ?? 'Today'"
      />
      <WatchStatus
        class="hero-watch-status"
        role="status"
        :status="wearable"
        :failed="wearableFailed"
        :elder="elder"
        :now="now"
      />
    </div>

    <!-- The torn-paper edge into the page below. Decoration only. -->
    <svg class="hero-tear" viewBox="0 0 1440 40" preserveAspectRatio="none" aria-hidden="true">
      <path
        d="M0 40V22l38-6 31 9 44-11 29 8 52-12 23 10 47-7 36 9 41-13 28 11 55-8 33 7 46-10 24 8 39-5 50 9 27-12 44 7 31-6 49 10 36-9 28 6 53-11 30 10 41-7 35 9 47-12 26 8 50-6 33 10 45-9 29 7 38-8L1440 20V40z"
      />
    </svg>
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

/*
 * The plum field runs the full width of the window: the content keeps the page's container, and
 * the field is painted past it (the clip keeps the paint from making the page scroll sideways).
 */
.hero {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1.5rem;
  padding: 2.5rem 0 4.5rem;
  background: var(--ed-plum);
  box-shadow: 0 0 0 100vmax var(--ed-plum);
  clip-path: inset(0 -100vmax);
  color: var(--ed-on-plum);
  /* Everything on the field takes its inks: the sentence, Why?, the walk link, the sample note. */
  --sl-ink: var(--ed-on-plum);
  --sl-ink-soft: var(--ed-on-plum-soft);
  --bs-body-color: var(--ed-on-plum);
  --bs-heading-color: var(--ed-on-plum);
  --bs-link-color: var(--ed-on-plum);
  --bs-link-hover-color: var(--ed-on-plum);
  --sl-skeleton: var(--ed-line-on-plum);
  --sl-focus: var(--ed-on-plum);
}

@media (min-width: 992px) {
  .hero {
    grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
    align-items: center;
    gap: 2rem;
    min-height: 34rem;
    padding: 3.5rem 0 6rem;
  }

  .hero--solo {
    grid-template-columns: minmax(0, 1fr);
    min-height: 0;
  }
}

.hero-copy {
  min-width: 0;
}

.hero-title {
  max-width: 13ch;
  margin: 0 0 1.25rem;
  font-size: clamp(2.75rem, 7.5vw, 5.75rem);
  line-height: 0.98;
  letter-spacing: -0.025em;
  text-wrap: balance;
}

.hero--solo .hero-title {
  max-width: 18ch;
}

.hero-cross {
  display: inline-block;
  width: 0.62em;
  height: 0.62em;
  margin: 0 0.04em;
  vertical-align: -0.02em;
  fill: var(--ed-cross);
}

.hero-lede {
  max-width: 34rem;
  margin-bottom: 2rem;
  color: var(--ed-on-plum-soft);
  font-size: 1.2rem;
  line-height: 1.5;
}

.hero-lede strong {
  color: var(--ed-on-plum);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem 1.5rem;
}

/* "Hear the catch-up": the round lime button with its words beside it, as in the reference. */
.hero-listen {
  display: inline-flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 3rem;
  padding: 0;
  border: 0;
  background: none;
  color: var(--ed-on-plum);
  font-weight: 700;
  text-align: left;
}

.hero-listen-disc {
  display: grid;
  place-items: center;
  width: 3.25rem;
  height: 3.25rem;
  border-radius: 50%;
  background: var(--ed-lime);
  color: var(--ed-lime-ink);
  transition: transform var(--sl-dur-base) var(--sl-ease-out);
}

.hero-listen-disc .sl-icon {
  width: 1.15rem;
  height: 1.15rem;
}

@media (hover: hover) and (pointer: fine) {
  .hero-listen:hover .hero-listen-disc {
    transform: scale(1.06);
  }
}

.hero-listen:focus-visible {
  border-radius: 999px;
  outline: 3px solid var(--ed-on-plum);
  outline-offset: 4px;
}

.hero-listen-words {
  max-width: 7rem;
  line-height: 1.2;
}

.hero-actions .ed-pill:focus-visible {
  outline-color: var(--ed-on-plum);
}

.hero-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1.25rem;
  margin-top: 2.5rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--ed-line-on-plum);
  color: var(--ed-on-plum-soft);
  font-size: 0.95rem;
}

.hero-greeting {
  color: var(--ed-on-plum);
  font-weight: 600;
}

.hero-greeting .hero-date {
  margin-left: 0.25rem;
  color: var(--ed-on-plum-soft);
  font-weight: 400;
}

.hero-stamp {
  font-weight: 700;
}

.hero-meta :deep(.why[open]) {
  flex-basis: 100%;
}

.hero :deep(a:not(.ed-pill):not(.walk-link)) {
  text-decoration: underline;
  text-underline-offset: 0.2em;
}

.hero-sample {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  max-width: 38rem;
  margin-top: 1rem;
  color: var(--ed-on-plum-soft);
  font-size: 0.875rem;
}

.hero-sample .sl-icon {
  margin-top: 0.15rem;
}

.hero-visual {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}

/* Her watch's facts are quiet outlined chips on the plum, the Simulated watch chip opens it. */
.hero-watch-status {
  margin-top: 0.75rem;
}

.hero :deep(.watch-line) {
  justify-content: center;
  gap: 0.5rem;
}

.hero :deep(.watch-part) {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 2.25rem;
  padding: 0.3rem 0.85rem;
  border: 1px solid var(--ed-line-on-plum);
  border-radius: 999px;
  color: var(--ed-on-plum);
  font-size: 0.875rem;
  font-weight: 700;
}

.hero :deep(.watch-part .dot),
.hero :deep(.watch-part.on .dot) {
  background: var(--ed-lime);
}

.hero :deep(.watch-part:not(.on) .dot) {
  background: transparent;
  box-shadow: inset 0 0 0 2px currentcolor;
}

.hero :deep(.watch-part.battery) {
  color: var(--ed-on-plum);
}

/* The way into the 3D watch: the one filled chip in the row. */
.hero :deep(.watch-part.sim-link) {
  border-color: var(--ed-lime);
  background: var(--ed-lime);
  color: var(--ed-lime-ink);
}

.hero :deep(.watch-part.sim-link:focus-visible) {
  outline: 3px solid var(--ed-on-plum);
  outline-offset: 3px;
}

.hero :deep(.remind) {
  color: var(--ed-on-plum);
}

.hero-tear {
  position: absolute;
  bottom: -1px;
  left: 50%;
  width: 100vw;
  height: 2.25rem;
  transform: translateX(-50%);
  fill: var(--ed-cream);
}

/* Loading: flat bars at the headline's size, and the watch's place held. */
.sk-title {
  display: block;
  width: min(30rem, 90%);
  height: 3.5rem;
  margin-bottom: 0.75rem;
}

.sk-title--short {
  width: min(20rem, 65%);
}

.sk-line {
  display: block;
  width: min(24rem, 80%);
  height: 1.2rem;
  margin-top: 1.5rem;
}

.sk-watch {
  display: grid;
  place-items: center;
  height: 26rem;
}

.sk-watch-body {
  width: 11rem;
  height: 13rem;
  border-radius: 2.5rem;
}

@media (max-width: 767.98px) {
  .hero {
    gap: 0.5rem;
    padding: 1.75rem 0 3.5rem;
  }

  .hero-lede {
    margin-bottom: 1.5rem;
    font-size: 1.1rem;
  }

  .hero-meta {
    margin-top: 1.75rem;
  }

  .sk-watch {
    height: 20rem;
  }
}
</style>
