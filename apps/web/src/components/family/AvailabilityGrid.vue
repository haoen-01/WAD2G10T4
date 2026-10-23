<script setup lang="ts">
import { computed } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import { addDays } from '@/lib/calendar';
import { hasHelper } from '@/lib/coverage';
import type { Appointment, Assignment, AvailabilityEntry, FamilyMember } from '@/lib/family';
import { WEEKDAYS_SHORT, formatIsoDay, parseIsoDay } from '@/lib/format-date';

/**
 * The next fortnight at a glance: one row per person, one column per day, so a gap ("nobody is free
 * on Tuesday") is visible without reading a list. A table, because that is what it is. Every cell
 * says its state in words for screen readers and in a symbol on screen, never colour alone.
 *
 * What a cell shows, strongest first: helping with something that day; free (any "available"
 * window); not free (any "not available" window); otherwise not said.
 */
const props = defineProps<{
  members: FamilyMember[];
  availability: AvailabilityEntry[];
  assignments: Assignment[];
  appointments: Appointment[];
  today: string;
  currentMemberId: string | null;
}>();

type Cell = 'helping' | 'available' | 'unavailable' | 'unknown';
const WORDS: Record<Cell, string> = {
  helping: 'helping',
  available: 'free',
  unavailable: 'not free',
  unknown: 'has not said',
};
const SYMBOLS: Record<Cell, string> = {
  helping: '●',
  available: '✓',
  unavailable: '✕',
  unknown: '',
};

const days = computed(() =>
  Array.from({ length: 14 }, (_, offset) => {
    const iso = addDays(props.today, offset);
    const parts = parseIsoDay(iso);
    const planned = props.appointments.filter((appointment) => appointment.date === iso);
    return {
      iso,
      weekday: parts ? WEEKDAYS_SHORT[parts.weekday].slice(0, 2) : '',
      day: parts?.day ?? '',
      planned: planned.length,
      open: planned.filter((appointment) => !hasHelper(props.assignments, appointment.id)).length,
    };
  }),
);

function cellFor(memberId: string, iso: string): Cell {
  const helping = props.assignments.some(
    (assignment) =>
      assignment.memberId === memberId &&
      props.appointments.some((a) => a.id === assignment.appointmentId && a.date === iso),
  );
  if (helping) return 'helping';
  const mine = props.availability.filter(
    (entry) => entry.memberId === memberId && entry.date === iso,
  );
  if (mine.some((entry) => entry.status === 'available')) return 'available';
  if (mine.some((entry) => entry.status === 'unavailable')) return 'unavailable';
  return 'unknown';
}

const dayHeading = (day: { iso: string; planned: number; open: number }) => {
  const planned =
    day.planned === 0
      ? 'nothing planned'
      : `${day.planned} planned${day.open ? `, ${day.open} without a helper` : ''}`;
  return `${formatIsoDay(day.iso)}, ${planned}`;
};
</script>

<template>
  <div class="grid-wrap">
    <table class="avail">
      <caption class="visually-hidden">
        Who is free on each of the next 14 days
      </caption>
      <thead>
        <tr>
          <th scope="col"><span class="visually-hidden">Family member</span></th>
          <th v-for="day in days" :key="day.iso" scope="col" :class="{ today: day.iso === today }">
            <span aria-hidden="true">
              <span class="d-block wd">{{ day.weekday }}</span>
              <span class="d-block dn">{{ day.day }}</span>
              <span class="plan" :class="{ has: day.planned, open: day.open }"></span>
            </span>
            <span class="visually-hidden">{{ dayHeading(day) }}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="member in members" :key="member.id">
          <th scope="row">
            <span class="d-flex align-items-center gap-2">
              <MemberAvatar
                :name="member.name"
                :colour="member.colour"
                size="sm"
                :current="member.id === currentMemberId"
              />
              <span>{{ member.name }}</span>
            </span>
          </th>
          <td
            v-for="day in days"
            :key="day.iso"
            :class="['cell', `cell-${cellFor(member.id, day.iso)}`]"
          >
            <span aria-hidden="true">{{ SYMBOLS[cellFor(member.id, day.iso)] }}</span>
            <span class="visually-hidden">{{ WORDS[cellFor(member.id, day.iso)] }}</span>
          </td>
        </tr>
      </tbody>
    </table>

    <ul class="key" aria-hidden="true">
      <li><span class="cell cell-helping">●</span> Helping that day</li>
      <li><span class="cell cell-available">✓</span> Free</li>
      <li><span class="cell cell-unavailable">✕</span> Not free</li>
      <li><span class="plan has"></span> Something planned</li>
      <li><span class="plan has open"></span> Still needs a helper</li>
    </ul>
  </div>
</template>

<style scoped>
.grid-wrap {
  overflow-x: auto;
}

.avail {
  width: 100%;
  min-width: 33rem;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 2px;
}

.avail thead th {
  padding-bottom: 0.3rem;
  font-weight: 700;
  text-align: center;
  vertical-align: bottom;
}

.avail thead th:first-child {
  width: 6.75rem;
}

.avail thead th.today .dn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.7rem;
  height: 1.7rem;
  border-radius: 50%;
  background: var(--sl-jade);
  color: #fff;
}

.wd {
  color: var(--sl-ink-soft);
  font-size: 0.75rem;
}

.dn {
  margin: 0 auto;
  font-variant-numeric: tabular-nums;
}

.plan {
  display: block;
  width: 0.45rem;
  height: 0.45rem;
  margin: 0.25rem auto 0;
  border-radius: 50%;
}

.plan.has {
  background: var(--sl-ink-soft);
}

.plan.open {
  background: var(--sl-coral);
}

.avail tbody th {
  padding: 0 0.35rem 0 0.4rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell {
  height: 2.4rem;
  border-radius: 0.5rem;
  background: var(--sl-mist);
  color: var(--sl-ink-soft);
  font-weight: 800;
  text-align: center;
}

.cell-helping {
  background: var(--sl-jade);
  color: #fff;
}

.cell-available {
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}

.cell-unavailable {
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink-soft);
}

.key {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.25rem;
  margin: 0.85rem 0 0;
  padding: 0;
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
  list-style: none;
}

.key li {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.key .cell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  font-size: 0.8rem;
}

.key .plan {
  margin: 0;
}
</style>
