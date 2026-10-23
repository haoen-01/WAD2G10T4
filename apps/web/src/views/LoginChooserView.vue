<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import type { ViewMode } from '@/lib/view-mode';

/** `/login`: who is signing in? Each choice opens that view's own sign-in page. */
const route = useRoute();

// A `?next=` from a guarded link is passed along; the sign-in page decides whether to use it.
const query = computed(() => (route.query.next ? { next: route.query.next } : {}));

const CHOICES: { audience: ViewMode; title: string; text: string; icon: IconName }[] = [
  {
    audience: 'family',
    title: 'I’m family',
    text: 'See how she is doing, share the calendar and arrange who goes along.',
    icon: 'users',
  },
  {
    audience: 'senior',
    title: 'I’m the senior',
    text: 'See your day: how active you have been, a suggestion and what is planned today.',
    icon: 'person',
  },
];
</script>

<template>
  <div class="chooser">
    <header class="mb-4">
      <h1>Welcome to Care+.</h1>
      <p class="text-body-secondary mt-2 mb-0">Who is signing in?</p>
    </header>

    <div class="row g-4">
      <div v-for="choice in CHOICES" :key="choice.audience" class="col-md-6">
        <RouterLink
          class="choice sl-panel h-100"
          :to="{ name: 'login-as', params: { audience: choice.audience }, query }"
          :data-testid="`choose-${choice.audience}`"
        >
          <span class="choice-icon" aria-hidden="true"><Icon :name="choice.icon" /></span>
          <span class="d-block h3 mb-2">{{ choice.title }}</span>
          <span class="d-block text-body-secondary">{{ choice.text }}</span>
        </RouterLink>
      </div>
    </div>

    <div class="new-here sl-panel mt-4 d-flex flex-wrap align-items-center gap-3">
      <span class="me-auto fs-5">New to Care+? Make an account first.</span>
      <RouterLink class="btn btn-primary btn-lg" :to="{ name: 'signup' }" data-testid="signup-link">
        Create an account
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.chooser {
  max-width: 50rem;
  margin: 0 auto;
}

.chooser h1 {
  font-size: clamp(2rem, 5vw, 2.8rem);
  font-weight: 800;
}

.choice {
  display: block;
  color: var(--sl-ink);
  text-decoration: none;
  transition:
    border-color 0.15s ease,
    transform 0.15s ease;
}

.choice:hover,
.choice:focus-visible {
  border-color: var(--sl-jade);
  transform: translateY(-2px);
}

.choice-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 3.5rem;
  height: 3.5rem;
  margin-bottom: 1rem;
  border-radius: 50%;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}

.choice-icon .sl-icon {
  width: 1.75rem;
  height: 1.75rem;
}
</style>
