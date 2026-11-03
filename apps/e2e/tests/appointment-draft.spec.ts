import { expect, test, type APIRequestContext } from '@playwright/test';

import { API_URL, isoDay, resetDemo } from './support';

// "Describe it" on the new-appointment form. The e2e run keeps LLM_ENABLED=false, so a plain
// parser fills in the form and must say so; the agent path is covered by the API tests.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

async function titles(request: APIRequestContext): Promise<string[]> {
  const response = await request.get(`${API_URL}/v1/people/mdm-lim/calendar`, {
    headers: { 'X-Demo-Sub': 'demo-family' },
  });
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as { appointments: { title: string }[] };
  return body.appointments.map((item) => item.title);
}

test('a typed sentence fills in the form, and only Add saves it', async ({ page, request }) => {
  await page.goto('/calendar');
  await page.getByTestId('add-appointment').click();
  const form = page.getByTestId('appointment-form');
  await form
    .getByTestId('describe-text')
    .fill('Dental check tomorrow 10:30 to 11:30 at Bedok Polyclinic');
  await form.getByTestId('describe-fill').click();

  const result = form.getByTestId('describe-result');
  await expect(result).toHaveAttribute('data-mode', 'fallback_disabled');
  await expect(result).toContainText('Filled in by Care+ from the words it recognised.');
  await expect(result).toContainText('Nothing is saved until you press Add.');
  await expect(result).not.toContainText('assistant');

  await expect(form.getByTestId('add-title')).toHaveValue('Dental check');
  await expect(form.getByLabel('Date', { exact: true })).toHaveValue(isoDay(1));
  await expect(form.getByLabel('From', { exact: true })).toHaveValue('10:30');
  await expect(form.getByLabel('To', { exact: true })).toHaveValue('11:30');
  await expect(form.getByLabel('Where (optional)')).toHaveValue('Bedok Polyclinic');
  expect(await titles(request)).not.toContain('Dental check');

  await form.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Added Dental check' })).toBeVisible();
  expect(await titles(request)).toContain('Dental check');
});
