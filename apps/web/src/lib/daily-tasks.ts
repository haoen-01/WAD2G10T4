/**
 * The day's medicine and other simple reminders shown on the Home overview. There is no backend
 * concept for this yet (see UPDATES.md): it is made-up sample data for the same demo person the
 * rest of the app is built around, always "today's" list rather than tied to a real date.
 *
 * Pure and free of Vue, so `lib/daily-tasks.test.ts` can run it under Node's type stripping; the
 * Home screen only reads it and tracks which ids are checked off, in memory.
 */

export type DailyTaskKind = 'medicine' | 'task';

export interface DailyTask {
  id: string;
  label: string;
  /** `HH:MM`, 24-hour. */
  time: string;
  kind: DailyTaskKind;
  notes?: string;
}

/** What each kind is called on screen. */
export const TASK_KIND_LABELS: Record<DailyTaskKind, string> = {
  medicine: 'Medicine',
  task: 'To do',
};

/** Mdm Lim's made-up checklist for today: when to take each medicine, and the day's reminders. */
export function sampleDailyTasks(): DailyTask[] {
  const tasks: DailyTask[] = [
    {
      id: 'task-bp-morning',
      label: 'Blood pressure tablet',
      time: '08:00',
      kind: 'medicine',
      notes: 'With breakfast',
    },
    { id: 'task-vitamin', label: 'Vitamin D supplement', time: '08:00', kind: 'medicine' },
    { id: 'task-water', label: 'Drink a glass of water', time: '10:00', kind: 'task' },
    { id: 'task-stretch', label: 'Light stretching', time: '17:00', kind: 'task' },
    {
      id: 'task-bp-evening',
      label: 'Blood pressure tablet',
      time: '20:00',
      kind: 'medicine',
      notes: 'After dinner',
    },
  ];
  return tasks.sort(byTime);
}

function byTime(a: DailyTask, b: DailyTask): number {
  return a.time.localeCompare(b.time) || a.label.localeCompare(b.label);
}
