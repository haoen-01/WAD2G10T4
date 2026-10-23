<script setup lang="ts">
import { useRouteA11y } from '@/composables/useRouteA11y';

// Replaces the route announcer the previous framework injected: a polite, visually hidden live
// region that says where a screen-reader user landed after a client-side navigation.
const { message } = useRouteA11y();
</script>

<template>
  <div class="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
    {{ message }}
  </div>
</template>
