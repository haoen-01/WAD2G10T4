import { compareWords, percentOfUsual } from '../../lib/activity';
import { addDays } from '../../lib/calendar';
export const TABS = ['today', 'calendar', 'badges', 'family'];
export const TAB_KEY = 'careplus.seniorTab.v1';
export function readTab(storage) {
  try {
    const value = storage.getItem(TAB_KEY);
    return TABS.find((tab) => tab === value) ?? 'today';
  } catch {
    return 'today';
  }
}
export function saveTab(storage, tab) {
  try {
    storage.setItem(TAB_KEY, tab);
  } catch {
    /* Works for this visit. */
  }
}
export function adjacentTab(tab, key) {
  const index = TABS.indexOf(tab);
  if (key === 'Home') return 'today';
  if (key === 'End') return 'family';
  if (key === 'ArrowRight') return TABS[(index + 1) % TABS.length];
  if (key === 'ArrowLeft') return TABS[(index + TABS.length - 1) % TABS.length];
  return null;
}
export function stepProgress(steps, usual) {
  const percent = percentOfUsual(steps, usual);
  return { percent, fill: percent === null ? 0 : Math.min(100, Math.max(0, percent)) };
}
export function stepWords(steps, usual) {
  const words = compareWords(percentOfUsual(steps, usual));
  if (words === 'more than a usual day') return 'More than usual';
  if (words === 'about the same as a usual day') return 'About the same as usual';
  if (words === 'not enough data to compare yet') return 'Not enough data to compare yet';
  return 'A bit less than usual';
}
export function sevenDays(readings, latest) {
  return Array.from({ length: 7 }, (_, index) => {
    const day = addDays(latest, index - 6);
    return { day, reading: readings.find((item) => item.day === day) ?? null };
  });
}
export function sortSeniorTasks(tasks) {
  return [...tasks].sort(
    (a, b) => a.time.localeCompare(b.time) || a.task_id.localeCompare(b.task_id),
  );
}
export function nextSeniorTask(tasks, clock) {
  return (
    sortSeniorTasks(tasks).find((task) => !task.completed && task.time >= clock)?.task_id ?? null
  );
}
