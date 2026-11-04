<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import BadgeShelf from '@/components/badges/BadgeShelf.vue';
import CheckInPanel from '@/components/walk/CheckInPanel.vue';
import DemoWalkControls from '@/components/walk/DemoWalkControls.vue';
import WalkFacts from '@/components/walk/WalkFacts.vue';
import WalkMap from '@/components/walk/WalkMap.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamily } from '@/composables/useFamily';
import { currentGroup } from '@/composables/useMe';
import { useWalk } from '@/composables/useWalk';
import { AUTH_ENABLED } from '@/lib/config';
import { DEMO_PERSON_ID } from '@/lib/labels';
import type { MapLook } from '@/lib/map-style';
import { ago, clockTime, STATE_WORDS, type WalkFix } from '@/lib/walk';

/**
 * The family's live view of the senior's walk: a 3D map they can explore, her walk in words, the
 * "Still for a while" check-in, and a replay of today's walk. Shown only while the senior shares her
 * walk. Until a real watch is connected the readings come from the simulated walk below the map.
 */
const walk = useWalk();
// The calendar, so a long stay during an appointment is not flagged.
useFamily();

const name = walk.seniorName;
// Her walking badges come from her steps, so they show whether or not she shares her walk.
const badgePerson = computed(() => currentGroup.value?.person_id ?? DEMO_PERSON_ID);
const follow = ref(true);
const threeD = ref(true);
const look = ref<MapLook>(import.meta.env.VITE_WALK_MAP === 'sketch' ? 'sketch' : 'streets');

// ---- Replay: drag back through today's walk ----

/** The time being replayed, or null for live. */
const replayAt = ref<number | null>(null);
const live = computed(() => replayAt.value === null);
const firstAt = computed(() => walk.fixes.value[0]?.at ?? 0);
const lastAt = computed(() => walk.latest.value?.at ?? 0);

const shownTrail = computed<readonly WalkFix[]>(() => {
  const at = replayAt.value;
  return at === null ? walk.fixes.value : walk.fixes.value.filter((fix) => fix.at <= at);
});
const shownPosition = computed(() =>
  live.value ? walk.latest.value : (shownTrail.value[shownTrail.value.length - 1] ?? null),
);

function scrub(event: Event) {
  const value = Number((event.target as HTMLInputElement).value);
  replayAt.value = value >= lastAt.value ? null : value;
  if (replayAt.value !== null) follow.value = true;
}

// A new demo walk (or a recorded one) starts live again.
watch(
  () => [walk.demoState.value?.startedAt, walk.route.value] as const,
  () => {
    replayAt.value = null;
  },
);

// ---- One short line on the map, and a screen-reader announcement when the state changes ----

const pill = computed(() => {
  const fix = walk.latest.value;
  if (!fix) return 'Waiting for the watch';
  if (!live.value && shownPosition.value) return `Replaying ${clockTime(shownPosition.value.at)}`;
  return `${STATE_WORDS[walk.state.value]} · ${ago(walk.now.value - fix.at)}`;
});

const announcement = ref('');
watch(
  () => walk.state.value,
  (state, before) => {
    if (state !== before && walk.latest.value) {
      announcement.value = `${name.value}: ${STATE_WORDS[state].toLowerCase()}, near ${walk.near.value}.`;
    }
  },
);
</script>

