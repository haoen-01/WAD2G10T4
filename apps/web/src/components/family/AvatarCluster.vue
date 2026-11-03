<script setup lang="ts">
import { motion } from 'motion-v';
import { computed } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import { useReducedMotion } from '@/composables/useReducedMotion';
import type { FamilyMember } from '@/lib/family';
import { DURATION, SPRING, staggerDelay } from '@/lib/motion';

/**
 * The care group as a row of overlapping avatars, with "+N" when there are more than `max`. The
 * whole cluster is one image to a screen reader, named with everyone in it (the avatars alone
 * are decoration). Family screens only: it uses motion, which the senior screen must not load.
 * Pointing at it or focusing it spreads the avatars apart (CSS, 180 ms) so each face reads on its
 * own; each one also carries its name as a tooltip.
 */
const props = withDefaults(
  defineProps<{ members: readonly FamilyMember[]; currentId?: string | null; max?: number }>(),
  { currentId: null, max: 4 },
);

const reduced = useReducedMotion();
const shown = computed(() => props.members.slice(0, props.max));
const extra = computed(() => Math.max(0, props.members.length - props.max));
const label = computed(() => {
  const names = props.members.map((member) =>
    member.id === props.currentId ? `${member.name} (you)` : member.name,
  );
  return names.length
    ? `Care group, ${names.length} people: ${names.join(', ')}`
    : 'No members yet';
});
</script>

<template>
  <a v-if="members.length" class="cluster" href="#family-group" :aria-label="label" :title="label">
    <motion.span
      v-for="(member, index) in shown"
      :key="member.id"
      class="cluster-item"
      :style="{ '--i': index }"
      :title="member.id === currentId ? `${member.name} (you)` : member.name"
      :initial="reduced ? { opacity: 0 } : { opacity: 0, scale: 0.6 }"
      :animate="{ opacity: 1, scale: 1 }"
      :transition="reduced ? { duration: 0 } : { ...SPRING, delay: staggerDelay(index) }"
    >
      <span class="cluster-face">
        <MemberAvatar
          :name="member.name"
          :colour="member.colour"
          size="md"
          :current="member.id === currentId"
        />
      </span>
    </motion.span>
    <motion.span
      v-if="extra"
      class="cluster-item cluster-more"
      :style="{ '--i': shown.length }"
      aria-hidden="true"
      :initial="{ opacity: 0 }"
      :animate="{ opacity: 1 }"
      :transition="{ duration: reduced ? 0 : DURATION.base }"
    >
      <span class="cluster-face">+{{ extra }}</span>
    </motion.span>
  </a>
</template>

<style scoped>
.cluster {
  display: inline-flex;
  border-radius: 999px;
  text-decoration: none;
  align-items: center;
  padding-left: 0.6rem;
}

/* Each avatar sits over the one before it, edged in the page colour so they read apart. */
.cluster-item {
  display: inline-flex;
  margin-left: -0.6rem;
  border-radius: 50%;
}

/* The spread: each face moves right by its place in the row, so the overlap opens up. It moves an
   inner span, because the outer one carries Motion's own entrance transform. */
.cluster-face {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  box-shadow: 0 0 0 2px var(--bs-body-bg);
  transition: transform var(--sl-dur-hover) var(--sl-ease-out);
}

.cluster:focus-visible .cluster-face {
  transform: translateX(calc(var(--i) * 0.45rem));
}

@media (hover: hover) and (pointer: fine) {
  .cluster:hover .cluster-face {
    transform: translateX(calc(var(--i) * 0.45rem));
  }
}

@media (prefers-reduced-motion: reduce) {
  .cluster-face {
    transform: none !important;
  }
}

.cluster-more .cluster-face {
  width: 2.5rem;
  height: 2.5rem;
  background: var(--sl-surface);
  color: var(--sl-ink);
  border: 1px solid var(--sl-line);
  font-size: 0.85rem;
  font-weight: 700;
}
</style>
