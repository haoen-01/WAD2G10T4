/**
 * What the senior screen lists as coming up. Pure and free of Vue, so
 * `lib/senior-upcoming.test.ts` can run it under Node's type stripping.
 */
import { addDays } from './calendar';

interface UpcomingItem {
  id: string;
  date: string;
  start: string;
}

/** The next three events this week, excluding events that have already started. */
export function upcomingEvents<T extends UpcomingItem>(
  items: readonly T[],
  today: string,
  clock: string,
): T[] {
  const end = addDays(today, 6);
  return items
    .filter(
      (item) =>
        item.date >= today && item.date <= end && (item.date > today || item.start >= clock),
    )
    .sort(
      (a, b) =>
        a.date.localeCompare(b.date) || a.start.localeCompare(b.start) || a.id.localeCompare(b.id),
    )
    .slice(0, 3);
}
