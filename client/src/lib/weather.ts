/**
 * The 2-hour weather forecast from data.gov.sg (NEA), reduced to what the Home card shows.
 * Pure, so `node --test` can check it without a network: the Axios call is in
 * `services/publicApis.ts`.
 *
 * Source: https://api-open.data.gov.sg/v2/real-time/api/two-hr-forecast
 */

/** The part of the API's JSON this app reads. */
export interface TwoHourForecastResponse {
  data?: {
    items?: {
      timestamp?: string;
      valid_period?: { text?: string };
      forecasts?: { area: string; forecast: string }[];
    }[];
  };
}

export interface AreaForecast {
  area: string;
  forecast: string;
}

export interface ForecastSummary {
  /** Every area, sorted A to Z, for the area picker. */
  forecasts: AreaForecast[];
  /** "9.30 am to 11.30 am", when the API gives one. */
  validFor: string | null;
}

/** The newest forecast in the response, or null when the JSON is not the shape we expect. */
export function summariseForecast(body: TwoHourForecastResponse): ForecastSummary | null {
  const items = body.data?.items;
  if (!Array.isArray(items) || items.length === 0) return null;
  const latest = items[items.length - 1];
  if (!Array.isArray(latest.forecasts) || latest.forecasts.length === 0) return null;
  const forecasts = latest.forecasts
    .filter((entry) => typeof entry.area === 'string' && typeof entry.forecast === 'string')
    .map((entry) => ({ area: entry.area, forecast: entry.forecast }))
    .sort((a, b) => a.area.localeCompare(b.area));
  // Entries that were all malformed leave nothing to show: treat that as no forecast.
  if (forecasts.length === 0) return null;
  return { forecasts, validFor: latest.valid_period?.text ?? null };
}

/** The same words the API uses for wet weather (and the backend's `context.py` checks for). */
export function isWet(forecast: string): boolean {
  return /rain|shower|thunder/i.test(forecast);
}

/** "Partly Cloudy (Day)" reads as "Partly cloudy". */
export function plainForecast(forecast: string): string {
  const words = forecast.replace(/\s*\((day|night)\)\s*$/i, '').trim();
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

/** One line of everyday advice. Never a health claim: only whether to plan indoors. */
export function weatherAdvice(forecast: string): string {
  if (isWet(forecast)) return 'Wet weather expected. An indoor activity may be easier today.';
  return 'Dry for now. A good time for a short walk or an outing.';
}
