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
  <a v-if="members.length" class="cluster" href="#family-group" :aria-label="label">
    <motion.span
      v-for="(member, index) in shown"
      :key="member.id"
      class="cluster-item"
      :initial="reduced ? { opacity: 0 } : { opacity: 0, scale: 0.6 }"
      :animate="{ opacity: 1, scale: 1 }"
      :transition="reduced ? { duration: 0 } : { ...SPRING, delay: staggerDelay(index) }"
    >
      <MemberAvatar
        :name="member.name"
        :colour="member.colour"
        size="md"
        :current="member.id === currentId"
      />
    </motion.span>
    <motion.span
      v-if="extra"
      class="cluster-item cluster-more"
      aria-hidden="true"
      :initial="{ opacity: 0 }"
      :animate="{ opacity: 1 }"
      :transition="{ duration: reduced ? 0 : DURATION.base }"
    >
      +{{ extra }}
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
  box-shadow: 0 0 0 2px var(--bs-body-bg);
}

.cluster-more {
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  background: var(--sl-surface);
  color: var(--sl-ink);
  border: 1px solid var(--sl-line);
  font-size: 0.85rem;
  font-weight: 700;
}
</style>
