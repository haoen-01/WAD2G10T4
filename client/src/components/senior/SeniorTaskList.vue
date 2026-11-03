<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue';

import BadgeCelebration from '@/components/badges/BadgeCelebration.vue';
import Icon from '@/components/ui/Icon.vue';
import { useTasks } from '@/composables/useTasks';
import { useNow } from '@/composables/useNow';
import { todayIso } from '@/lib/calendar';
import { formatClockTime } from '@/lib/format-date';
import {
  finishedTheDay,
  nextSeniorTask,
  readCheered,
  saveCheered,
  shouldCheer,
  sortSeniorTasks,
} from '@/lib/senior-view';
import type { TaskOccurrence } from '@/lib/tasks';
/**
 * The senior's own list of today's tasks. The senior ticks them done; their family adds and
 * changes them (`useTasks`, kept by the family group in the API).
 */
const id = useId();
const tasks = useTasks();
const now = useNow();
const today = computed(() => todayIso(now.value));
const clock = computed(
  () =>
    `${String(now.value.getHours()).padStart(2, '0')}:${String(now.value.getMinutes()).padStart(2, '0')}`,
);
const dayTasks = computed<TaskOccurrence[]>(() => sortSeniorTasks(tasks.tasksOn(today.value)));
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
const notice = ref('');
/** The small "all done" confetti, shown for a few seconds when the last task of the day is ticked. */
const cheering = ref(false);
let cheerTimer = 0;
/** Confetti colours from the theme (jade, sun, orange), read at the moment of the cheer. */
function cheerColours(): string[] {
  const style = getComputedStyle(document.documentElement);
  return ['--sl-jade', '--sl-sun', '--sl-orange', '--sl-mint']
    .map((name) => style.getPropertyValue(name).trim())
    .filter(Boolean);
}
const colours = ref<string[]>([]);
/** localStorage, or null where the browser refuses it (some private modes). */
const storage = (() => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
})();
onBeforeUnmount(() => window.clearTimeout(cheerTimer));

async function toggle(task: TaskOccurrence) {
  notice.value = '';
  const before = { done: done.value, total: dayTasks.value.length };
  const wasDone = task.completed;
  const saved = await tasks.setCompleted(task.task_id, today.value, !wasDone);
  if (!saved) return;
  const after = { done: done.value, total: dayTasks.value.length };
  const finished = finishedTheDay(before, after);
  notice.value = finished
    ? `${task.title} marked done. All done for today. Well done!`
    : `${task.title} marked ${wasDone ? 'not done' : 'done'}.`;
  // No motion library on the senior screen: the device's reduced-motion setting is read directly.
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  const lastCheered = storage ? readCheered(storage) : null;
  if (shouldCheer({ finished, today: today.value, lastCheered, reducedMotion })) {
    if (storage) saveCheered(storage, today.value);
    colours.value = cheerColours();
    cheering.value = true;
    window.clearTimeout(cheerTimer);
    cheerTimer = window.setTimeout(() => (cheering.value = false), 4500);
  }
}
</script>

