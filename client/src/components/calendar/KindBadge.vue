<script setup lang="ts">
import { KIND_LABELS, type AppointmentKind } from '@/lib/family';

// The kind is always words as well as a colour: colour alone is not a signal.
defineProps<{ kind: AppointmentKind }>();
</script>

<template>
  <span class="badge rounded-pill kind-badge" :class="`kind-${kind}`">{{ KIND_LABELS[kind] }}</span>
</template>
