import { expect, type APIRequestContext, type Page } from '@playwright/test';

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

/**
 * Removes every task from the demo senior's family group (the reset gives it a sample checklist),
 * so a test sees only the tasks it adds. Returns the group's id for `addDemoTask`.
 */
export async function clearDemoTasks(request: APIRequestContext): Promise<string> {
  const list = await request.get(`${API_URL}/v1/people/mdm-lim/tasks`);
  expect(list.ok()).toBe(true);
  const { group_id: groupId, tasks } = (await list.json()) as {
    group_id: string;
    tasks: { task_id: string }[];
  };
  for (const task of tasks) {
    const deleted = await request.post(
      `${API_URL}/v1/groups/${groupId}/tasks/${task.task_id}/delete`,
    );
    expect(deleted.ok()).toBe(true);
  }
  return groupId;
}

/** Adds a task to the demo group straight through the API. */
export async function addDemoTask(
  request: APIRequestContext,
  groupId: string,
  task: { title: string; start_date: string; time: string; repeat?: string },
) {
  const response = await request.post(`${API_URL}/v1/groups/${groupId}/tasks`, { data: task });
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

/**
 * Opens the family header's Settings popover (zoom, light or dark, Sign out) and returns it. The
 * senior keeps those controls in the top bar, so a senior test does not call this.
 */
export async function openSettings(page: Page) {
  const button = page.getByRole('button', { name: 'Settings', exact: true });
  if ((await button.getAttribute('aria-expanded')) !== 'true') await button.click();
  const panel = page.getByRole('group', { name: 'Settings' });
  await expect(panel).toBeVisible();
  return panel;
}
