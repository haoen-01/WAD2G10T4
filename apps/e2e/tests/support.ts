import { expect, type APIRequestContext } from '@playwright/test';

/**
 * Shared by the specs in this directory. Not a spec itself (no `.spec.ts`), so Playwright never
 * collects it as tests.
 */

// Mirrors `playwright.config.ts`: the API under test is whichever port the config started.
export const API_PORT = process.env.E2E_API_PORT ?? '8000';
export const API_URL = `http://127.0.0.1:${API_PORT}`;

/** The day `offset` days from today, `YYYY-MM-DD`: the demo schedule is relative to today. */
export function isoDay(offset: number): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/** One day of a demo appointment, as the calendar links to it (`demo-taichi` on day 2, say). */
export const demoOccurrence = (key: string, offset: number) => `${key}@${isoDay(offset)}`;

/** Resets one person's run (the API's default demo person when omitted). */
export async function resetDemo(request: APIRequestContext, personId?: string) {
  const response = await request.post(`${API_URL}/v1/demo/reset`, {
    params: personId ? { person_id: personId } : undefined,
  });
  expect(response.ok()).toBe(true);
}

/** The parts of the API's `AdvanceResponse` these tests read. */
export interface AdvanceResult {
  state: { last_decision: string };
  created_intervention: { title: string } | null;
  created_case: { title: string } | null;
}

/**
 * Plays one simulated day straight through the API, so a test can set the scene without clicking
 * (there is no Simulator screen any more). Returns the decoded response body.
 */
export async function advance(
  request: APIRequestContext,
  event: string,
  personId = 'mdm-lim',
): Promise<AdvanceResult> {
  const response = await request.post(`${API_URL}/v1/simulation/advance`, {
    data: { event, event_id: crypto.randomUUID(), person_id: personId },
  });
  expect(response.ok()).toBe(true);
  return response.json();
}
