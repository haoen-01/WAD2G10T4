import axios from 'axios';

import { toHolidays, type PublicHoliday } from '@/lib/holidays';
import {
  summariseForecast,
  type ForecastSummary,
  type TwoHourForecastResponse,
} from '@/lib/weather';

/**
 * Free public APIs the browser calls directly with Axios. Both send back
 * `Access-Control-Allow-Origin: *` and need no key. Nothing about the senior is ever sent: the
 * requests carry only a year or nothing at all.
 *
 * This is a separate Axios instance from `services/http.ts` on purpose: these requests must never
 * carry the Care+ sign-in token.
 */
const publicHttp = axios.create({ timeout: 8_000 });

export const FORECAST_URL = 'https://api-open.data.gov.sg/v2/real-time/api/two-hr-forecast';
export const HOLIDAYS_URL = 'https://date.nager.at/api/v3/PublicHolidays';

/** NEA's 2-hour forecast for every area in Singapore (data.gov.sg). Throws when it is unavailable. */
export async function getTwoHourForecast(): Promise<ForecastSummary> {
  const response = await publicHttp.get<TwoHourForecastResponse>(FORECAST_URL);
  const summary = summariseForecast(response.data);
  if (!summary) throw new Error('The forecast came back in a shape this page does not understand.');
  return summary;
}

/** Singapore's public holidays for one year (Nager.Date). */
export async function getPublicHolidays(year: number): Promise<PublicHoliday[]> {
  const response = await publicHttp.get<unknown>(`${HOLIDAYS_URL}/${year}/SG`);
  return toHolidays(response.data);
}
