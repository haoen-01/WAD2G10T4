<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue';
import { RouterLink } from 'vue-router';

import TaskForm from '@/components/home/TaskForm.vue';
import Icon from '@/components/ui/Icon.vue';
import LoopRing from '@/components/ui/LoopRing.vue';
import { useNow } from '@/composables/useNow';
import { useTasks } from '@/composables/useTasks';
import { addDays, timeToMinutes, todayIso } from '@/lib/calendar';
import { formatClockTime, formatIsoDay } from '@/lib/format-date';
import type { TaskInput, TaskOccurrence, TaskSchedule } from '@/lib/tasks';
import { minutesOf, nextTask, untilWords } from '@/lib/today';

/**
 * "Today's tasks": medicine and reminders that tick off, a ring for how many are done and a line
 * for what is next. Family members in the group add, edit and delete them; anyone ticks them off.
 * Tasks are kept by the family group in the API (`useTasks`) and also show on the calendar.
 */
const props = defineProps<{ canManage: boolean }>();
const id = useId();
const tasks = useTasks();
const canManage = computed(() => props.canManage && tasks.canManage());
const now = useNow();
// The same "today" as the calendar, so a task ticked off here is the one shown there.
const today = todayIso;
const day = ref(today());
const isToday = computed(() => day.value === today());
const notice = ref('');
/** The day the last saved task starts on, so the notice can link to it in the calendar. */
const savedDay = ref<string | null>(null);
/** The open form: `'new'`, a task being edited, or nothing. */
const editing = ref<TaskSchedule | 'new' | null>(null);
const dayTasks = computed(() => tasks.tasksOn(day.value));
const doneCount = computed(() => dayTasks.value.filter((task) => task.completed).length);

// "Next": only for today, the earliest one not done that is still to come (or overdue).
const next = computed(() => {
  if (!isToday.value) return null;
  const items = dayTasks.value.map((task) => ({ ...task, id: task.task_id }));
  const done = new Set(items.filter((task) => task.completed).map((task) => task.id));
  return nextTask(items, minutesOf(now.value), done);
});
const nextWhen = computed(() => {
  if (!next.value) return '';
  if (next.value.overdue) return 'earlier today';
  return untilWords(timeToMinutes(next.value.task.time) - minutesOf(now.value));
});

watch(day, () => {
  editing.value = null;
  notice.value = '';
  savedDay.value = null;
});

function openForm(task?: TaskSchedule) {
  editing.value = task ?? 'new';
  notice.value = '';
  savedDay.value = null;
}

function done(message: string, onDay: string | null = null) {
  editing.value = null;
  notice.value = message;
  savedDay.value = onDay;
}
async function save(input: TaskInput) {
  const task = editing.value;
  const saved =
    task && task !== 'new' ? await tasks.update(task.task_id, input) : await tasks.add(input);
  // Not saved: the form stays open with what was typed, and a message says why.
  if (saved) done(task === 'new' ? 'Added to the calendar.' : 'Saved.', input.start_date);
}
function toggle(task: TaskOccurrence) {
  void tasks.setCompleted(task.task_id, day.value, !task.completed);
  notice.value = '';
}
async function remove() {
  const task = editing.value;
  if (task && task !== 'new' && (await tasks.remove(task.task_id))) done('Deleted.');
}
</script>

