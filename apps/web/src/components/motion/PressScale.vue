<script setup lang="ts">
import { motion } from 'motion-v';

import { useReducedMotion } from '@/composables/useReducedMotion';
import { DURATION } from '@/lib/motion';

/**
 * A wrapper that dips slightly while its button is pressed, so a tap feels answered. The button
 * inside keeps all its own behaviour. Does nothing with reduced motion.
 */
const reduced = useReducedMotion();
</script>

<template>
  <motion.div
    :while-press="reduced ? undefined : { scale: 0.96 }"
    :transition="{ duration: DURATION.fast }"
  >
    <slot />
  </motion.div>
</template>
