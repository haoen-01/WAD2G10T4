<script setup lang="ts">
import { computed } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import { helperLoad, loadWarning, needingHelp } from '@/lib/coverage';
import type { Appointment, Assignment, FamilyMember } from '@/lib/family';

/**
 * Who is carrying the care over the coming weeks, as one bar per person and one for what nobody has
 * taken. It says so in words when one person has most of it, which is the quiet problem in many
 * families: the same daughter takes every visit because nobody else noticed.
 */
const props = defineProps<{
  members: FamilyMember[];
  assignments: Assignment[];
  /** The appointments being shared out (the coming weeks). */
  appointments: Appointment[];
  currentMemberId: string | null;
}>();

const loads = computed(() => helperLoad(props.members, props.assignments, props.appointments));
const open = computed(() => needingHelp(props.appointments, props.assignments).length);
const warning = computed(() => loadWarning(loads.value));
const widest = computed(() => Math.max(1, open.value, ...loads.value.map((load) => load.count)));
const width = (count: number) => `${(count / widest.value) * 100}%`;
</script>

<template>
  <div>
    <ul class="share">
      <li v-for="load in loads" :key="load.member.id">
        <span class="who">
          <MemberAvatar
            :name="load.member.name"
            :colour="load.member.colour"
            size="sm"
            :current="load.member.id === currentMemberId"
          />
          <span class="fw-semibold">{{ load.member.name }}</span>
        </span>
        <span class="track" aria-hidden="true">
          <span class="fill" :style="{ width: width(load.count) }"></span>
        </span>
        <span class="count tabular">{{ load.count }}</span>
      </li>
      <li class="open-row">
        <span class="who">
          <span class="open-mark" aria-hidden="true"></span>
          <span class="fw-semibold">Not taken yet</span>
        </span>
        <span class="track" aria-hidden="true">
          <span class="fill" :style="{ width: width(open) }"></span>
        </span>
        <span class="count tabular">{{ open }}</span>
      </li>
    </ul>
    <p v-if="warning" class="warn mb-0">{{ warning }}</p>
  </div>
</template>

<style scoped>
.share {
  display: grid;
  gap: 0.6rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.share li {
  display: grid;
  grid-template-columns: 9rem minmax(0, 1fr) 2rem;
  gap: 0.75rem;
  align-items: center;
}

.who {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.track {
  height: 0.85rem;
  border-radius: 999px;
  background: var(--sl-mist);
  overflow: hidden;
}

.fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--sl-jade);
  transition: width 0.5s var(--sl-ease);
}

.open-row .fill {
  background: var(--sl-coral);
}

.open-mark {
  width: 1.9rem;
  height: 1.9rem;
  border: 3px solid var(--sl-coral);
  border-top-color: transparent;
  border-radius: 50%;
  transform: rotate(45deg);
}

.count {
  font-weight: 800;
  text-align: right;
}

.warn {
  margin-top: 1rem;
  padding: 0.6rem 0.9rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-sun-soft);
  font-weight: 600;
}

@media (max-width: 575.98px) {
  .share li {
    grid-template-columns: 7rem minmax(0, 1fr) 1.5rem;
  }
}
</style>
