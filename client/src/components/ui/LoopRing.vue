<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

/**
 * The Care+ ring: a loop that closes as something gets done. It draws itself from empty when it
 * first appears, then follows its value. The ring is decoration; whatever goes in the slot (and the
 * words around it) carries the meaning, so the SVG is hidden from screen readers.
 */
const props = withDefaults(
  defineProps<{
    /** 0 to 1. Anything above 1 closes the loop; the slot can say by how much. */
    value: number;
    size?: number;
    stroke?: number;
    /** A CSS colour for the arc. */
    color?: string;
    track?: string;
  }>(),
  { size: 120, stroke: 12, color: 'var(--sl-jade)', track: 'var(--sl-jade-soft)' },
);

const radius = computed(() => (props.size - props.stroke) / 2);
const circumference = computed(() => 2 * Math.PI * radius.value);

// Start empty and close to the value on the next frame, so the loop is seen closing.
const drawn = ref(false);
onMounted(() => {
  window.requestAnimationFrame(() => {
    drawn.value = true;
  });
});

const offset = computed(() => {
  const value = drawn.value ? Math.max(0, Math.min(1, props.value)) : 0;
  return circumference.value * (1 - value);
});
</script>

<template>
  <div class="loop-ring" :style="{ width: `${size}px`, height: `${size}px` }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" aria-hidden="true">
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="track"
        :stroke-width="stroke"
      />
      <circle
        class="loop-ring-arc"
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="color"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="offset"
        :transform="`rotate(-90 ${size / 2} ${size / 2})`"
      />
    </svg>
    <div class="loop-ring-center">
      <slot></slot>
    </div>
  </div>
</template>

<style scoped>
.loop-ring {
  position: relative;
  flex: none;
}

.loop-ring svg {
  display: block;
}

.loop-ring-arc {
  transition: stroke-dashoffset 1.2s var(--sl-ease);
}

.loop-ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  line-height: 1.1;
}
</style>
