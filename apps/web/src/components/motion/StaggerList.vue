<script setup lang="ts" generic="T">
import { motion } from 'motion-v';
import { watch } from 'vue';

import { useReducedMotion } from '@/composables/useReducedMotion';
import { DURATION, EASE, durationFor, enterFrom, staggerDelay } from '@/lib/motion';

/**
 * A list whose entries rise in one after another. Entries already on screen when a batch arrives
 * wait their turn only once: a later single entry (a new check-in at the top) arrives straight
 * away. With reduced motion entries fade in without moving or waiting.
 *
 *   <StaggerList :items="entries" :item-key="(e) => e.id"><template #item="{ item }">…</template>
 */
const props = defineProps<{ items: readonly T[]; itemKey: (item: T) => string }>();
defineSlots<{ item(props: { item: T; index: number }): unknown }>();

const reduced = useReducedMotion();
const delays = new Map<string, number>();

// Runs before each render: gives every new key its place in the batch it arrived with.
watch(
  () => props.items.map((item) => props.itemKey(item)),
  (keys) => {
    let position = 0;
    for (const key of keys) {
      if (!delays.has(key)) delays.set(key, staggerDelay(position++, reduced.value));
    }
  },
  { immediate: true, flush: 'sync' },
);
</script>

<template>
  <ul class="list-unstyled mb-0">
    <motion.li
      v-for="(item, index) in items"
      :key="itemKey(item)"
      :initial="enterFrom(reduced)"
      :animate="{ opacity: 1, y: 0 }"
      :transition="{
        duration: durationFor(DURATION.slow, reduced),
        delay: delays.get(itemKey(item)) ?? 0,
        ease: [...EASE.ease],
      }"
    >
      <slot name="item" :item="item" :index="index" />
    </motion.li>
  </ul>
</template>
