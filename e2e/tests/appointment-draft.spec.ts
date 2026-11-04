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

for (const [typed, from, to] of [
  ['Hearing test tomorrow at 2', '14:00', '15:00'],
  ['Hearing test tomorrow at 2:30 PM', '14:30', '15:30'],
  ['Hearing test tomorrow 14:30', '14:30', '15:30'],
  ['Hearing test tomorrow at noon', '12:00', '13:00'],
] as const) {
  test(`"${typed}" fills in the time and keeps the day`, async ({ page, request }) => {
    await page.goto('/calendar');
    await page.getByTestId('add-appointment').click();
    const form = page.getByTestId('appointment-form');
    await form.getByTestId('describe-text').fill(typed);
    await form.getByTestId('describe-fill').click();
    await expect(form.getByTestId('describe-result')).toContainText(
      'Nothing is saved until you press Add.',
    );
    await expect(form.getByLabel('Date', { exact: true })).toHaveValue(isoDay(1));
    await expect(form.getByLabel('From', { exact: true })).toHaveValue(from);
    await expect(form.getByLabel('To', { exact: true })).toHaveValue(to);
    await expect(form.getByTestId('add-title')).toHaveValue('Hearing test');
    expect(await titles(request)).not.toContain('Hearing test');
  });
}

test('filled-in fields can be edited, and what you typed yourself is never overwritten', async ({
  page,
  request,
}) => {
  await page.goto('/calendar');
  await page.getByTestId('add-appointment').click();
  const form = page.getByTestId('appointment-form');
  // Typed by hand first: a fill must keep these.
  await form.getByTestId('add-title').fill('Teeth cleaning');
  await form.getByLabel('Where (optional)').fill('Tampines clinic');

  await form
    .getByTestId('describe-text')
    .fill('Dental check tomorrow 10:30 to 11:30 at Bedok Polyclinic');
  await form.getByTestId('describe-fill').click();
  const result = form.getByTestId('describe-result');
  await expect(result).toContainText('Kept what you had typed for what it is and the place.');
  await expect(form.getByTestId('add-title')).toHaveValue('Teeth cleaning');
  await expect(form.getByLabel('Where (optional)')).toHaveValue('Tampines clinic');
  await expect(form.getByLabel('From', { exact: true })).toHaveValue('10:30');

  // Every filled-in field stays editable before saving.
  await form.getByLabel('To', { exact: true }).fill('12:00');
  await form.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Added Teeth cleaning' })).toBeVisible();
  expect(await titles(request)).toContain('Teeth cleaning');
});

test('when filling in fails, it says why, changes nothing, and the form still saves by hand', async ({
  page,
  request,
}) => {
  // The fill-in request fails on the server (as with a provider or configuration problem).
  await page.route('**/appointments/draft', (route) =>
    route.fulfill({ status: 500, json: { code: 'internal_error', message: 'x', detail: null } }),
  );
  await page.goto('/calendar');
  await page.getByTestId('add-appointment').click();
  const form = page.getByTestId('appointment-form');
  await form.getByTestId('add-title').fill('Haircut');
  await form.getByTestId('describe-text').fill('haircut tomorrow 3pm');
  await form.getByTestId('describe-fill').click();

  const alert = form.getByRole('alert').first();
  await expect(alert).toContainText('Care+ had a problem reading that, so nothing was changed.');
  await expect(form.getByTestId('add-title')).toHaveValue('Haircut');

  // Manual entry and saving need no AI at all.
  await form.getByLabel('Date', { exact: true }).fill(isoDay(2));
  await form.getByLabel('From', { exact: true }).fill('15:00');
  await form.getByLabel('To', { exact: true }).fill('15:30');
  await form.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Added Haircut' })).toBeVisible();
  expect(await titles(request)).toContain('Haircut');
});

test('a fill-in that cannot reach Care+ says so, not that the words could not be read', async ({
  page,
}) => {
  await page.route('**/appointments/draft', (route) => route.abort('internetdisconnected'));
  await page.goto('/calendar');
  await page.getByTestId('add-appointment').click();
  const form = page.getByTestId('appointment-form');
  await form.getByTestId('describe-text').fill('haircut tomorrow 3pm');
  await form.getByTestId('describe-fill').click();
  await expect(form.getByRole('alert').first()).toContainText('Care+ could not be reached');
});
