<script setup lang="ts">
import { computed } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useWalk } from '@/composables/useWalk';
import { distanceM } from '@/lib/geo';
import {
  ago,
  clockTime,
  formatDistance,
  formatDuration,
  lngLatOf,
  STATE_WORDS,
  type WalkState,
} from '@/lib/walk';

/**
 * Her walk in words: what she is doing and where, when the watch last sent a reading, and the
 * walk's figures. Everything the map shows as a picture is said here, for anyone who cannot see it.
 */
const walk = useWalk();

const TONES: Record<WalkState, string> = {
  waiting: 'sl-tone-blue',
  walking: 'sl-tone-jade',
  resting: 'sl-tone-blue',
  home: 'sl-tone-jade',
  signal_lost: 'sl-tone-orange',
};
const ICONS = {
  waiting: 'home',
  walking: 'walk',
  resting: 'clock',
  home: 'home',
  signal_lost: 'watch',
} as const;

const fromHome = computed(() => {
  const fix = walk.latest.value;
  if (!fix) return null;
  const home = walk.route.value.home;
  return distanceM([home.lng, home.lat], lngLatOf(fix));
});

/** One line saying it all: "Walking near the pond", "Out of signal since 4:12 pm, near …". */
const headline = computed(() => {
  const fix = walk.latest.value;
  const state = walk.state.value;
  if (!fix) return STATE_WORDS.waiting;
  if (state === 'home') return 'Back home';
  if (state === 'signal_lost') {
    return `Watch out of signal since ${clockTime(fix.at)}. Last seen near ${walk.near.value}.`;
  }
  return `${STATE_WORDS[state]} near ${walk.near.value}`;
});

const gps = computed(() => {
  const fix = walk.latest.value;
  if (!fix) return null;
  return fix.accuracyM <= 10
    ? `Good (within ${fix.accuracyM} m)`
    : `Weak (within ${fix.accuracyM} m)`;
});
</script>

<template>
  <section class="sl-panel walk-facts" aria-labelledby="walk-facts-heading">
    <h2 id="walk-facts-heading" class="h5 mb-3">Right now</h2>

    <p class="walk-headline sl-tag mb-2" :class="TONES[walk.state.value]" data-testid="walk-state">
      <Icon :name="ICONS[walk.state.value]" />{{ headline }}
    </p>
    <p v-if="walk.latest.value" class="sl-note mb-3" data-testid="walk-updated">
      Last reading {{ ago(walk.now.value - walk.latest.value.at) }}
      <span aria-hidden="true">·</span> {{ clockTime(walk.latest.value.at) }}
    </p>

    <dl class="walk-figures mb-0">
      <div>
        <dt>Time out</dt>
        <dd class="tabular" data-testid="walk-time">
          {{ walk.latest.value ? formatDuration(walk.summary.value.durationMs) : '–' }}
        </dd>
      </div>
      <div>
        <dt>Distance</dt>
        <dd class="tabular" data-testid="walk-distance">
          {{ formatDistance(walk.summary.value.distanceM) }}
        </dd>
      </div>
      <div>
        <dt>Steps <span class="fw-normal">(estimate)</span></dt>
        <dd class="tabular">about {{ walk.summary.value.aboutSteps.toLocaleString('en-SG') }}</dd>
      </div>
      <div>
        <dt>Pace</dt>
        <dd class="tabular">
          <template v-if="walk.summary.value.paceMinPerKm">
            {{ Math.round(walk.summary.value.paceMinPerKm) }} min per km
          </template>
          <template v-else>Not yet</template>
        </dd>
      </div>
      <div>
        <dt>From home</dt>
        <dd class="tabular">{{ fromHome === null ? '–' : formatDistance(fromHome) }}</dd>
      </div>
      <div>
        <dt>GPS</dt>
        <dd>{{ gps ?? '–' }}</dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.walk-headline {
  padding: 0.45rem 0.85rem;
  font-size: 1rem;
  white-space: normal;
}

.walk-figures {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem 1rem;
}

.walk-figures dt {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
}

.walk-figures dd {
  margin: 0.1rem 0 0;
  color: var(--sl-ink);
  font-size: 1.1rem;
  font-weight: 700;
}
</style>
