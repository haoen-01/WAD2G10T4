<script setup lang="ts">
import { computed } from 'vue';

import { AVATAR_COLOURS } from '@/lib/family';

const props = withDefaults(
  defineProps<{ name: string; colour: number; size?: 'sm' | 'md' | 'lg'; current?: boolean }>(),
  { size: 'md', current: false },
);

const initials = computed(
  () =>
    props.name
      .split(' ')
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join('')
      .toUpperCase() || '?',
);
</script>

<template>
  <!-- Decoration only: the person's name is always written next to it. -->
  <span
    class="avatar"
    :class="[`avatar-${colour % AVATAR_COLOURS}`, `avatar-${size}`, { 'avatar-current': current }]"
    aria-hidden="true"
  >
    {{ initials }}
  </span>
</template>

<style scoped>
.avatar {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 50%;
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.avatar-sm {
  width: 1.9rem;
  height: 1.9rem;
  font-size: 0.75rem;
}

.avatar-lg {
  width: 3.5rem;
  height: 3.5rem;
  font-size: 1.2rem;
}

/* The person using the screen wears a ring: they are "in the loop". */
.avatar-current {
  box-shadow:
    0 0 0 3px var(--sl-surface),
    0 0 0 5px var(--sl-sun);
}

/* Six colours, each with white text that passes AA. */
.avatar-0 {
  background: #0b684f;
}

.avatar-1 {
  background: #1f5f8b;
}

.avatar-2 {
  background: #7a4b94;
}

.avatar-3 {
  background: #8a5a00;
}

.avatar-4 {
  background: #a1324a;
}

.avatar-5 {
  background: #3f5f6f;
}
</style>
