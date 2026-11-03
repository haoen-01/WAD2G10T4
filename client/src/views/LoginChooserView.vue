<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import AuthShell from '@/components/ui/AuthShell.vue';
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
  <AuthShell title="Welcome to Care+." lead="Who is signing in?" width="wide">
    <div class="row g-3 g-md-4">
      <div v-for="choice in CHOICES" :key="choice.audience" class="col-md-6">
        <RouterLink
          class="auth-choice sl-panel h-100"
          :to="{ name: 'login-as', params: { audience: choice.audience }, query }"
          :data-testid="`choose-${choice.audience}`"
        >
          <span class="choice-icon" aria-hidden="true"><Icon :name="choice.icon" /></span>
          <span>
            <span class="choice-title">{{ choice.title }}</span>
            <span class="choice-text">{{ choice.text }}</span>
          </span>
        </RouterLink>
      </div>
    </div>

    <div class="new-here sl-panel mt-3 mt-sm-4 d-flex flex-wrap align-items-center gap-3">
      <span class="new-here-text me-auto fs-5">New to Care+? Make an account first.</span>
      <RouterLink class="btn btn-primary btn-lg" :to="{ name: 'signup' }" data-testid="signup-link">
        Create an account
      </RouterLink>
    </div>
  </AuthShell>
</template>

<style scoped>
.new-here-text {
  text-wrap: balance;
}
</style>
