<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue';
import { RouterLink } from 'vue-router';

import TaskForm from '@/components/home/TaskForm.vue';
import Icon from '@/components/ui/Icon.vue';
import { useNow } from '@/composables/useNow';
import { useTasks } from '@/composables/useTasks';
import { showToast } from '@/composables/useToast';
import { addDays, timeToMinutes, todayIso } from '@/lib/calendar';
import { formatClockTime, formatIsoDay } from '@/lib/format-date';
import { capRows } from '@/lib/home';
import type { TaskInput, TaskOccurrence, TaskSchedule } from '@/lib/tasks';
import { minutesOf, nextTask, untilWords } from '@/lib/today';

/**
 * "Today's tasks" on Home: today's medicine and reminders to tick off, how many are done and what
 * is next. At most five rows show; "See all" opens the day on the calendar. Adding, editing and
 * other days wait behind "Manage tasks", so Home stays a list to act on rather than a tool.
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
/** "Manage tasks": the day stepper, Add task and Edit. Closing it goes back to today. */
const managing = ref(false);
const manageButton = ref<HTMLButtonElement | null>(null);
function startManaging(addNew = false) {
  managing.value = true;
  if (addNew) openForm();
}
async function stopManaging() {
  managing.value = false;
  editing.value = null;
  day.value = today();
  await nextTick();
  manageButton.value?.focus();
}
const doneCount = computed(() => dayTasks.value.filter((task) => task.completed).length);
const rows = computed(() => capRows(dayTasks.value));

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
/** The tick box for a task, so Undo can put focus back on it. */
function checkFor(taskId: string) {
  return document.getElementById(`${id}-task-${taskId}`);
}
async function toggle(task: TaskOccurrence) {
  notice.value = '';
  const onDay = day.value;
  const completed = !task.completed;
  const saved = await tasks.setCompleted(task.task_id, onDay, completed);
  // Ticking off is easy to do by mistake on a phone, so it can be taken back from the toast.
  if (!saved || !completed) return;
  showToast(`Ticked off: ${task.title}.`, {
    actionLabel: 'Undo',
    action: async () => {
      if (await tasks.setCompleted(task.task_id, onDay, false)) {
        await nextTick();
        checkFor(task.task_id)?.focus();
      }
    },
  });
}
async function remove() {
  const task = editing.value;
  if (task && task !== 'new' && (await tasks.remove(task.task_id))) done('Deleted.');
}
</script>

