import { expect, test, type Page } from '@playwright/test';

import { resetDemo } from './support';

// The two views: the family's (Home, Calendar, Family) and the senior's own screen. The e2e run has
// sign-in off, so each sign-in page offers "Continue as" instead of a password; with sign-in on the
// same pages take a password and check the account's role.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

const nav = (page: Page) => page.getByRole('navigation', { name: 'Main' });

async function enterAs(page: Page, audience: 'family' | 'senior') {
  await page.goto('/login');
  await page.getByTestId(`choose-${audience}`).click();
  await expect(page).toHaveURL(new RegExp(`/login/${audience}$`));
  await page.getByTestId(`continue-${audience}`).click();
}

test('the family sees Home, Walk, Calendar and Family, and never the senior screen', async ({
  page,
}) => {
  await enterAs(page, 'family');
  await expect(page).toHaveURL(/\/$/);

  await expect(nav(page).getByRole('link')).toHaveText(['Home', 'Walk', 'Calendar', 'Family']);

  await page.goto('/senior');
  await expect(page).toHaveURL(/\/$/);
});

test('the senior sees only their day: activity, a suggestion and today’s plans', async ({
  page,
}) => {
  await enterAs(page, 'senior');
  await expect(page).toHaveURL(/\/senior$/);

  await expect(nav(page).getByRole('link')).toHaveText(['My day']);
  await expect(page.getByRole('heading', { name: 'Your activity' })).toBeVisible();
  await expect(page.getByTestId('steps-today')).not.toBeEmpty();
  await expect(page.getByRole('heading', { name: 'Today’s activities' })).toBeVisible();

  for (const path of ['/', '/walk', '/calendar', '/family']) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/senior$/);
  }
});

test('signing out goes back to choosing who is signing in', async ({ page }) => {
  await enterAs(page, 'senior');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByTestId('choose-family')).toBeVisible();
});
