<script setup lang="ts">
import type { Tone } from '@/lib/labels';

// A status is always words as well as a colour: colour alone is not a signal.
defineProps<{ label: string; tone: Tone }>();
</script>

<template>
  <span class="badge rounded-pill" :class="`text-bg-${tone}`">{{ label }}</span>
</template>
