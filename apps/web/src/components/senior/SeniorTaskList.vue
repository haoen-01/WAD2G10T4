<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId } from 'vue';
import TaskForm from '@/components/home/TaskForm.vue';
import Icon from '@/components/ui/Icon.vue';
import { useTasks } from '@/composables/useTasks';
import { useNow } from '@/composables/useNow';
import { todayIso } from '@/lib/calendar';
import { formatClockTime } from '@/lib/format-date';
import type { TaskInput, TaskOccurrence } from '@/lib/tasks';
import { nextSeniorTask, sortSeniorTasks } from './senior-view.js';
const props = defineProps<{ personId: string }>();
const id = useId();
const tasks = useTasks();
const now = useNow();
const today = computed(() => todayIso(now.value));
const clock = computed(
  () =>
    `${String(now.value.getHours()).padStart(2, '0')}:${String(now.value.getMinutes()).padStart(2, '0')}`,
);
const dayTasks = computed<TaskOccurrence[]>(() =>
  sortSeniorTasks(tasks.tasksOn(props.personId, today.value)),
);
const nextId = computed(() => nextSeniorTask(dayTasks.value, clock.value));
const done = computed(() => dayTasks.value.filter((task) => task.completed).length);
const rows = computed(() =>
  dayTasks.value.map((task) => ({
    ...task,
    timeLabel: formatClockTime(task.time),
    icon: task.kind === 'medicine' ? ('pill' as const) : ('task' as const),
    tickLabel: task.completed ? `Mark ${task.title} not done` : `Mark ${task.title} done`,
  })),
);
const dialog = ref<HTMLDialogElement | null>(null);
const addButton = ref<HTMLButtonElement | null>(null);
const formOpen = ref(false);
const notice = ref('');
function toggle(task: TaskOccurrence) {
  tasks.setCompleted(props.personId, task.task_id, today.value, !task.completed);
  notice.value = `${task.title} marked ${task.completed ? 'not done' : 'done'}.`;
}
async function openForm() {
  formOpen.value = true;
  await nextTick();
  dialog.value?.showModal();
  dialog.value?.querySelector('input')?.focus();
}
function closeForm() {
  dialog.value?.close();
  formOpen.value = false;
  addButton.value?.focus();
}
function save(input: TaskInput) {
  tasks.add(props.personId, input);
  notice.value = input.start_date === today.value ? 'Task added.' : 'Task added to your calendar.';
  closeForm();
}
onBeforeUnmount(() => dialog.value?.close());
</script>

<template>
  <section
    class="sl-panel senior-tasks rounded-4 shadow-sm p-4"
    :aria-labelledby="`${id}-heading`"
    data-testid="task-panel"
  >
    <div class="d-flex flex-wrap align-items-center justify-content-between gap-3 mb-4">
      <div>
        <h2 :id="`${id}-heading`" class="fs-3 d-flex align-items-center gap-2">
          <Icon name="task" />Today's tasks
        </h2>
        <p class="fs-5 mb-0 text-body-secondary">{{ done }} of {{ rows.length }} done</p>
      </div>
      <button
        ref="addButton"
        type="button"
        class="btn btn-primary btn-lg"
        data-testid="add-task"
        @click="openForm"
      >
        Add task
      </button>
    </div>
    <p v-if="!rows.length" class="fs-5">No tasks for today.</p>
    <ul v-else class="list-unstyled d-grid gap-3 mb-0">
      <li
        v-for="task in rows"
        :key="task.task_id"
        class="task-row rounded-4 p-3"
        :class="{ completed: task.completed, 'next-task': task.task_id === nextId }"
      >
        <span class="task-time fs-5 fw-semibold tabular">{{ task.timeLabel }}</span>
        <div class="task-content">
          <span class="d-flex align-items-start gap-2 fs-5 fw-semibold"
            ><Icon :name="task.icon" /><span class="task-title">{{ task.title }}</span></span
          >
          <span v-if="task.notes" class="d-block text-body-secondary mt-1">{{ task.notes }}</span>
          <span
            v-if="task.task_id === nextId"
            class="next-badge d-inline-block rounded-pill px-2 mt-1 fw-semibold"
            >Next</span
          >
        </div>
        <button
          type="button"
          class="tick-button rounded-circle"
          :aria-label="task.tickLabel"
          :aria-pressed="task.completed"
          @click="toggle(task)"
        >
          <Icon v-if="task.completed" name="check" /><span
            v-else
            aria-hidden="true"
            class="empty-tick"
          ></span>
        </button>
      </li>
    </ul>
    <p class="fs-5 mt-3 mb-0" role="status">{{ notice }}</p>
    <Teleport to="body">
      <dialog
        ref="dialog"
        class="modal senior-task-modal"
        :aria-labelledby="`${id}-modal-title`"
        @cancel.prevent="closeForm"
        @click.self="closeForm"
      >
        <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
          <div class="modal-content rounded-4 shadow-sm">
            <div class="modal-header">
              <h2 :id="`${id}-modal-title`" class="modal-title fs-3">Add a task</h2>
              <button type="button" class="btn btn-outline-secondary" @click="closeForm">
                Close
              </button>
            </div>
            <div class="modal-body p-4">
              <TaskForm v-if="formOpen" :day="today" @save="save" @cancel="closeForm" />
            </div>
          </div>
        </div>
      </dialog>
    </Teleport>
  </section>
</template>

<style scoped>
.senior-tasks {
  border-top: 0.35rem solid var(--sl-orange-deep);
}
.task-row {
  display: grid;
  grid-template-columns: 6.5rem minmax(0, 1fr) 3rem;
  gap: 0.75rem;
  align-items: center;
  border: 1px solid var(--sl-line);
  background: var(--sl-surface);
}
.task-content {
  min-width: 0;
  overflow-wrap: anywhere;
}
.task-time {
  color: var(--sl-ink);
}
.next-task {
  border-color: var(--sl-orange-deep);
}
.next-badge {
  background: var(--sl-orange-soft);
  color: var(--sl-orange-deep);
}
.completed .task-title {
  text-decoration: line-through;
  color: var(--sl-ink-soft);
}
.tick-button {
  width: 48px;
  height: 48px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--sl-jade-deep);
  background: var(--sl-surface);
  color: var(--sl-jade-deep);
}
.tick-button[aria-pressed='true'] {
  background: var(--sl-jade-soft);
}
button:focus-visible {
  outline: 3px solid var(--sl-blue-deep);
  outline-offset: 3px;
}
.senior-task-modal {
  border: 0;
  margin: 0;
  padding: 0;
  width: 100%;
  max-width: none;
  height: 100%;
  max-height: none;
  background: transparent;
  color: var(--sl-ink);
}
.senior-task-modal[open] {
  display: block;
}
.senior-task-modal::backdrop {
  background: color-mix(in srgb, var(--sl-ink) 50%, transparent);
}
.senior-task-modal .modal-dialog {
  pointer-events: auto;
}
.senior-task-modal :deep(.btn),
.senior-tasks > div > .btn {
  min-height: 48px;
}
.senior-task-modal :deep(.form-control),
.senior-task-modal :deep(.form-select) {
  min-height: 48px;
  font-size: 1.125rem;
}
@media (max-width: 575.98px) {
  .task-row {
    grid-template-columns: minmax(0, 1fr) 3rem;
  }
  .task-time {
    grid-column: 1;
  }
  .task-content {
    grid-column: 1;
  }
  .tick-button {
    grid-column: 2;
    grid-row: 1 / 3;
  }
}
</style>
