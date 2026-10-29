<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { useWalk } from '@/composables/useWalk';
import { STATE_WORDS } from '@/lib/walk';

/** On Home, under her watch: "Walking near the pond · See live", while she shares her walk. */
const walk = useWalk();

const out = computed(
  () => walk.latest.value !== null && !['waiting', 'home'].includes(walk.state.value),
);
</script>

<template>
  <RouterLink
    v-if="walk.sharing.value"
    class="walk-link"
    :class="{ 'is-out': out }"
    to="/walk"
    data-testid="home-walk-link"
  >
    <Icon name="walk" />
    <template v-if="out">
      <span>{{ STATE_WORDS[walk.state.value] }} near {{ walk.near.value }}</span>
      <span class="fw-bold">See live</span>
    </template>
    <span v-else>See her walks</span>
    <Icon name="chevron-right" />
  </RouterLink>
</template>

<style scoped>
.walk-link {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 2.75rem;
  padding: 0.35rem 0.85rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
  background: var(--sl-surface);
  color: var(--sl-jade-deep);
  font-size: 0.95rem;
  font-weight: 650;
  text-decoration: none;
}

.walk-link.is-out {
  border-color: transparent;
  background: var(--sl-jade-soft);
}

.walk-link:hover {
  text-decoration: underline;
}
</style>
