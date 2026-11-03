<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { expiryLabel } from '@/lib/countdown';

/**
 * A PIN shown large enough to read across a table, as "123 456", with a countdown to its expiry.
 * While `pending`, the same panel holds the place with dots, so the page does not move when the PIN
 * arrives.
 */
const props = defineProps<{ pin: string; expiresAt: string; testid?: string; pending?: boolean }>();

// The code's lifetime comes from the API's `expires_at` alone: nothing here assumes how long a
// code lasts.

/** Whole seconds from `now` (ms since the epoch) until `expiresAt` (an ISO time); never below 0. */
function secondsUntil(expiresAt: string, now: number): number {
  const end = Date.parse(expiresAt);
  if (Number.isNaN(end)) return 0;
  // Rounded down, so a fresh code shows its full time (15:00, not 15:01) and 0 means it is over.
  return Math.max(0, Math.floor((end - now) / 1000));
}

/**
 * What a screen reader is told, which changes only at the moments that matter (a minute left, then
 * expired), so a polite live region holding it never reads out every second.
 */
function countdownAnnouncement(seconds: number): string {
  if (seconds <= 0) return 'Code expired.';
  if (seconds <= 60) return 'Less than a minute left on the code.';
  return '';
}

// Ticks once a second. The time left always comes from `expiresAt`, so a new code restarts it.
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now();
  }, 1000);
});
onUnmounted(() => clearInterval(timer));

const spaced = computed(() => `${props.pin.slice(0, 3)} ${props.pin.slice(3)}`);
const remaining = computed(() => secondsUntil(props.expiresAt, now.value));
const expired = computed(() => !props.pending && remaining.value === 0);
const expiryText = computed(() => expiryLabel(remaining.value));
const announcement = computed(() => (props.pending ? '' : countdownAnnouncement(remaining.value)));
</script>

<template>
  <div class="pin-display">
    <!-- Same line box as the digits below: the dots are the digits' own size and never wrap. -->
    <p v-if="pending" class="pin-digits mb-1" aria-hidden="true">••• •••</p>
    <p
      v-else
      class="pin-digits mb-1"
      :class="{ 'pin-expired': expired }"
      :data-testid="testid"
      :aria-label="`PIN ${pin.split('').join(' ')}`"
    >
      {{ spaced }}
    </p>
    <!-- The visible countdown is not live: the region below speaks only at a minute left and at 0. -->
    <p class="d-flex align-items-start gap-2 fw-semibold mb-0 tabular">
      <Icon name="clock" class="pin-clock flex-shrink-0" />
      <!-- Both wordings share one grid cell, so this line is as tall whichever is showing. -->
      <span class="pin-line">
        <span :class="{ invisible: !pending }">Getting your code...</span>
        <span :class="{ invisible: pending }">{{ expiryText }}</span>
      </span>
    </p>
    <p class="visually-hidden" aria-live="polite">{{ announcement }}</p>
  </div>
</template>

<style scoped>
.pin-display {
  padding: 1rem 1.25rem;
  border-radius: var(--sl-radius);
  background: var(--sl-jade-soft);
  /* The digits below size themselves from this panel's width. */
  container-type: inline-size;
}

/* Sits level with the first line when the words wrap. */
.pin-clock {
  margin-top: 0.25em;
}

.pin-line {
  display: grid;
}

.pin-line > * {
  grid-area: 1 / 1;
}

.pin-digits {
  color: var(--sl-jade-deep);
  /* Six digits stay one unit. They grow with the zoom until the line fills the panel: 20cqi is the
     largest size at which "123 456" and its letter spacing still fit, so it only holds them back
     where the panel is truly short of room. */
  font-size: min(clamp(2.2rem, 8vw, 3rem), 20cqi);
  line-height: 1.2;
  white-space: nowrap;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.12em;
}

/* An expired code is struck through, and the line below says so in words. */
.pin-expired {
  text-decoration: line-through;
}
</style>
