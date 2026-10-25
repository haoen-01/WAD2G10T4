<script setup lang="ts">
import { animate } from 'motion-v';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { useReducedMotion } from '@/composables/useReducedMotion';
import { DURATION, EASE, durationFor } from '@/lib/motion';

/**
 * A whole number that counts up to its value. The counting digits are decoration (aria-hidden); the
 * real value is in visually hidden text, so a screen reader reads it once and never hears the count.
 * With reduced motion the final value shows at once.
 */
const props = defineProps<{ value: number }>();

const reduced = useReducedMotion();
const shown = ref(reduced.value ? props.value : 0);
let controls: { stop: () => void } | null = null;

function run(to: number) {
  controls?.stop();
  if (reduced.value) {
    shown.value = to;
    return;
  }
  controls = animate(shown.value, to, {
    duration: durationFor(DURATION.count, false),
    ease: [...EASE.ease],
    onUpdate: (latest: number) => {
      shown.value = Math.round(latest);
    },
  });
}

onMounted(() => run(props.value));
watch(() => props.value, run);
watch(reduced, (now) => {
  if (now) run(props.value);
});
onBeforeUnmount(() => controls?.stop());
</script>

<template>
  <span class="number-ticker">
    <span class="visually-hidden">{{ value }}</span>
    <span class="tabular" aria-hidden="true" data-testid="ticker-digits">{{ shown }}</span>
  </span>
</template>
