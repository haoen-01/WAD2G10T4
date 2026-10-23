<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';

/** A PIN shown large enough to read across a table, as "123 456", with a countdown to its expiry. */
const props = defineProps<{ pin: string; expiresAt: string; testid?: string }>();

// The code's lifetime comes from the API's `expires_at` alone: nothing here assumes how long a
// code lasts.

/** Whole seconds from `now` (ms since the epoch) until `expiresAt` (an ISO time); never below 0. */
function secondsUntil(expiresAt: string, now: number): number {
  const end = Date.parse(expiresAt);
  if (Number.isNaN(end)) return 0;
  // Rounded down, so a fresh code shows its full time (15:00, not 15:01) and 0 means it is over.
  return Math.max(0, Math.floor((end - now) / 1000));
}

/** "4:59", "1:02:03" for a code that lasts hours, or "Code expired" once it reaches 0. */
function formatCountdown(seconds: number): string {
  const total = Math.floor(seconds);
  if (!Number.isFinite(total) || total <= 0) return 'Code expired';
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
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
const expired = computed(() => remaining.value === 0);
const expiryText = computed(() =>
  expired.value ? formatCountdown(0) : `Expires in ${formatCountdown(remaining.value)}`,
);
const announcement = computed(() => countdownAnnouncement(remaining.value));
</script>

<template>
  <div class="pin-display">
    <p
      class="pin-digits mb-1"
      :class="{ 'pin-expired': expired }"
      :data-testid="testid"
      :aria-label="`PIN ${pin.split('').join(' ')}`"
    >
      {{ spaced }}
    </p>
    <!-- The visible countdown is not live: the region below speaks only at a minute left and at 0. -->
    <p class="d-flex align-items-center gap-2 fw-semibold mb-0 tabular">
      <Icon name="clock" />{{ expiryText }}
    </p>
    <p class="visually-hidden" aria-live="polite">{{ announcement }}</p>
  </div>
</template>

<style scoped>
.pin-display {
  padding: 1rem 1.25rem;
  border-radius: var(--sl-radius);
  background: var(--sl-jade-soft);
}

.pin-digits {
  color: var(--sl-jade-deep);
  font-size: clamp(2.2rem, 8vw, 3rem);
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.12em;
}

/* An expired code is struck through, and the line below says so in words. */
.pin-expired {
  text-decoration: line-through;
}
</style>
