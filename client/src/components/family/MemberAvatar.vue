<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import { avatarAlt, avatarPhoto, initialsOf } from '@/lib/avatar';
import { AVATAR_COLOURS } from '@/lib/family';

/**
 * A person's round avatar: their photo, or their initials on one of six colours.
 *
 * `photo` is optional and nothing passes one yet: the API has no photo field. When it gains one
 * (a future `photo_url` on members and seniors), pass that URL here. A photo that fails to load
 * falls back to the initials. `colour` set to `'senior'` uses the senior's own warm colour.
 */
const props = withDefaults(
  defineProps<{
    name: string;
    colour: number | 'senior';
    size?: 'sm' | 'md' | 'lg' | 'xl';
    current?: boolean;
    photo?: string | null;
    /** True when the name is not written beside the avatar, so the avatar itself names the person. */
    labelled?: boolean;
  }>(),
  { size: 'md', current: false, photo: null, labelled: false },
);

const failed = ref(false);
watch(
  () => props.photo,
  () => (failed.value = false),
);

const initials = computed(() => initialsOf(props.name));
const src = computed(() => avatarPhoto(props.photo, failed.value));
const colourClass = computed(() =>
  props.colour === 'senior' ? 'avatar-senior' : `avatar-${props.colour % AVATAR_COLOURS}`,
);
</script>

<template>
  <!-- Decoration unless `labelled`: the person's name is normally written next to it. -->
  <span
    class="avatar"
    :class="[colourClass, `avatar-${size}`, { 'avatar-current': current, 'avatar-photo': src }]"
    :role="labelled && !src ? 'img' : undefined"
    :aria-label="labelled && !src ? name : undefined"
    :aria-hidden="labelled ? undefined : 'true'"
    data-testid="member-avatar"
  >
    <img
      v-if="src"
      class="avatar-img"
      :src="src"
      :alt="labelled ? avatarAlt(name) : ''"
      data-testid="avatar-photo"
      @error="failed = true"
    />
    <template v-else>{{ initials }}</template>
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
  overflow: hidden;
  border-radius: 50%;
  color: var(--sl-avatar-on, #fff);
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

/* The hero: big enough to read as a person, not an icon. */
.avatar-xl {
  width: 5.5rem;
  height: 5.5rem;
  font-size: 1.9rem;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* The person using the screen wears a ring: they are "in the loop". */
.avatar-current {
  box-shadow:
    0 0 0 3px var(--sl-surface),
    0 0 0 5px var(--sl-sun);
}

.avatar-0 {
  background: var(--sl-avatar-0, #0b684f);
}

.avatar-1 {
  background: var(--sl-avatar-1, #1f5f8b);
}

.avatar-2 {
  background: var(--sl-avatar-2, #7a4b94);
}

.avatar-3 {
  background: var(--sl-avatar-3, #8a5a00);
}

.avatar-4 {
  background: var(--sl-avatar-4, #a1324a);
}

.avatar-5 {
  background: var(--sl-avatar-5, #3f5f6f);
}

/* Each colour falls back to the six the theme has always used (white text passes AA on each),
   for a theme that does not define the avatar tokens. */

/* The senior: the hero's own avatar (jade with white initials in light, ink with sun initials in
   dark) and a light ring that sets it off the sun field (no family member's colour). */
.avatar-senior {
  background: var(--sl-avatar-senior, #0b684f);
  color: var(--sl-avatar-senior-on, #fff);
  box-shadow: 0 0 0 4px var(--sl-hero-avatar-ring, transparent);
}

.avatar-photo {
  background: var(--sl-skeleton);
}
</style>