<template>
  <section
    class="sl-panel senior-tasks"
    :aria-labelledby="`${id}-heading`"
    data-testid="task-panel"
  >
    <div class="d-flex flex-wrap align-items-center justify-content-between gap-3 mb-4">
      <div>
        <h2 :id="`${id}-heading`" class="fs-3 d-flex align-items-center gap-2">
          <Icon name="task" />Today's tasks
        </h2>
        <p class="fs-5 mb-0 text-body-secondary">
          <template v-if="rows.length && done === rows.length">All done for today</template>
          <template v-else>{{ done }} of {{ rows.length }} done</template>
        </p>
      </div>
    </div>
    <p v-if="tasks.error.value && !tasks.loaded.value" class="fs-5" role="alert">
      Your tasks could not be loaded. Please try again soon.
    </p>
    <p v-else-if="!tasks.loaded.value" class="fs-5 text-body-secondary">Loading your tasks…</p>
    <p v-else-if="!rows.length" class="fs-5">No tasks for today.</p>
    <ul v-else class="list-unstyled d-grid mb-0">
      <li
        v-for="task in rows"
        :key="task.task_id"
        class="task-row"
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
          <span
            v-if="task.completed"
            class="done-badge d-inline-flex align-items-center gap-1 rounded-pill px-2 mt-1 fw-semibold"
            ><Icon name="check" />Done</span
          >
        </div>
        <button
          type="button"
          class="tick-button rounded-circle"
          :aria-label="task.tickLabel"
          :aria-pressed="task.completed"
          @click="toggle(task)"
        >
          <!-- The tick draws itself in when done (a CSS stroke transition, no motion library). -->
          <svg class="tick-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M5 12.5l4.5 4.5L19 7.5" pathLength="1" />
          </svg>
        </button>
      </li>
    </ul>
    <p class="fs-5 mt-3 mb-0" role="status" data-testid="senior-task-notice">{{ notice }}</p>
    <BadgeCelebration v-if="cheering" brief :colours="colours" :origin="null" />
  </section>
</template>

<style scoped>
/* A plain panel like Home's; rows are split by a rule, not boxed, so the words keep the width. The
   tick column is drawn in px (56), so at 150% zoom the text column does not shrink with it. */
.task-row {
  transition: background-color var(--sl-dur-base) ease;
  display: grid;
  grid-template-columns: 6.5rem minmax(0, 1fr) 56px;
  gap: 0.75rem;
  align-items: center;
  padding: 0.85rem 0.5rem;
  border-top: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
}
.task-row:first-child {
  border-top: 0;
}
.task-content {
  min-width: 0;
  overflow-wrap: break-word;
}
.task-time {
  color: var(--sl-ink);
}
/* The next task is marked by its tag only. */
.next-badge {
  background: var(--sl-orange-soft);
  color: var(--sl-orange-deep);
}
/* Done: a pale jade row, the title struck through, a "Done" tag and a filled tick. */
.task-row.completed {
  border-top-color: transparent;
  background: var(--sl-jade-soft);
}
.task-row.completed + .task-row {
  border-top-color: transparent;
}
.task-title {
  transition: color var(--sl-dur-base) ease;
}
.completed .task-title {
  text-decoration: line-through;
  color: var(--sl-ink-soft);
}
.done-badge {
  background: var(--sl-surface);
  color: var(--sl-jade-deep);
}
.tick-button {
  width: 56px;
  height: 56px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--sl-jade-deep);
  background: var(--sl-surface);
  color: var(--sl-jade-deep);
}
.tick-button {
  transition:
    background-color var(--sl-dur-base) ease,
    border-color var(--sl-dur-base) ease,
    color var(--sl-dur-base) ease,
    transform var(--sl-dur-press) var(--sl-ease-out);
}
.tick-button:active {
  transform: scale(0.97);
}
/* The tick: a stroke hidden until done, then drawn in over 260 ms. */
.tick-mark {
  width: 1.9rem;
  height: 1.9rem;
  fill: none;
  stroke: currentcolor;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.tick-mark path {
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  transition: stroke-dashoffset 0.26s var(--sl-ease-out);
}
.tick-button[aria-pressed='true'] .tick-mark path {
  stroke-dashoffset: 0;
}
@media (prefers-reduced-motion: reduce) {
  .tick-button:active {
    transform: none;
  }
}
.tick-button[aria-pressed='true'] {
  border-color: var(--sl-jade);
  background: var(--sl-jade);
  color: var(--sl-jade-on);
}
button:focus-visible {
  outline: 3px solid var(--sl-focus);
  outline-offset: 3px;
}
@media (max-width: 575.98px) {
  .task-row {
    grid-template-columns: minmax(0, 1fr) 56px;
    column-gap: 0.5rem;
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