<template>
  <div class="walk-page">
    <header class="sl-page-head walk-head">
      <div>
        <p class="walk-eyebrow mb-1"><Icon name="walk" /> Live walk</p>
        <h1>{{ name }}’s walk</h1>
        <p class="sl-lede mb-0">
          Where {{ name }} is right now, shared by their own choice. Explore the map, replay the
          walk, and see if they have stayed in one place for a long time.
        </p>
      </div>
      <span v-if="walk.sharing.value" class="sl-tag sl-tone-jade" data-testid="walk-sharing">
        <Icon name="check" /> {{ name }} is sharing their walk
      </span>
    </header>

    <!-- Her choice: no walk is shown unless she shares it. -->
    <section
      v-if="!walk.sharing.value"
      class="sl-panel walk-not-shared"
      data-testid="walk-not-shared"
      aria-labelledby="not-shared-heading"
    >
      <Icon name="eye-off" />
      <div>
        <h2 id="not-shared-heading" class="h4">{{ name }} is not sharing their walks</h2>
        <p class="mb-2">
          {{ name }}’s location is shown only when they turn on “Share my walk with my family” on
          their own page. They can turn it off at any time.
        </p>
        <p v-if="!AUTH_ENABLED" class="sl-note mb-0">
          In the demo: sign out, choose “I’m the senior”, and turn it on under “My walks”.
        </p>
      </div>
    </section>

    <div v-else class="walk-layout">
      <div class="walk-main">
        <WalkMap
          v-model:follow="follow"
          v-model:three-d="threeD"
          v-model:look="look"
          :route="walk.route.value"
          :trail="shownTrail"
          :position="shownPosition"
          :live="live"
          :senior-name="name"
        >
          <p class="walk-pill" :class="{ 'is-replay': !live }" data-testid="walk-pill">
            <span class="walk-pill-dot" aria-hidden="true"></span>{{ pill }}
          </p>
        </WalkMap>

        <div v-if="walk.fixes.value.length > 1" class="walk-replay sl-panel">
          <label for="walk-replay" class="form-label mb-1">
            Replay today’s walk
            <span class="sl-note ms-1">
              {{ live ? 'Showing now' : `Showing ${clockTime(replayAt ?? 0)}` }}
            </span>
          </label>
          <div class="d-flex align-items-center gap-3">
            <span class="sl-note tabular">{{ clockTime(firstAt) }}</span>
            <input
              id="walk-replay"
              class="form-range flex-grow-1"
              type="range"
              :min="firstAt"
              :max="lastAt"
              :step="5000"
              :value="replayAt ?? lastAt"
              :aria-valuetext="live ? 'Now' : clockTime(replayAt ?? 0)"
              data-testid="walk-replay"
              @input="scrub"
            />
            <button
              type="button"
              class="btn btn-sm btn-outline-primary"
              :disabled="live"
              data-testid="walk-live"
              @click="replayAt = null"
            >
              Now
            </button>
          </div>
        </div>
      </div>

      <div class="walk-side">
        <WalkFacts />
        <CheckInPanel />
        <DemoWalkControls />
      </div>
    </div>

    <BadgeShelf
      class="mt-4"
      :person-id="badgePerson"
      :can-claim="false"
      :senior-name="name"
      :title="`${name}’s walking badges`"
    />

    <p class="visually-hidden" aria-live="polite">{{ announcement }}</p>
  </div>
</template>

<style scoped>
.walk-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
}

.walk-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--sl-jade-deep);
  font-size: 0.85rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.walk-not-shared {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  max-width: 44rem;
}

.walk-not-shared > .sl-icon {
  flex: none;
  width: 2rem;
  height: 2rem;
  color: var(--sl-ink-soft);
}

.walk-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1.25rem;
}

@media (min-width: 992px) {
  .walk-layout {
    grid-template-columns: minmax(0, 1fr) minmax(20rem, 24rem);
    align-items: start;
  }

  .walk-side {
    position: sticky;
    top: calc(var(--sl-pinned-height, 4.5rem) + 1rem);
  }
}

.walk-main,
.walk-side {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.walk-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  padding: 0.45rem 0.85rem;
  border-radius: 999px;
  background: var(--sl-surface);
  color: var(--sl-ink);
  box-shadow: var(--sl-float);
  font-weight: 700;
}

.walk-pill-dot {
  width: 0.65rem;
  height: 0.65rem;
  border-radius: 50%;
  background: var(--sl-jade);
  box-shadow: 0 0 0 3px var(--sl-jade-soft);
}

.walk-pill.is-replay .walk-pill-dot {
  background: var(--sl-ink-soft);
  box-shadow: none;
}

.walk-replay {
  padding: 0.9rem 1.1rem;
}

.walk-replay .tabular {
  white-space: nowrap;
}

.walk-replay .form-range::-webkit-slider-thumb {
  background: var(--sl-jade);
}

.walk-replay .form-range::-moz-range-thumb {
  background: var(--sl-jade);
}

.walk-replay .form-range:focus::-webkit-slider-thumb {
  box-shadow: 0 0 0 0.25rem var(--sl-jade-soft);
}
</style>
