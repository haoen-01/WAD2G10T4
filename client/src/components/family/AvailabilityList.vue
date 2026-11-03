<script lang="ts">
import { defineComponent, type PropType } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import {
  availabilityBadge,
  describeWindow,
  type AvailabilityEntry,
  type FamilyMember,
} from '@/lib/family';
import { formatIsoDay } from '@/lib/format-date';
import { relativeDay } from '@/lib/today';

/**
 * "Family availability": every shared time, grouped under one heading per day. A person can
 * remove their own times; that emits `remove` with the entry, and the page asks to confirm with
 * an Undo.
 */
export default defineComponent({
  name: 'AvailabilityList',
  components: { MemberAvatar, StatusBadge },

  props: {
    /** The shared times, already in date and time order. */
    windows: { type: Array as PropType<AvailabilityEntry[]>, required: true },
    members: { type: Array as PropType<FamilyMember[]>, required: true },
    currentMemberId: { type: String as PropType<string | null>, default: null },
    today: { type: String, required: true },
  },

  emits: {
    remove: (entry: AvailabilityEntry) => Boolean(entry),
  },

  computed: {
    byDay(): { date: string; entries: AvailabilityEntry[] }[] {
      const groups: { date: string; entries: AvailabilityEntry[] }[] = [];
      for (const entry of this.windows) {
        const last = groups.at(-1);
        if (last && last.date === entry.date) last.entries.push(entry);
        else groups.push({ date: entry.date, entries: [entry] });
      }
      return groups;
    },
  },

  methods: {
    availabilityBadge,
    describeWindow,
    formatIsoDay,
    relativeDay,
    memberOf(id: string): FamilyMember | undefined {
      return this.members.find((member) => member.id === id);
    },
  },
});
</script>

<template>
  <section aria-labelledby="everyone-heading">
    <h2 id="everyone-heading" class="h4 mb-3">Family availability</h2>
    <p v-if="windows.length === 0" class="empty">Nobody has shared their availability yet.</p>
    <div v-else class="days">
      <div v-for="group in byDay" :key="group.date" class="day">
        <h3 class="day-head">
          <span>{{ formatIsoDay(group.date, { style: 'long' }) }}</span>
          <span class="day-rel">{{ relativeDay(group.date, today) }}</span>
        </h3>
        <ul class="list-group">
          <template v-for="entry in group.entries" :key="entry.id">
            <li
              v-if="memberOf(entry.memberId)"
              class="list-group-item d-flex flex-wrap align-items-center gap-3 py-3"
            >
              <MemberAvatar
                :name="memberOf(entry.memberId)!.name"
                :colour="memberOf(entry.memberId)!.colour"
                :current="entry.memberId === currentMemberId"
              />
              <span class="me-auto">
                <span class="fw-semibold">{{ describeWindow(entry) }}</span>
                <span class="d-block small text-body-secondary">
                  {{ memberOf(entry.memberId)!.name
                  }}<template v-if="entry.memberId === currentMemberId"> (you)</template>
                </span>
              </span>
              <StatusBadge v-bind="availabilityBadge(entry.status)" />
              <button
                v-if="entry.memberId === currentMemberId"
                type="button"
                class="btn btn-outline-secondary"
                :aria-label="`Remove ${formatIsoDay(entry.date)}, ${describeWindow(entry)}`"
                @click="$emit('remove', entry)"
              >
                Remove
              </button>
            </li>
          </template>
        </ul>
      </div>
    </div>
  </section>
</template>

<style scoped>
.days {
  display: grid;
  gap: 1.25rem;
}

.day-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.5rem;
  font-size: 1.05rem;
}

.day-rel {
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
  font-weight: 600;
}

.empty {
  padding: 1rem 1.25rem;
  border: 2px dashed var(--sl-line);
  border-radius: var(--sl-radius-sm);
  color: var(--sl-ink-soft);
}
</style>
