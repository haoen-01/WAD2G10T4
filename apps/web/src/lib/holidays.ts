/**
 * Singapore public holidays from Nager.Date, reduced to what the calendar shows. Pure, so
 * `node --test` can check it without a network: the Axios call is in `services/publicApis.ts`.
 *
 * Source: https://date.nager.at/api/v3/PublicHolidays/{year}/SG
 */

/** One entry of the API's JSON array (only the fields this app reads). */
export interface PublicHolidayResponse {
  date: string;
  localName?: string;
  name?: string;
}

export interface PublicHoliday {
  /** YYYY-MM-DD */
  date: string;
  name: string;
}

/**
 * Clean, sorted holidays. The API lists a holiday once per day, and some names repeat (Chinese New
 * Year is two days), so the result is keyed by date, never by name.
 */
export function toHolidays(body: unknown): PublicHoliday[] {
  if (!Array.isArray(body)) return [];
  const holidays: PublicHoliday[] = [];
  for (const entry of body as PublicHolidayResponse[]) {
    if (!entry || typeof entry.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(entry.date))
      continue;
    const name = entry.name || entry.localName;
    if (!name) continue;
    holidays.push({ date: entry.date, name });
  }
  return holidays.sort((a, b) => a.date.localeCompare(b.date));
}

/** Date to holiday name, for the calendar grid. Two holidays on one day are joined. */
export function holidaysByDay(holidays: PublicHoliday[]): Record<string, string> {
  const days: Record<string, string> = {};
  for (const holiday of holidays) {
    days[holiday.date] = days[holiday.date]
      ? `${days[holiday.date]} / ${holiday.name}`
      : holiday.name;
  }
  return days;
}

/** The holidays that fall in one month (`month` is 1 to 12). */
export function holidaysInMonth(
  holidays: PublicHoliday[],
  year: number,
  month: number,
): PublicHoliday[] {
  const prefix = `${year}-${String(month).padStart(2, '0')}-`;
  return holidays.filter((holiday) => holiday.date.startsWith(prefix));
}
