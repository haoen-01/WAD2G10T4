<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink } from 'vue-router';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import Icon from '@/components/ui/Icon.vue';
import { addDays } from '@/lib/calendar';
import type { Appointment, FamilyMember } from '@/lib/family';
import { WEEKDAYS_SHORT, formatClockTime, formatIsoDay, parseIsoDay } from '@/lib/format-date';
import type { TaskOccurrence } from '@/lib/tasks';
import { timeRange } from '@/lib/today';

/**
 * Seven days from today, each a link into the calendar on that day. Each appointment shows its start
 * and end time and who is going; one with nobody going stands out (a coral dashed edge, a warning
 * icon and the words "No one going"), so it never relies on colour alone. Seven columns on a wide screen, a list of rows
 * on a phone (so nothing scrolls sideways).
 */
const props = defineProps<{
  today: string;
  appointments: Appointment[];
  helpersOf: (appointmentId: string) => FamilyMember[];
  /** Tasks from the Tasks panel by date, listed after each day's appointments. */
  tasksByDay?: Record<string, TaskOccurrence[]>;
}>();

const days = computed(() =>
  Array.from({ length: 7 }, (_, offset) => {
    const iso = addDays(props.today, offset);
    const parts = parseIsoDay(iso);
    return {
      iso,
      weekday: offset === 0 ? 'Today' : parts ? WEEKDAYS_SHORT[parts.weekday] : '',
      day: parts?.day ?? '',
      items: props.appointments.filter((appointment) => appointment.date === iso),
      tasks: props.tasksByDay?.[iso] ?? [],
    };
  }),
);

function linkLabel(iso: string, count: number, open: number, taskCount = 0) {
  const what =
    count === 0
      ? taskCount
        ? 'no appointments'
        : 'nothing planned'
      : `${count} ${count === 1 ? 'appointment' : 'appointments'}`;
  const need = open ? `, ${open} with no one going yet` : '';
  const tasks = taskCount ? `, ${taskCount} ${taskCount === 1 ? 'task' : 'tasks'}` : '';
  return `${formatIsoDay(iso, { style: 'long' })}: ${what}${need}${tasks}. Open in the calendar.`;
}
</script>

<template>
  <!-- Bootstrap row-cols: one day per row on phones, two from small screens, and all seven in a
       line from xl up (Bootstrap stops at six, so the seven is set below). -->
  <ol class="week row row-cols-1 row-cols-sm-2 g-2 list-unstyled mb-0">
    <li v-for="day in days" :key="day.iso" class="col">
      <RouterLink
        class="week-day"
        :class="{ today: day.iso === today, empty: !day.items.length && !day.tasks.length }"
        :to="{ path: '/calendar', query: { day: day.iso } }"
        :aria-label="
          linkLabel(
            day.iso,
            day.items.length,
            day.items.filter((item) => helpersOf(item.id).length === 0).length,
            day.tasks.length,
          )
        "
      >
        <span class="week-date" aria-hidden="true">
          <span class="week-weekday">{{ day.weekday }}</span>
          <span class="week-num">{{ day.day }}</span>
        </span>
        <span class="week-items" aria-hidden="true">
          <span v-if="!day.items.length && !day.tasks.length" class="week-none">Free day</span>
          <span
            v-for="item in day.items"
            :key="item.id"
            class="week-item"
            :class="[`kind-${item.kind}`, { open: !helpersOf(item.id).length }]"
          >
            <span class="week-time">{{ timeRange(item.start, item.end) }}</span>
            <span class="week-title">{{ item.title }}</span>
            <span v-if="helpersOf(item.id).length" class="week-helpers">
              <MemberAvatar
                v-for="helper in helpersOf(item.id)"
                :key="helper.id"
                :name="helper.name"
                :colour="helper.colour"
                size="sm"
              />
            </span>
            <span v-else class="week-need"><Icon name="alert" class="me-1" />No one going</span>
          </span>
          <span v-if="day.tasks.length" class="week-count d-md-none">
            {{ day.tasks.length }} {{ day.tasks.length === 1 ? 'task' : 'tasks' }}
          </span>
          <span
            v-for="task in day.tasks"
            :key="`task-${task.task_id}`"
            class="week-item week-task kind-task d-none d-md-flex"
            :class="{ done: task.completed }"
          >
            <span class="week-time">{{ formatClockTime(task.time) }} · Task</span>
            <span class="week-title">{{ task.completed ? '✓' : '☐' }} {{ task.title }}</span>
          </span>
        </span>
      </RouterLink>
    </li>
  </ol>
</template>

<style scoped>
@media (min-width: 1200px) {
  .week > li {
    width: calc(100% / 7);
  }
}

.week-day {
  display: flex;
  gap: 1rem;
  height: 100%;
  padding: 0.85rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  color: var(--sl-ink);
  text-decoration: none;
  transition:
    border-color 0.15s ease,
    transform 0.15s var(--sl-ease);
}

.week-day:hover {
  border-color: var(--sl-jade);
  transform: translateY(-2px);
}

.week-day.today {
  border: 2px solid var(--sl-ink);
}

.week-day.empty {
  background: transparent;
}

@media (min-width: 1200px) {
  .week-day {
    flex-direction: column;
    gap: 0.6rem;
    min-height: 11rem;
  }
}

.week-date {
  display: flex;
  flex: none;
  flex-direction: column;
  width: 3rem;
}

.week-weekday {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
}

.week-num {
  font-size: 1.6rem;
  font-weight: 800;
  line-height: 1;
}

.week-items {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.45rem;
  min-width: 0;
}

.week-none {
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
}

.week-item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.4rem 0.5rem;
  border-left: 4px solid var(--kind);
  border-radius: 0.4rem;
  background: color-mix(in srgb, var(--kind) 9%, var(--sl-surface));
  font-size: 0.875rem;
  line-height: 1.25;
}

.week-task {
  border-left-style: dashed;
}

.week-count {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
}

/* Nobody going: a coral dashed edge on the three other sides, keeping the kind's colour on the left. */
.week-item.open {
  border: 2px dashed var(--sl-coral);
  border-left: 4px solid var(--kind);
  background: var(--sl-coral-soft);
}

.week-task.done .week-title {
  color: var(--sl-ink-soft);
  text-decoration: line-through;
}

.week-time {
  color: var(--sl-ink-soft);
  font-size: 0.8rem;
  font-weight: 700;
}

.week-title {
  font-weight: 700;
  overflow-wrap: anywhere;
}

.week-helpers {
  display: flex;
  gap: 0.2rem;
  margin-top: 0.15rem;
}

.week-need {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  margin-top: 0.2rem;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  background: var(--sl-coral);
  color: var(--sl-surface);
  font-size: 0.8rem;
  font-weight: 800;
}
</style>
