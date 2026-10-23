<script lang="ts">
import { defineComponent, type PropType } from 'vue';

import AppointmentCard from '@/components/calendar/AppointmentCard.vue';
import TaskForm from '@/components/home/TaskForm.vue';
import type { Appointment, FamilyMember } from '@/lib/family';
import { formatClockTime, formatIsoDay } from '@/lib/format-date';
import { TASK_REPEAT_LABELS } from '@/lib/tasks';
import type { TaskInput, TaskOccurrence } from '@/lib/tasks';

/**
 * The chosen day: its date, the public holiday if there is one, and what is planned. Choosing an
 * appointment emits `select` with it, and the calendar opens its details.
 */
export default defineComponent({
  name: 'DayAgenda',
  components: { AppointmentCard, TaskForm },

  props: {
    /** YYYY-MM-DD */
    day: { type: String, required: true },
    appointments: { type: Array as PropType<Appointment[]>, required: true },
    holiday: { type: String as PropType<string | null>, default: null },
    /** Whether a filter is on, so an empty day can say why. */
    filtersOn: { type: Boolean, default: false },
    helpersOf: {
      type: Function as PropType<(appointment: Appointment) => FamilyMember[]>,
      required: true,
    },
    /** The day's tasks from the Tasks panel; ticking one here ticks it there too. */
    tasks: { type: Array as PropType<TaskOccurrence[]>, default: () => [] },
    /** Today, so a task on a later day cannot be ticked off yet. */
    today: { type: String, required: true },
    /** Whether the person can add appointments (a member of the family group). */
    canAdd: { type: Boolean, default: false },
  },

  emits: {
    select: (appointment: Appointment) => Boolean(appointment),
    'toggle-task': (task: TaskOccurrence) => Boolean(task),
    'save-task': (taskId: string, input: TaskInput) => Boolean(taskId && input),
    'delete-task': (taskId: string) => Boolean(taskId),
    /** "+ Add" on this day. */
    add: (day: string) => Boolean(day),
  },

  data: () => ({ editingId: null as string | null }),

  watch: {
    // Another day: close any open form.
    day() {
      this.editingId = null;
    },
  },

  methods: {
    formatClockTime,
    formatIsoDay,
    repeatLabel: (task: TaskOccurrence) => TASK_REPEAT_LABELS[task.repeat],
    saveTask(taskId: string, input: TaskInput) {
      this.editingId = null;
      this.$emit('save-task', taskId, input);
    },
    deleteTask(taskId: string) {
      this.editingId = null;
      this.$emit('delete-task', taskId);
    },
    helperNames(appointment: Appointment): string[] {
      return this.helpersOf(appointment).map((member) => member.name);
    },
  },
});
</script>

<template>
  <section class="mb-4" aria-labelledby="day-heading">
    <div class="d-flex align-items-center justify-content-between gap-2 mb-2">
      <h2 id="day-heading" class="h4 mb-0">
        <span v-if="day === today" class="today-tag">Today</span>
        {{ formatIsoDay(day, { style: 'long' }) }}
      </h2>
      <button
        v-if="canAdd && day >= today"
        type="button"
        class="btn btn-sm btn-outline-primary"
        :aria-label="`Add on ${formatIsoDay(day, { style: 'long' })}`"
        @click="$emit('add', day)"
      >
        + Add
      </button>
    </div>
    <p v-if="holiday" class="day-holiday">
      Public holiday: <strong>{{ holiday }}</strong>
    </p>
    <div v-if="appointments.length" class="cards">
      <AppointmentCard
        v-for="appointment in appointments"
        :key="appointment.id"
        :appointment="appointment"
        :helper-names="helperNames(appointment)"
        :helpers="helpersOf(appointment)"
        @select="$emit('select', appointment)"
      />
    </div>
    <p v-else-if="!tasks.length" class="empty">
      <template v-if="filtersOn">Nothing matches the filters.</template>
      <template v-else>Nothing planned.</template>
    </p>

    <div v-if="tasks.length" class="mt-3" data-testid="day-tasks">
      <h3 class="h5 mb-2">Tasks</h3>
      <ul class="list-unstyled mb-1 task-cards">
        <li v-for="task in tasks" :key="task.task_id" class="day-task">
          <TaskForm
            v-if="editingId === task.task_id"
            :task="task"
            :day="day"
            @save="saveTask(task.task_id, $event)"
            @delete="deleteTask(task.task_id)"
            @cancel="editingId = null"
          />
          <div v-else class="d-flex gap-2 align-items-start">
            <label class="d-flex gap-2 align-items-start flex-grow-1">
              <input
                type="checkbox"
                class="form-check-input day-task-check"
                :checked="task.completed"
                :disabled="day > today"
                @change="$emit('toggle-task', task)"
              />
              <span>
                <span
                  class="d-block fw-semibold"
                  :class="{ 'text-decoration-line-through': task.completed }"
                  >{{ task.title }}</span
                >
                <span class="d-block sl-note">
                  {{ formatClockTime(task.time) }} · {{ repeatLabel(task) }}
                </span>
              </span>
            </label>
            <button
              type="button"
              class="btn btn-sm btn-outline-secondary"
              :aria-label="`Edit ${task.title}`"
              @click="editingId = task.task_id"
            >
              Edit
            </button>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
/* A full-width row: appointments and tasks sit side by side, as many as fit. */
.cards,
.task-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
  gap: 0.75rem;
}

.cards :deep(.appointment) {
  height: 100%;
  border: 1px solid var(--sl-line);
  border-left: 4px solid var(--kind);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
}

.task-cards .day-task {
  margin-bottom: 0;
}

.today-tag {
  display: inline-block;
  margin-right: 0.4rem;
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  background: var(--sl-jade);
  color: #fff;
  font-size: 0.75em;
  vertical-align: 0.15em;
}

.day-holiday {
  padding: 0.4rem 0.75rem;
  border-left: 4px solid var(--sl-sun);
  background: var(--sl-sun-soft);
}

.day-task {
  padding: 0.6rem 0.75rem;
  border-left: 3px dashed var(--kind, #46605a);
  border-radius: 0.3rem;
  background: var(--sl-surface);
  margin-bottom: 0.4rem;
  overflow-wrap: anywhere;
}

.day-task label {
  cursor: pointer;
}

.day-task-check {
  flex: none;
  width: 1.4rem;
  height: 1.4rem;
  margin-top: 0.1rem;
}

.empty {
  padding: 1rem 1.25rem;
  border: 2px dashed var(--sl-line);
  border-radius: var(--sl-radius-sm);
  color: var(--sl-ink-soft);
}
</style>