<template>
  <section class="sl-panel task-panel" :aria-labelledby="`${id}-heading`" data-testid="task-panel">
    <div class="d-flex align-items-center gap-3 mb-3">
      <div class="flex-grow-1 min-w-0">
        <h3 :id="`${id}-heading`" class="h4 mb-0">
          {{ isToday ? 'Today’s tasks' : 'Tasks' }}
        </h3>
        <p v-if="dayTasks.length" class="mb-0 text-body-secondary" aria-live="polite">
          <template v-if="doneCount === dayTasks.length">All done.</template>
          <template v-else>{{ doneCount }} of {{ dayTasks.length }} done</template>
        </p>
      </div>
      <button
        v-if="canManage && !managing"
        ref="manageButton"
        type="button"
        class="btn btn-outline-primary flex-none"
        data-testid="manage-tasks"
        @click="startManaging()"
      >
        Manage tasks
      </button>
      <template v-else-if="canManage">
        <button
          :type="editing === 'new' ? 'submit' : 'button'"
          :form="editing === 'new' ? `${id}-new-task` : undefined"
          class="btn btn-primary flex-none"
          data-testid="add-task"
          @click="editing === 'new' ? undefined : openForm()"
        >
          Add task
        </button>
        <button
          type="button"
          class="btn btn-quiet flex-none"
          data-testid="manage-done"
          @click="stopManaging"
        >
          Done
        </button>
      </template>
    </div>

    <!-- Another day: step through days instead of typing a date (while managing). -->
    <div v-if="managing" class="day-nav mb-3" role="group" aria-label="Day">
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
      v-if="editing && canManage && managing"
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
    <div v-else-if="!dayTasks.length" class="tasks-empty" data-testid="tasks-empty">
      <p class="mb-1 fw-semibold">
        {{ isToday ? 'No tasks today.' : `No tasks on ${formatIsoDay(day)}.` }}
      </p>
      <p v-if="canManage" class="mb-0 text-body-secondary">
        Add a reminder for {{ isToday ? 'today' : 'this day' }}, such as a call or a medicine time.
        Everyone in the family group sees it.
        <button
          v-if="!managing"
          type="button"
          class="btn btn-link p-0 align-baseline"
          @click="startManaging(true)"
        >
          Add a task
        </button>
      </p>
    </div>
    <ul v-else class="tasks">
      <li
        v-for="task in rows.shown"
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
          <span class="task-box" aria-hidden="true">
            <!-- The tick draws itself in when the task is done (CSS stroke, 220 ms). -->
            <svg class="task-tick" viewBox="0 0 24 24" focusable="false">
              <path d="M5 12.5l4.5 4.5L19 7.5" pathLength="1" />
            </svg>
          </span>
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
          v-if="canManage && managing"
          type="button"
          class="btn btn-sm btn-quiet task-edit"
          :aria-label="`Edit ${task.title}`"
          @click="openForm(task)"
        >
          Edit
        </button>
      </li>
    </ul>

    <RouterLink
      v-if="rows.hidden"
      class="see-all"
      :to="{ path: '/calendar', query: { day } }"
      data-testid="tasks-see-all"
    >
      See all {{ dayTasks.length }} on the calendar<Icon name="chevron-right" />
    </RouterLink>

    <p class="sl-note mt-3 mb-0">Saved for the whole family group, and shown on the calendar.</p>
  </section>
</template>

<style scoped>
.min-w-0 {
  min-width: 0;
}

.flex-none {
  flex: none;
}

.tasks-empty {
  padding: 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--bs-tertiary-bg);
}

.see-all {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  min-height: 2.75rem;
  margin-top: 0.5rem;
  font-weight: 700;
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
  margin: 0;
  padding: 0;
  list-style: none;
}

/* One task: the whole row ticks it; Edit (while managing) sits at the right edge. Rows are divided
   by a rule, like the other lists on Home. */
.task-row {
  position: relative;
  display: flex;
  align-items: center;
  border-top: 1px solid var(--sl-line);
  transition: background-color var(--sl-dur-base) ease;
}

.task-row:first-child {
  border-top: 0;
}

@media (hover: hover) and (pointer: fine) {
  .task-row:hover {
    background: var(--bs-tertiary-bg);
  }
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
  padding: 0.6rem 0.25rem;
  cursor: pointer;
}

.task-check:disabled + .task-label {
  cursor: default;
}

.task-check:focus-visible + .task-label {
  outline: 3px solid var(--sl-focus);
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
  color: var(--sl-jade-on);
  transition:
    background-color var(--sl-dur-base) ease,
    border-color var(--sl-dur-base) ease;
}

/* The tick is a stroke that is drawn in: hidden (dash offset 1) until the task is done. A CSS
   transition, so a quick tick and untick reverses smoothly instead of restarting. */
.task-tick {
  width: 1.2rem;
  height: 1.2rem;
  fill: none;
  stroke: currentcolor;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.task-tick path {
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  transition: stroke-dashoffset 0.22s var(--sl-ease-out);
}

.done .task-tick path {
  stroke-dashoffset: 0;
}

.task-text {
  transition: color var(--sl-dur-base) ease;
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
  background: color-mix(in srgb, var(--sl-jade-soft) 40%, var(--sl-surface));
}

.done .task-box {
  border-color: var(--sl-jade);
  background: var(--sl-jade);
}

.done .task-text {
  color: var(--sl-ink-soft);
  text-decoration: line-through;
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
