<script setup lang="ts">
import { computed } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { HELPING_BADGE, statusBadge } from '@/lib/family';
import type { FamilyMember, MemberStatus } from '@/lib/family';

const props = defineProps<{
  members: FamilyMember[];
  /** Who has taken this appointment. */
  helperIds: string[];
  /** What each person has said about it, by member id. Missing means they have not said. */
  statuses: Record<string, MemberStatus>;
  currentMemberId: string | null;
}>();

// Most useful first: who is helping, then who could, then who has not said, then who cannot.
const ORDER = { helping: 0, available: 1, unknown: 2, unavailable: 3 } as const;

const rows = computed(() =>
  props.members
    .map((member) => {
      const helping = props.helperIds.includes(member.id);
      const status = props.statuses[member.id] ?? 'unknown';
      return {
        member,
        badge: helping ? HELPING_BADGE : statusBadge(status),
        rank: ORDER[helping ? 'helping' : status],
      };
    })
    .sort((a, b) => a.rank - b.rank),
);
</script>

<template>
  <p v-if="rows.length === 0" class="text-body-secondary mb-0">
    Nobody has joined the family group yet.
  </p>
  <ul v-else class="list-group">
    <li
      v-for="row in rows"
      :key="row.member.id"
      class="list-group-item d-flex align-items-center gap-3 py-3"
    >
      <MemberAvatar
        :name="row.member.name"
        :colour="row.member.colour"
        :current="row.member.id === currentMemberId"
      />
      <span class="me-auto">
        <span class="fw-semibold">{{ row.member.name }}</span>
        <span v-if="row.member.id === currentMemberId" class="text-body-secondary"> (you)</span>
        <span class="d-block small text-body-secondary">{{ row.member.relationship }}</span>
      </span>
      <StatusBadge v-if="row.badge" v-bind="row.badge" />
      <span v-else class="small text-body-secondary">Has not replied yet</span>
    </li>
  </ul>
</template>
