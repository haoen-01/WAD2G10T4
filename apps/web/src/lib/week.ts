/**
 * The week a day belongs to, for the phone's week strip. Pure, so `lib/week.test.ts` runs it under
 * Node. Weeks start on Sunday, the same as the month grid.
 */
import { addDays } from './calendar';
import { parseIsoDay } from './format-date';

/** The seven days (Sunday to Saturday) around `iso`. An unreadable day gives an empty week. */
export function weekOf(iso: string): string[] {
  const parts = parseIsoDay(iso);
  if (!parts) return [];
  const start = addDays(iso, -parts.weekday);
  return Array.from({ length: 7 }, (_, index) => addDays(start, index));
}
