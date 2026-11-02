/**
 * Shared tasks ("Take morning medicine", "Water the plants") and their rules. Pure and free of Vue,
 * so `lib/tasks.test.ts` can run it under Node's type stripping; `composables/useTasks.ts` wraps it
 * in reactive state read from the API.
 *
 * The API keeps one list per family group (`silverloop.family_tasks`, which mirrors `occursOn`).
 * These rules work out each day of it and change the list straight away while a save is on its way.
 */

export type TaskRepeat = 'none' | 'daily' | 'weekly';

export const TASK_REPEAT_LABELS: Record<TaskRepeat, string> = {
  none: 'Once',
  daily: 'Every day',
  weekly: 'Every week',
};

/** What someone fills in to add or change a task. */
export interface TaskInput {
  title: string;
  /** `YYYY-MM-DD`: the first (or only) day. */
  start_date: string;
  /** `HH:MM`, 24-hour. */
  time: string;
  repeat: TaskRepeat;
  /** `YYYY-MM-DD`: the last day a repeating task happens, or `null` for no end. */
  repeat_until: string | null;
  notes: string;
  /** Medicine gets its own tag in the list. None: a plain to-do. */
  kind?: TaskKind;
}

export type TaskKind = 'task' | 'medicine';

/** A saved task schedule. A repeating task is one schedule that happens on many days. */
export interface TaskSchedule extends TaskInput {
  task_id: string;
}

/** One day of a task, and whether it has been ticked off for that day. */
export interface TaskOccurrence extends TaskSchedule {
  date: string;
  completed: boolean;
}

/** Everything kept for one senior. `completions` maps a task to the days it was ticked off. */
export interface TaskStore {
  schedules: TaskSchedule[];
  completions: Record<string, string[]>;
}

export const emptyStore = (): TaskStore => ({ schedules: [], completions: {} });

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Whole days from `from` to `to` (negative when `to` comes first). */
function daysBetween(from: string, to: string): number {
  const utc = (iso: string) => {
    const [year, month, day] = iso.split('-').map(Number);
    return Date.UTC(year, month - 1, day);
  };
  return Math.round((utc(to) - utc(from)) / 86_400_000);
}

/** Whether a task happens on a day. */
export function occursOn(task: TaskSchedule, day: string): boolean {
  if (day < task.start_date) return false;
  if (task.repeat === 'none') return day === task.start_date;
  if (task.repeat_until && day > task.repeat_until) return false;
  return task.repeat === 'daily' || daysBetween(task.start_date, day) % 7 === 0;
}

/** The tasks on one day, earliest first, each with whether it was ticked off that day. */
export function tasksOn(store: TaskStore, day: string): TaskOccurrence[] {
  return (
    store.schedules
      .filter((task) => occursOn(task, day))
      .map((task) => ({
        ...task,
        date: day,
        completed: store.completions[task.task_id]?.includes(day) ?? false,
      }))
      // `HH:MM` sorts by time as plain text.
      .sort((a, b) => a.time.localeCompare(b.time) || a.title.localeCompare(b.title))
  );
}

/** The tasks on each of a list of days, keyed by day. Days with no tasks are left out. */
export function tasksByDay(store: TaskStore, days: readonly string[]) {
  const result: Record<string, TaskOccurrence[]> = {};
  for (const day of days) {
    const list = tasksOn(store, day);
    if (list.length) result[day] = list;
  }
  return result;
}

/** What is wrong with a task before it is saved, or `null` when it can be saved. */
export function checkTask(input: TaskInput): string | null {
  if (!input.title.trim()) return 'Please give the task a name.';
  if (!ISO_DAY.test(input.start_date)) return 'Please choose the first day.';
  if (!CLOCK.test(input.time)) return 'Please choose a time.';
  if (input.repeat !== 'none' && input.repeat_until) {
    if (!ISO_DAY.test(input.repeat_until)) return 'Please choose a valid last day.';
    if (input.repeat_until < input.start_date) {
      return 'The last day must be on or after the first day.';
    }
  }
  return null;
}

/** The input tidied for saving: a trimmed title, and no last day on a task that happens once. */
export function cleanTask(input: TaskInput): TaskInput {
  return {
    title: input.title.trim(),
    start_date: input.start_date,
    time: input.time,
    repeat: input.repeat,
    repeat_until: input.repeat === 'none' ? null : input.repeat_until || null,
    notes: input.notes.trim(),
    kind: input.kind === 'medicine' ? 'medicine' : 'task',
  };
}

export function addTask(store: TaskStore, input: TaskInput, taskId: string): TaskStore {
  return { ...store, schedules: [...store.schedules, { ...cleanTask(input), task_id: taskId }] };
}

/** Changes the whole schedule. Days already ticked off stay ticked off. */
export function updateTask(store: TaskStore, taskId: string, input: TaskInput): TaskStore {
  return {
    ...store,
    schedules: store.schedules.map((task) =>
      task.task_id === taskId ? { ...cleanTask(input), task_id: taskId } : task,
    ),
  };
}

/** Removes a task and every day it was ticked off. */
export function deleteTask(store: TaskStore, taskId: string): TaskStore {
  const completions = { ...store.completions };
  delete completions[taskId];
  return { schedules: store.schedules.filter((task) => task.task_id !== taskId), completions };
}

/** Ticks a task off (or back on) for one day. */
export function setCompleted(
  store: TaskStore,
  taskId: string,
  day: string,
  completed: boolean,
): TaskStore {
  const days = (store.completions[taskId] ?? []).filter((done) => done !== day);
  return {
    ...store,
    completions: { ...store.completions, [taskId]: completed ? [...days, day] : days },
  };
}

/** The parts of the API's task list (`TaskList`) these rules need. */
export interface TaskListLike {
  tasks: ReadonlyArray<{
    task_id: string;
    title: string;
    kind?: string;
    start_date: string;
    time: string;
    repeat?: string;
    repeat_until?: string | null;
    notes?: string;
  }>;
  ticks: ReadonlyArray<{ task_id: string; day: string }>;
}

/** The API's task list as the store the screens read. */
export function storeFromList(list: TaskListLike): TaskStore {
  const completions: Record<string, string[]> = {};
  for (const tick of list.ticks) (completions[tick.task_id] ??= []).push(tick.day);
  return {
    schedules: list.tasks.map((task) => ({
      task_id: task.task_id,
      title: task.title,
      start_date: task.start_date,
      time: task.time,
      repeat: task.repeat === 'daily' || task.repeat === 'weekly' ? task.repeat : 'none',
      repeat_until: task.repeat_until ?? null,
      notes: task.notes ?? '',
      kind: task.kind === 'medicine' ? 'medicine' : 'task',
    })),
    completions,
  };
}
