import { reactive } from 'vue';

import { todayIso } from '@/lib/calendar';
import { sampleDailyTasks } from '@/lib/daily-tasks';
import { newId } from '@/lib/family';
import { DEMO_PERSON_ID } from '@/lib/labels';
import {
  addTask,
  deleteTask,
  emptyStore,
  parseStore,
  setCompleted,
  tasksByDay,
  tasksOn,
  updateTask,
} from '@/lib/tasks';
import type { TaskInput, TaskStore } from '@/lib/tasks';

/**
 * Each senior's tasks, kept in this browser (the API has no tasks yet). A module singleton, like
 * `useFamily`, so the Tasks panel, the calendar and the week ahead all show the same list, and a
 * change in one shows in the others at once. Another tab of this browser picks changes up too.
 */
const KEY_PREFIX = 'careplus.tasks.v1.';
const stores = reactive<Record<string, TaskStore>>({});

/**
 * The demo senior starts with the sample daily checklist (`lib/daily-tasks.ts`), every day from
 * today, so the panel has something to show. Only the first time: once anything is saved for her
 * (even deleting them all), that is what is kept.
 */
function sampleStore(): TaskStore {
  let store = emptyStore();
  for (const sample of sampleDailyTasks()) {
    store = addTask(
      store,
      {
        title: sample.label,
        start_date: todayIso(),
        time: sample.time,
        repeat: 'daily',
        repeat_until: null,
        notes: sample.notes ?? '',
        kind: sample.kind === 'medicine' ? 'medicine' : 'task',
      },
      sample.id,
    );
  }
  return store;
}

function read(personId: string): TaskStore {
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + personId);
    if (raw === null && personId === DEMO_PERSON_ID) {
      const seeded = sampleStore();
      window.localStorage.setItem(KEY_PREFIX + personId, JSON.stringify(seeded));
      return seeded;
    }
    return parseStore(raw);
  } catch {
    // Storage blocked (a private window, site data off): an empty list that lasts for this visit.
    return emptyStore();
  }
}

function storeOf(personId: string): TaskStore {
  return (stores[personId] ??= read(personId));
}

function write(personId: string, next: TaskStore): void {
  stores[personId] = next;
  try {
    window.localStorage.setItem(KEY_PREFIX + personId, JSON.stringify(next));
  } catch {
    // Not saved past this visit, but the screen still shows the change.
  }
}

// A change made in another tab of this browser.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key?.startsWith(KEY_PREFIX)) {
      stores[event.key.slice(KEY_PREFIX.length)] = parseStore(event.newValue);
    }
  });
}

export function useTasks() {
  return {
    /** All of one senior's task schedules. */
    schedulesOf: (personId: string) => storeOf(personId).schedules,
    /** One day's tasks, earliest first. */
    tasksOn: (personId: string, day: string) => tasksOn(storeOf(personId), day),
    /** The tasks on each of these days, for the calendar. */
    tasksByDay: (personId: string, days: readonly string[]) => tasksByDay(storeOf(personId), days),
    add: (personId: string, input: TaskInput) =>
      write(personId, addTask(storeOf(personId), input, newId('task'))),
    update: (personId: string, taskId: string, input: TaskInput) =>
      write(personId, updateTask(storeOf(personId), taskId, input)),
    remove: (personId: string, taskId: string) =>
      write(personId, deleteTask(storeOf(personId), taskId)),
    setCompleted: (personId: string, taskId: string, day: string, completed: boolean) =>
      write(personId, setCompleted(storeOf(personId), taskId, day, completed)),
  };
}
