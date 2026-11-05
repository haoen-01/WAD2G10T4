import { expect, test, type Page } from '@playwright/test';

import { resetDemo } from './support';

// When Care+ cannot be reached, the screen says so and offers Try again. Nobody is sent to sign in
// or to "join a family group" because a request failed, and the address stays the same.
//
// The e2e run has sign-in off, so the request the guard makes is `GET /v1/me` (the family view
// reads it to know whether this member is in a family group yet). The same decision covers
// `GET /v1/auth/me` with sign-in on; `client/src/lib/route-guard.test.ts` pins that side.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

/** Enters the demo as the family before the page loads (sign-in is off in the e2e run). */
async function asFamily(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem('careplus.demoView.v1', 'family'));
}

test('an unreachable /v1/me shows the connection panel, keeps the URL, and Try again recovers', async ({
  page,
}) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) => route.abort());
  await page.goto('/');

  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute('role', 'alert');
  await expect(
    panel.getByRole('heading', { name: 'Can’t connect to Care+ right now' }),
  ).toBeFocused();
  await expect(panel).toContainText('Care+ could not reach its service.');
  await expect(page).toHaveURL('/');
  // Not sent to "join a family group", and the menu links are hidden meanwhile.
  await expect(page.getByRole('heading', { name: /family group/i })).toHaveCount(0);
  await expect(page.getByRole('navigation', { name: 'Main' })).toHaveCount(0);

  await page.unroute('**/v1/me');
  await panel.getByRole('button', { name: 'Try again' }).click();
  await expect(panel).toHaveCount(0);
  await expect(page).toHaveURL('/');
  await expect(page.locator('.home')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible();
});

test('a server error on /v1/me shows the panel on a deep link, not the group start page', async ({
  page,
}) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) =>
    route.fulfill({
      status: 503,
      body: 'down',
      headers: { 'Access-Control-Allow-Origin': '*' },
    }),
  );
  await page.goto('/calendar');
  await expect(page.getByTestId('connection-problem')).toBeVisible();
  await expect(page).toHaveURL('/calendar');
  await expect(page.getByTestId('connection-problem')).toContainText(
    'Care+ could not complete this request.',
  );
});

test('a retry that fails again keeps the panel, mounts no screen, and leaves focus alone', async ({
  page,
}) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) => route.abort());
  await page.goto('/');

  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();
  const retry = panel.getByRole('button', { name: 'Try again' });
  await retry.focus();

  // Count what Home would read if it mounted behind the panel.
  const viewReads: string[] = [];
  page.on('request', (request) => {
    if (/\/v1\/(people|groups)\//.test(request.url())) viewReads.push(request.url());
  });
  await retry.click();
  await expect(retry).toHaveText(/Try again/);
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('status')).toHaveText(/Still can’t connect/);
  await expect(page.locator('.home')).toHaveCount(0);
  expect(viewReads).toEqual([]);
  // The panel was not mounted again, so focus stays on Try again rather than jumping to the
  // heading.
  await expect(retry).toBeFocused();
  await expect(page).toHaveURL('/');
});

test('a reload that cannot reach Care+ keeps the family view and offers Sign out, not Sign in', async ({
  page,
}) => {
  await asFamily(page);
  await page.goto('/family');
  await expect(page.locator('h1').first()).toBeVisible();

  await page.route('**/v1/me', (route) => route.abort());
  await page.reload();
  await expect(page.getByTestId('connection-problem')).toBeVisible();
  await expect(page).toHaveURL('/family');
  await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign in' })).toHaveCount(0);

  // No horizontal scroll on a phone.
  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const box = await page.getByTestId('connection-retry').boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});
