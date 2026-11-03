<script setup lang="ts">
import { computed } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import type { FamilyMember } from '@/lib/family';

const props = defineProps<{
  member: FamilyMember;
  isCurrent: boolean;
  helpingCount: number;
  /** The demo (sign-in off) only: switch to being this member. */
  canSwitch?: boolean;
}>();
defineEmits<{ use: [] }>();

const helping = computed(() =>
  props.helpingCount === 0
    ? 'Not helping yet'
    : `Helping with ${props.helpingCount} ${props.helpingCount === 1 ? 'visit' : 'visits'}`,
);
</script>

<template>
  <div class="card member h-100" :class="{ current: isCurrent }">
    <div class="card-body d-flex flex-wrap align-items-center gap-2 p-2 px-3">
      <MemberAvatar :name="member.name" :colour="member.colour" size="sm" :current="isCurrent" />
      <div class="me-auto">
        <h3 class="h6 mb-0">
          {{ member.name }}
          <StatusBadge v-if="isCurrent" label="You" tone="primary" />
        </h3>
        <span class="member-load small">{{ member.relationship }} · {{ helping }}</span>
      </div>
      <button
        v-if="canSwitch && !isCurrent"
        type="button"
        class="btn btn-sm btn-outline-primary"
        @click="$emit('use')"
      >
        I’m {{ member.name }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.member {
  transition:
    border-color 0.15s ease,
    transform 0.15s var(--sl-ease);
}

.member:hover {
  transform: translateY(-2px);
}

.member.current {
  border: 2px solid var(--sl-ink);
}

.member-load {
  color: var(--sl-ink-soft);
}
</style>
