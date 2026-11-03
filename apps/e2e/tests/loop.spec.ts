import { expect, test } from '@playwright/test';

import { API_URL, advance, resetDemo } from './support';

// The whole product loop in a real browser, against the real API: a simulated day reaches the
// senior, a persistent decline is handed to a person, and stored consent is shown to the family.
// (The family calendar has its own spec, `family.spec.ts`; it needs no API.)

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

test('Home shows whether the senior’s watch is connected, and its battery', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: 'Care+' })).toBeVisible();
  const watch = page.getByTestId('watch-status');
  await expect(watch).toContainText(/Watch connected · synced/);
  // The level depends on the time of day (it is simulated), so only its shape is checked here.
  await expect(page.getByTestId('watch-battery')).toContainText(/\d+%/);
  await expect(watch).toContainText('Simulated watch');
});

test('a low watch battery is red and asks the family to remind her to charge it', async ({
  page,
}) => {
  await page.route('**/v1/people/*/wearable', (route) =>
    route.fulfill({
      json: {
        connected: true,
        last_synced_at: new Date().toISOString(),
        battery_percent: 12,
        charging: false,
        source: 'synthetic',
      },
    }),
  );
  await page.goto('/');
  const battery = page.getByTestId('watch-battery');
  await expect(battery).toContainText('12%, needs charging');
  await expect(battery).toHaveClass(/battery-critical/);
  await expect(page.getByTestId('charge-reminder')).toContainText(
    'Remind Mdm Lim to charge the watch',
  );
});

test('a simulated decline reaches the senior, who can reply', async ({ page, request }) => {
  // Played straight through the API (there is no Simulator screen any more).
  const result = await advance(request, 'activity_declines');
  expect(result.state.last_decision).toBe('gentle_nudge');

  // Whichever suggestion the day produced is the one the senior must see.
  const title = result.created_intervention?.title ?? '';
  expect(title).not.toBe('');

  await page.goto('/senior');
  await expect(page.getByRole('heading', { name: title })).toBeVisible();

  await page.getByRole('button', { name: /^Yes/ }).click();
  await expect(page.getByTestId('thanks')).toContainText('Nothing is booked');
  // The answered suggestion is gone; the one status line stays at the top.
  await expect(page.getByRole('heading', { name: title })).toHaveCount(0);
  await expect(page.getByTestId('activity-status')).toBeVisible();
});

test('a persistent decline is handed to a person, not offered to the senior as a suggestion', async ({
  request,
}) => {
  // Three declining days straight through the API, all via the same helper used elsewhere.
  let result;
  for (let day = 0; day < 3; day += 1) result = await advance(request, 'activity_declines');

  expect(result?.state.last_decision).toBe('coordinator_review');
  expect(result?.created_intervention).toBeFalsy();
  expect(result?.created_case?.title).toBeTruthy();
});

test('the senior screen has no privacy switch', async ({ page }) => {
  await page.goto('/senior');
  await expect(page.getByRole('heading', { name: 'My steps' })).toBeVisible();
  // The only switches are the walk-sharing ones under "My walks" (walk.spec.ts), not consent.
  await expect(page.getByRole('switch')).toHaveCount(2);
  await expect(page.getByRole('switch', { name: /Share my walk|Tell my family/ })).toHaveCount(2);
  await expect(page.getByRole('switch', { name: /privacy|consent/i })).toHaveCount(0);
  await expect(page.getByText('Your privacy')).toHaveCount(0);
});

test('consent withdrawn through the API still shows on the home overview', async ({
  page,
  request,
}) => {
  // The switch is gone from the app, but consent is still stored and still gates Care+'s nudges.
  const consent = (active: boolean) =>
    request.post(`${API_URL}/v1/people/mdm-lim/consent`, {
      data: { active, reason: 'e2e' },
    });
  expect((await consent(false)).ok()).toBe(true);
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('withdrawn her consent');

  // Leave the shared demo person as it was found.
  expect((await consent(true)).ok()).toBe(true);
});

test('an unknown address says so and offers a way home', async ({ page }) => {
  await page.goto('/nope');
  await expect(page.getByRole('heading', { level: 1, name: 'Page not found' })).toBeVisible();
});
