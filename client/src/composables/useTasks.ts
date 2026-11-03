import type { TaskList } from '@silverloop/api-client';
import { ref, watch } from 'vue';

import { currentGroup, loadMe } from '@/composables/useMe';
import { showToast } from '@/composables/useToast';
import { classifyApiError } from '@/lib/api-errors';
import { calendarSourceFor } from '@/lib/family-group';
import type { CalendarSource } from '@/lib/family-group';
import { DEMO_PERSON_ID } from '@/lib/labels';
import {
  cleanTask,
  deleteTask,
  emptyStore,
  setCompleted,
  storeFromList,
  tasksByDay,
  tasksOn,
  updateTask,
} from '@/lib/tasks';
import type { TaskInput, TaskStore } from '@/lib/tasks';
import * as api from '@/services/careApi';

/**
 * The senior's tasks, kept by their family group in the API (`/v1/.../tasks`). A module singleton,
 * like `useFamily`, so the Tasks panel, the day timeline, the calendar, the week ahead and the
 * senior's list all show the same list, and a change in one shows in the others at once.
 *
 * It reads from the same place as the calendar: the senior their own, a family member the group
 * they picked (so it works before the senior is linked). A tick or an edit shows straight away and
 * is undone, with a message, if the API refuses it.
 */
const store = ref<TaskStore>(emptyStore());
const groupId = ref<string | null>(null);
const loaded = ref(false);
const error = ref<string | null>(null);
/** Where the shown list came from, so a tick goes back to the same place. */
let source: CalendarSource | null = null;

const keyOf = (from: CalendarSource) =>
  from.kind === 'group' ? `group:${from.groupId}` : `person:${from.personId}`;

let reading: Promise<void> | null = null;
/** The group changed while a read was in flight: read again once it lands. */
let readAgain = false;

/** Reads the list again. Calls made while a read is in flight share it. */
function refresh(): Promise<void> {
  reading ??= (async () => {
    try {
      const me = await loadMe().catch(() => null);
      const next = calendarSourceFor(me, currentGroup.value, DEMO_PERSON_ID);
      // Another senior or group: show nothing of the last one while this one loads.
      if (!source || keyOf(source) !== keyOf(next)) {
        store.value = emptyStore();
        loaded.value = false;
      }
      source = next;
      const list: TaskList =
        next.kind === 'group'
          ? await api.getGroupTasks(next.groupId)
          : await api.getPersonTasks(next.personId);
      store.value = storeFromList(list);
      groupId.value = list.group_id ?? null;
      error.value = null;
      loaded.value = true;
    } catch (caught) {
      error.value = classifyApiError(caught).message;
    } finally {
      reading = null;
      if (readAgain) {
        readAgain = false;
        void refresh();
      }
    }
  })();
  return reading;
}

// Picking another senior in the navbar shows their tasks.
watch(
  () => currentGroup.value?.group_id,
  (next, previous) => {
    if (next === previous) return;
    if (reading) readAgain = true;
    else if (loaded.value) void refresh();
  },
);

/**
 * Shows `change` at once, then saves it. If the save fails, the list goes back to how it was and
 * the reason shows. Either way the list is read again afterwards.
 */
async function save(change: (now: TaskStore) => TaskStore, work: () => Promise<unknown>) {
  const before = store.value;
  store.value = change(before);
  try {
    await work();
    return true;
  } catch (caught) {
    store.value = before;
    showToast(classifyApiError(caught).message);
    return false;
  } finally {
    void refresh();
  }
}

function needGroup(): string | null {
  if (!groupId.value || source?.kind !== 'group') {
    showToast('Only family members in the group can change tasks.');
    return null;
  }
  return groupId.value;
}

export function useTasks() {
  // Every screen that shows tasks reads them fresh when it opens.
  void refresh();
  return {
    loaded,
    error,
    refresh,
    /** Whether this viewer can add, edit and delete tasks: a family member in the group. */
    canManage: () => groupId.value !== null && source?.kind === 'group',
    /** All the task schedules. */
    schedules: () => store.value.schedules,
    /** One day's tasks, earliest first. */
    tasksOn: (day: string) => tasksOn(store.value, day),
    /** The tasks on each of these days, for the calendar. */
    tasksByDay: (days: readonly string[]) => tasksByDay(store.value, days),
    /** Adds a task. Resolves to whether it was saved. */
    async add(input: TaskInput): Promise<boolean> {
      const group = needGroup();
      if (!group) return false;
      try {
        await api.createTask(group, cleanTask(input));
        await refresh();
        return true;
      } catch (caught) {
        showToast(classifyApiError(caught).message);
        return false;
      }
    },
    update(taskId: string, input: TaskInput): Promise<boolean> {
      const group = needGroup();
      if (!group) return Promise.resolve(false);
      return save(
        (now) => updateTask(now, taskId, input),
        () => api.updateTask(group, taskId, cleanTask(input)),
      );
    },
    remove(taskId: string): Promise<boolean> {
      const group = needGroup();
      if (!group) return Promise.resolve(false);
      return save(
        (now) => deleteTask(now, taskId),
        () => api.deleteTask(group, taskId),
      );
    },
    /** Ticks one day of a task done, or not. The senior's own screen goes through their route. */
    setCompleted(taskId: string, day: string, completed: boolean): Promise<boolean> {
      const from = source;
      if (!from) return Promise.resolve(false);
      return save(
        (now) => setCompleted(now, taskId, day, completed),
        () =>
          from.kind === 'group'
            ? api.setGroupTaskDay(from.groupId, taskId, day, completed)
            : api.setPersonTaskDay(from.personId, taskId, day, completed),
      );
    },
  };
}
