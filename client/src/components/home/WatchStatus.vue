<script setup lang="ts">
import type { WearableStatus } from '@silverloop/api-client';
import { computed } from 'vue';
import { RouterLink } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { batteryLevel, describeBattery, syncedAgo } from '@/lib/wearable';

/**
 * The senior's watch on Home: connected or not, when it last synced, and its battery, coloured the
 * way phones colour it. When it is low (red) the family is asked to remind the senior to charge it.
 * Simulated until a real device is connected, and labelled so.
 */
const props = defineProps<{
  status: WearableStatus | null;
  /** True when the status could not be read. */
  failed: boolean;
  elder: string;
  now: Date;
}>();

const percent = computed(() => props.status?.battery_percent ?? null);
const level = computed(() =>
  percent.value === null ? null : batteryLevel(percent.value, props.status?.charging ?? false),
);
const words = computed(() =>
  percent.value === null ? '' : describeBattery(percent.value, props.status?.charging ?? false),
);
const synced = computed(() =>
  props.status?.last_synced_at ? syncedAgo(props.status.last_synced_at, props.now) : null,
);
</script>

<template>
  <!-- One quiet line: connected or not, last sync, battery, and that the watch is simulated. Only a
       low battery gets colour, because only then is there something to do. -->
  <div class="watch" data-testid="watch-status">
    <p class="watch-line mb-0">
      <span v-if="failed" class="watch-part">
        <span class="dot" aria-hidden="true"></span>Watch status unavailable
      </span>
      <template v-else-if="status">
        <span class="watch-part" :class="{ on: status.connected }">
          <span class="dot" aria-hidden="true"></span>
          <template v-if="status.connected">
            Watch connected<template v-if="synced"> · {{ synced }}</template>
          </template>
          <template v-else>Watch not connected</template>
        </span>
        <span
          v-if="percent !== null && level"
          class="watch-part battery"
          :class="`battery-${level}`"
          data-testid="watch-battery"
        >
          <span class="cell" aria-hidden="true">
            <span class="fill" :style="{ width: `${percent}%` }"></span>
          </span>
          <span><span class="visually-hidden">Watch battery </span>{{ words }}</span>
        </span>
        <!-- Opens the watch in 3D (/watch). -->
        <RouterLink to="/watch" class="watch-part sim sim-link" data-testid="watch-open">
          <Icon name="watch" /><span class="sim-words">Simulated watch</span
          ><Icon name="chevron-right" />
        </RouterLink>
      </template>
      <span v-else class="watch-part">
        <span class="dot" aria-hidden="true"></span>Checking the watch…
      </span>
    </p>

    <p v-if="level === 'critical'" class="remind mb-0" data-testid="charge-reminder">
      The watch battery is low. Remind {{ elder }} to charge the watch.
    </p>
  </div>
</template>

<style scoped>
.watch-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 1rem;
  color: var(--sl-ink-soft);
  font-size: 0.95rem;
}

.watch-part {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  background: var(--sl-ink-soft);
}

/* Connected: green dot, as on most devices. Not connected: grey. */
.on .dot {
  background: var(--bs-success);
}

/* A small battery: a cell with a fill the width of the charge, and a nub on the right. */
.cell {
  position: relative;
  width: 1.4rem;
  height: 0.7rem;
  padding: 1px;
  border: 2px solid currentcolor;
  border-radius: 3px;
}

.cell::after {
  position: absolute;
  top: 50%;
  right: -5px;
  width: 3px;
  height: 0.3rem;
  border-radius: 0 1px 1px 0;
  background: currentcolor;
  content: '';
  transform: translateY(-50%);
}

.fill {
  display: block;
  height: 100%;
  border-radius: 1px;
  background: currentcolor;
}

/* Quiet while fine or charging; amber when getting low, red when it needs charging. */
.battery-low {
  color: var(--bs-warning-text-emphasis);
  font-weight: 600;
}

.battery-critical {
  color: var(--sl-coral-deep);
  font-weight: 700;
}

.sim {
  font-size: 0.85rem;
}

/* The way into the 3D watch. On the Home hero it is one of the ink chips (HomeHero styles every
   `.watch-part`), so it keeps the chip's own words rather than a colour of its own; the watch icon
   and the arrow say it opens something, and the words underline on hover and focus. */
.sim-link {
  color: inherit;
  text-decoration: none;
  transition: transform 0.2s ease;
}

@media (hover: hover) and (pointer: fine) {
  .sim-link:hover {
    transform: translateX(2px);
  }
}

.sim-link:hover .sim-words,
.sim-link:focus-visible .sim-words {
  text-decoration: underline;
}

.remind {
  margin-top: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-coral-soft);
  color: var(--sl-coral-deep);
  font-weight: 600;
}
</style>
