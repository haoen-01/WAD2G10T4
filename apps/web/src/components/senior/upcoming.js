import { addDays } from '../../lib/calendar';
/** The next three events this week, excluding events that have already started. */
export function upcomingEvents(items, today, clock) {
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
