<script setup lang="ts">
import { motion } from 'motion-v';

import PinDisplay from '@/components/family/PinDisplay.vue';
import { useReducedMotion } from '@/composables/useReducedMotion';
import { DURATION, EASE, SPRING } from '@/lib/motion';

/**
 * The invite PIN as a card that settles into place with a soft ring around it. All the digits are
 * ordinary text from the first render (inside PinDisplay, which the senior screen also uses and
 * which stays free of motion); the ring is decoration and is left out with reduced motion.
 * Family screens only. Give it a `key` that changes with the PIN so a new code plays it again.
 */
defineProps<{ pin: string; expiresAt: string; testid?: string }>();
const reduced = useReducedMotion();
</script>

<template>
  <motion.div
    class="pin-card"
    :initial="reduced ? false : { scale: 0.94 }"
    :animate="{ scale: 1 }"
    :transition="SPRING"
  >
    <motion.span
      v-if="!reduced"
      class="pin-ring"
      aria-hidden="true"
      :initial="{ opacity: 0.7, scale: 1 }"
      :animate="{ opacity: 0, scale: 1.08 }"
      :transition="{ duration: DURATION.count, ease: [...EASE.out] }"
    />
    <PinDisplay :pin="pin" :expires-at="expiresAt" :testid="testid" />
  </motion.div>
</template>

<style scoped>
.pin-card {
  position: relative;
}

/* Decoration: a ring that fades outwards once. It never takes a click. */
.pin-ring {
  position: absolute;
  inset: 0;
  border: 2px solid var(--sl-jade);
  border-radius: var(--sl-radius);
  pointer-events: none;
}
</style>
