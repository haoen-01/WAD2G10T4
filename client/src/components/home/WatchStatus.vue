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
  <div class="watch" data-testid="watch-status">
    <span v-if="failed" class="chip chip-off">
      <span class="dot" aria-hidden="true"></span>Watch status unavailable
    </span>
    <template v-else-if="status">
      <span class="chip" :class="status.connected ? 'chip-on' : 'chip-off'">
        <span class="dot" aria-hidden="true"></span>
        <template v-if="status.connected">
          Watch connected<template v-if="synced"> · {{ synced }}</template>
        </template>
        <template v-else>Watch not connected</template>
      </span>
      <span
        v-if="percent !== null && level"
        class="chip battery"
        :class="`battery-${level}`"
        data-testid="watch-battery"
      >
        <span class="cell" aria-hidden="true">
          <span class="fill" :style="{ width: `${percent}%` }"></span>
        </span>
        <span><span class="visually-hidden">Watch battery </span>{{ words }}</span>
      </span>
      <!-- Opens the watch in 3D. -->
      <RouterLink to="/watch" class="sim-link" data-testid="watch-open">
        <Icon name="watch" class="me-1" />Simulated watch<Icon name="chevron-right" class="ms-1" />
      </RouterLink>
    </template>
    <span v-else class="chip chip-off"
      ><span class="dot" aria-hidden="true"></span>Checking the watch…</span
    >

    <p v-if="level === 'critical'" class="remind mb-0" data-testid="charge-reminder">
      The watch battery is low. Remind {{ elder }} to charge the watch.
    </p>
  </div>
</template>

<style scoped>
.watch {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.3rem 0.75rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
  background: var(--sl-surface);
  font-size: 0.9rem;
  font-weight: 600;
}

.dot {
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--bs-secondary);
}

/* Connected: green dot, as on most devices. Not connected: grey. */
.chip-on .dot {
  background: var(--bs-success);
}

/* A small battery: a cell with a fill the width of the charge, and a nub on the right. */
.cell {
  position: relative;
  width: 1.6rem;
  height: 0.8rem;
  padding: 1px;
  border: 2px solid currentcolor;
  border-radius: 3px;
}

.cell::after {
  position: absolute;
  top: 50%;
  right: -5px;
  width: 3px;
  height: 0.35rem;
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

/* Green when fine or charging, amber when getting low, red when it needs charging. */
.battery-good,
.battery-charging {
  border-color: var(--bs-success-border-subtle);
  background: var(--bs-success-bg-subtle);
  color: var(--bs-success-text-emphasis);
}

.battery-low {
  border-color: var(--bs-warning-border-subtle);
  background: var(--bs-warning-bg-subtle);
  color: var(--bs-warning-text-emphasis);
}

.battery-critical {
  border-color: var(--bs-danger-border-subtle);
  background: var(--bs-danger-bg-subtle);
  color: var(--bs-danger-text-emphasis);
}

.sim-link {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
  color: var(--sl-jade-deep);
  font-size: 0.85rem;
  font-weight: 700;
  text-decoration: none;
  transition:
    background 0.2s ease,
    transform 0.2s ease;
}

.sim-link:hover,
.sim-link:focus-visible {
  background: var(--sl-jade-soft);
  transform: translateX(2px);
}

.remind {
  flex-basis: 100%;
  padding: 0.5rem 0.75rem;
  border-left: 4px solid var(--bs-danger);
  border-radius: 0.25rem;
  background: var(--bs-danger-bg-subtle);
  color: var(--bs-danger-text-emphasis);
  font-weight: 600;
}
</style>
