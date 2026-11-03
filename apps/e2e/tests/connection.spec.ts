import { expect, test, type Page } from '@playwright/test';

import { resetDemo } from './support';

// When Care+ cannot be reached, the screen says so and offers Try again. Nobody is sent to sign in
// or to "join a family group" because a request failed, and the address stays the same.

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
  await expect(page.locator('.hero-title')).toBeVisible();
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
  await expect(page.locator('.hero-title, .home')).toHaveCount(0);
  expect(viewReads).toEqual([]);
  // The panel was not mounted again, so focus stays on Try again rather than jumping to the
  // heading.
  await expect(retry).toBeFocused();
  await expect(page).toHaveURL('/');
});
