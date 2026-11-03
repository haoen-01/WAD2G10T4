<script setup lang="ts">
/**
 * The shared frame of the sign-in and onboarding screens: the page heading and
 * a lead line, then the page's own content. Presentational and motion-free, so these screens stay
 * light. Panels placed in the slot (`.sl-panel`) get the frosted card look used on the family
 * screens.
 */
defineProps<{
  title: string;
  lead?: string;
  width?: 'narrow' | 'medium' | 'wide';
  /** 2 when something above already has the page's h1 (the landing story on `/login`). */
  level?: 1 | 2;
}>();
</script>

<template>
  <div class="auth-shell" :class="`auth-${width ?? 'medium'}`">
    <header class="auth-head">
      <component :is="level === 2 ? 'h2' : 'h1'" class="auth-title">{{ title }}</component>
      <p v-if="lead" class="auth-lead">{{ lead }}</p>
    </header>
    <slot />
  </div>
</template>

<style scoped>
.auth-shell {
  margin: 0 auto;
  padding-top: 0.5rem;
}

.auth-narrow {
  max-width: 34rem;
}

.auth-medium {
  max-width: 40rem;
}

.auth-wide {
  max-width: 50rem;
}

.auth-head {
  margin-bottom: 1.5rem;
}

@media (max-width: 575.98px) {
  .auth-shell {
    padding-top: 0;
  }

  .auth-head {
    margin-bottom: 1rem;
  }

  .auth-lead {
    font-size: 1.0625rem;
  }
}

.auth-title {
  margin: 0;
  font-family: 'Bricolage Grotesque', var(--bs-body-font-family);
  font-size: clamp(1.75rem, 6vw, 2.6rem);
  font-weight: 800;
  letter-spacing: -0.01em;
  text-wrap: balance;
}

.auth-lead {
  margin: 0.5rem 0 0;
  font-size: 1.125rem;
  color: var(--sl-ink-soft);
  max-width: 36rem;
}

/* Frosted card: the same glass tokens as the nav, with the soft lift of a resting card. */
.auth-shell :slotted(.sl-panel) {
  background: var(--sl-glass-bg);
  border-color: var(--sl-glass-border);
  -webkit-backdrop-filter: var(--sl-glass-filter);
  backdrop-filter: var(--sl-glass-filter);
  box-shadow: var(--sl-elev-2);
}

/* Dark: the hairline edge is easier to see on the deep page. */
:root[data-bs-theme='dark'] .auth-shell :slotted(.sl-panel) {
  border-color: rgb(255 255 255 / 22%);
}
</style>

<!-- Not scoped: the choice's icon and text sit inside the slotted link or button. -->
<style>
/*
 * A big choice (who is signing in, join or create a group): one card, icon on the left of the text
 * on a phone and above it from 576px. A link or a button; both get the same look and a clear focus.
 */
.auth-shell .auth-choice {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 0 1rem;
  width: 100%;
  min-height: 3.5rem;
  padding: 1rem;
  color: var(--sl-ink);
  text-align: left;
  text-decoration: none;
  transition: border-color var(--sl-dur-base) ease;
}

.auth-shell .auth-choice:hover,
.auth-shell .auth-choice:focus-visible {
  border-color: var(--sl-jade);
}

.auth-shell .auth-choice:focus-visible {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
}

.auth-shell .choice-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 50%;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-size: 1.4rem;
}

.auth-shell .choice-title {
  display: block;
  font-size: 1.25rem;
  font-weight: 800;
  line-height: 1.25;
}

.auth-shell .choice-text {
  display: block;
  margin-top: 0.15rem;
  color: var(--sl-ink-soft);
}

@media (min-width: 576px) {
  .auth-shell .auth-choice {
    grid-template-columns: 1fr;
    gap: 0.75rem 0;
    align-content: start;
    padding: 1.5rem;
  }

  .auth-shell .choice-icon {
    width: 3.5rem;
    height: 3.5rem;
    font-size: 1.75rem;
  }

  .auth-shell .choice-title {
    font-size: 1.4rem;
  }
}
</style>
