<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import LandingStory from '@/components/landing/LandingStory.vue';
import AuthShell from '@/components/ui/AuthShell.vue';
import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import type { ViewMode } from '@/lib/view-mode';

/**
 * `/login`: first the landing story (what Care+ is, scrolled through), then who is signing in.
 * Each choice opens that view's own sign-in page.
 */
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
  <LandingStory />

  <div id="sign-in" class="sign-in" tabindex="-1">
    <AuthShell
      :level="2"
      title="Start caring together."
      lead="The family and the senior each have their own way in. Who is signing in?"
      width="wide"
    >
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
        <RouterLink
          class="btn btn-primary btn-lg"
          :to="{ name: 'signup' }"
          data-testid="signup-link"
        >
          Create an account
        </RouterLink>
      </div>
    </AuthShell>
  </div>
</template>

<style scoped>
/*
 * The sign-in section fills the whole screen, so arriving at it ("Get started", or scrolling to
 * the end of the story) shows only this one background, with the choices in the middle.
 * - It runs up behind the see-through header (the top padding keeps the content below it), so
 *   the header never shows the dark story behind it.
 * - The negative `scroll-margin-top` undoes the page's own gap above a jump target
 *   (`scroll-padding-top` in theme.css), so the section's top lands exactly at the top of the
 *   screen.
 */
.sign-in {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 100dvh;
  padding: calc(var(--sl-pinned-height, 0px) + 2rem) 0 2.5rem;
  scroll-margin-top: calc(-1 * (var(--sl-pinned-height, 0px) + 0.75rem));
  /* A gentle snap: stop scrolling just short of it and the page settles here. */
  scroll-snap-align: start;
}

.sign-in > * {
  width: 100%;
}

/* It takes focus only so "Get started" can hand the keyboard over; it is not a control. */
.sign-in:focus {
  outline: none;
}

/* Only on this page, and only "proximity": the snap acts near the sign-in section, nowhere else.
   No snap with reduced motion, so the page never moves by itself. */
@media (prefers-reduced-motion: no-preference) {
  :global(html:has(.sign-in)) {
    scroll-snap-type: y proximity;
  }
}

.new-here-text {
  text-wrap: balance;
}
</style>