<template>
  <section class="sl-panel task-panel" :aria-labelledby="`${id}-heading`" data-testid="task-panel">
    <div class="d-flex align-items-center gap-3 mb-3">
      <LoopRing
        :value="dayTasks.length ? doneCount / dayTasks.length : 0"
        :size="64"
        :stroke="8"
        color="var(--sl-sun)"
        track="var(--sl-sun-soft)"
      >
        <span class="fw-bold tabular">{{ doneCount }}/{{ dayTasks.length }}</span>
      </LoopRing>
      <div class="flex-grow-1 min-w-0">
        <h2 :id="`${id}-heading`" class="h4 mb-0">
          {{ isToday ? 'Today’s tasks' : 'Tasks' }}
        </h2>
        <p class="mb-0 text-body-secondary" aria-live="polite">
          <template v-if="dayTasks.length && doneCount === dayTasks.length">All done.</template>
          <template v-else>{{ doneCount }} of {{ dayTasks.length }} done</template>
        </p>
      </div>
      <button
        v-if="canManage"
        :type="editing === 'new' ? 'submit' : 'button'"
        :form="editing === 'new' ? `${id}-new-task` : undefined"
        class="btn btn-primary flex-none sl-cur-add"
        data-testid="add-task"
        @click="editing === 'new' ? undefined : openForm()"
      >
        Add task
      </button>
    </div>

    <!-- Another day: step through days instead of typing a date. -->
    <div class="day-nav mb-3" role="group" aria-label="Day">
      <button
        type="button"
        class="btn btn-sm btn-quiet"
        aria-label="Previous day"
        @click="day = addDays(day, -1)"
      >
        <Icon name="chevron-left" />
      </button>
      <span class="fw-semibold tabular">{{ isToday ? 'Today' : formatIsoDay(day) }}</span>
      <button
        type="button"
        class="btn btn-sm btn-quiet"
        aria-label="Next day"
        @click="day = addDays(day, 1)"
      >
        <Icon name="chevron-right" />
      </button>
      <button v-if="!isToday" type="button" class="btn btn-sm btn-link" @click="day = today()">
        Back to today
      </button>
    </div>

    <p v-if="notice" role="status" class="text-success small mb-2">
      {{ notice }}
      <RouterLink v-if="savedDay" :to="{ path: '/calendar', query: { day: savedDay } }">
        View
      </RouterLink>
    </p>

    <TaskForm
      v-if="editing && canManage"
      :key="editing === 'new' ? 'new' : editing.task_id"
      :form-id="editing === 'new' ? `${id}-new-task` : undefined"
      class="task-form mb-3"
      :task="editing === 'new' ? null : editing"
      :day="day"
      @save="save"
      @delete="remove"
      @cancel="editing = null"
    />

    <p v-if="next" class="next-up">
      <Icon name="clock" />
      <span>
        Next: <strong>{{ next.task.title }}</strong> at {{ formatClockTime(next.task.time) }},
        {{ nextWhen }}
      </span>
    </p>

    <p
      v-if="tasks.error.value && !tasks.loaded.value"
      class="text-body-secondary mb-0"
      role="alert"
    >
      Tasks could not be loaded.
      <button type="button" class="btn btn-link p-0 align-baseline" @click="tasks.refresh()">
        Try again
      </button>
    </p>
    <p v-else-if="!tasks.loaded.value" class="text-body-secondary mb-0">Loading tasks…</p>
    <p v-else-if="!dayTasks.length" class="text-body-secondary mb-0">No tasks.</p>
    <ul v-else class="tasks">
      <li
        v-for="task in dayTasks"
        :key="task.task_id"
        class="task-row"
        :class="{ done: task.completed }"
      >
        <input
          :id="`${id}-task-${task.task_id}`"
          class="task-check"
          type="checkbox"
          :checked="task.completed"
          :disabled="day > today()"
          @change="toggle(task)"
        />
        <label :for="`${id}-task-${task.task_id}`" class="task-label">
          <span class="task-box" aria-hidden="true"><Icon name="check" /></span>
          <span class="task-time tabular">{{ formatClockTime(task.time) }}</span>
          <span class="task-text">
            <span class="d-block">{{ task.title }}</span>
            <span v-if="task.kind === 'medicine' || task.notes" class="task-meta">
              <span v-if="task.kind === 'medicine'" class="task-kind">
                <Icon name="pill" />Medicine
              </span>
              <span v-if="task.notes">{{ task.notes }}</span>
            </span>
          </span>
        </label>
        <button
          v-if="canManage"
          type="button"
          class="btn btn-sm btn-quiet task-edit"
          :aria-label="`Edit ${task.title}`"
          @click="openForm(task)"
        >
          Edit
        </button>
      </li>
    </ul>

    <p class="sl-note mt-3 mb-0">Kept in this browser.</p>
  </section>
</template>

<style scoped>
.min-w-0 {
  min-width: 0;
}

.flex-none {
  flex: none;
}

.day-nav {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.task-form {
  padding: 1rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-mist);
}

.next-up {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-sun-soft);
}

.next-up .sl-icon {
  margin-top: 0.15rem;
}

.tasks {
  display: grid;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* One task: the whole box ticks it; Edit sits at the right edge. */
.task-row {
  position: relative;
  display: flex;
  align-items: center;
  border: 2px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease;
}

.task-row:hover {
  border-color: var(--sl-ink-soft);
}

.task-check {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.task-label {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 0.85rem;
  min-width: 0;
  min-height: 3.5rem;
  padding: 0.6rem 0.85rem;
  cursor: var(--sl-cur-tick);
}

.task-check:disabled + .task-label {
  cursor: default;
}

.task-check:focus-visible + .task-label {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
  border-radius: var(--sl-radius-sm);
}

.task-edit {
  flex: none;
  margin-right: 0.5rem;
}

.task-box {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border: 2px solid var(--sl-ink-soft);
  border-radius: 0.5rem;
  color: transparent;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    transform 0.2s var(--sl-ease);
}

.task-time {
  flex: none;
  min-width: 5.2rem;
  font-weight: 700;
  white-space: nowrap;
}

.task-text {
  flex: 1 1 8rem;
  min-width: 0;
  overflow-wrap: anywhere;
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 0.6rem;
  margin-top: 0.2rem;
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
}

.task-kind {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 0.3rem;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-size: 0.8rem;
  font-weight: 700;
}

.done {
  border-color: var(--sl-jade-soft);
  background: color-mix(in srgb, var(--sl-jade-soft) 40%, var(--sl-surface));
}

.done .task-box {
  border-color: var(--sl-jade);
  background: var(--sl-jade);
  color: #fff;
  animation: pop 0.3s var(--sl-ease);
}

.done .task-text {
  color: var(--sl-ink-soft);
  text-decoration: line-through;
}

@keyframes pop {
  50% {
    transform: scale(1.2);
  }
}

@media (max-width: 575.98px) {
  .task-label {
    flex-wrap: wrap;
  }

  .task-time {
    min-width: 4.6rem;
  }
}
</style>
