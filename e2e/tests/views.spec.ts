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
  await expect(page.getByRole('heading', { name: 'My steps' })).toBeVisible();
  await expect(page.getByTestId('steps-today')).not.toBeEmpty();
  await expect(page.getByRole('heading', { name: 'Next up' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Today', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(page.getByRole('button', { name: 'Show more details' })).toHaveCount(0);
  await page.getByRole('button', { name: 'See my calendar' }).click();
  await expect(page.getByRole('heading', { name: 'My calendar' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'My steps' })).toBeHidden();
  await page.reload();
  await expect(page.getByRole('tab', { name: 'Calendar', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await page.getByRole('tab', { name: 'Calendar', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: /^Badges/ })).toBeFocused();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Family', exact: true })).toBeFocused();
  await expect(page.getByTestId('add-family-member')).toHaveCount(1);
  await page.getByTestId('add-family-member').click();
  await expect(page.getByTestId('senior-link-pin')).toBeVisible();
  await expect(page.getByText('Link your family', { exact: true })).toHaveCount(0);
  await page.keyboard.press('Home');
  await page.getByRole('tab', { name: 'Today', exact: true }).click();
  // One plain sentence first; the week's chart is behind "See my week".
  await expect(page.getByTestId('activity-status')).toHaveText(/^You walked /);
  const seeWeek = page.getByTestId('see-my-week');
  await expect(seeWeek).toHaveAttribute('aria-expanded', 'false');
  await seeWeek.click();
  await expect(seeWeek).toHaveAttribute('aria-expanded', 'true');
  const chart = page.getByRole('group', { name: 'Steps on each day. Choose a day for details.' });
  const bars = chart.getByRole('button');
  await expect(bars).toHaveCount(7);
  await bars.first().hover();
  await expect(chart.locator('.chart-tip')).toBeVisible();
  await bars.first().focus();
  await expect(chart.locator('.chart-tip')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expect(bars.nth(1)).toBeFocused();
  await expect(bars.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await bars.last().click();
  await expect(bars.last()).toHaveAttribute('aria-pressed', 'true');
  const detailId = await bars.last().getAttribute('aria-controls');
  await expect(page.locator(`[id="${detailId}"]`)).toContainText('active minutes');
  await page.evaluate(() => {
    document.documentElement.dataset.bsTheme = 'dark';
    document.documentElement.style.zoom = '1.5';
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => {
    document.documentElement.style.zoom = '1';
  });
  await page.addInitScript(() => {
    const get = Storage.prototype.getItem;
    const set = Storage.prototype.setItem;
    Storage.prototype.getItem = function (key) {
      if (key === 'careplus.seniorTab.v1') throw new Error('Storage unavailable');
      return get.call(this, key);
    };
    Storage.prototype.setItem = function (key, value) {
      if (key === 'careplus.seniorTab.v1') throw new Error('Storage unavailable');
      set.call(this, key, value);
    };
  });
  await page.reload();
  await expect(page.getByRole('tab', { name: 'Today', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await page.getByRole('tab', { name: 'Calendar', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'My calendar' })).toBeVisible();

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
