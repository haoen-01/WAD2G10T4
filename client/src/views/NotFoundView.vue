<script setup lang="ts">
import { RouterLink } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
</script>

<template>
  <div class="missing">
    <!-- An open loop: the one place in the app where the ring does not close. -->
    <svg class="missing-loop" viewBox="0 0 120 120" aria-hidden="true">
      <circle
        cx="60"
        cy="60"
        r="44"
        fill="none"
        stroke="var(--sl-line)"
        stroke-width="14"
        stroke-linecap="round"
        stroke-dasharray="200 77"
        transform="rotate(20 60 60)"
      />
    </svg>
    <h1>Page not found</h1>
    <p class="text-body-secondary mt-3 mb-4">
      That page does not exist. It may have moved, or the link may be old.
    </p>
    <div class="d-flex flex-wrap justify-content-center gap-2">
      <RouterLink class="btn btn-primary btn-lg sl-cta" to="/">
        <Icon name="home" class="me-2" />Back to Overview
      </RouterLink>
      <RouterLink class="btn btn-outline-primary btn-lg" to="/calendar">
        <Icon name="calendar" class="me-2" />Open the calendar
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.missing {
  max-width: 32rem;
  margin: 2rem auto;
  text-align: center;
}

.missing-loop {
  width: 8rem;
  height: 8rem;
  margin-bottom: 1.5rem;
}

.missing h1 {
  font-size: clamp(2rem, 5vw, 2.8rem);
  font-weight: 800;
}
</style>
