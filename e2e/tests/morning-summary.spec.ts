import { expect, test, type Page } from '@playwright/test';

import { advance, resetDemo } from './support';

// The morning summary on Home (lib/morning-summary.ts), and Home's shorter layout on a phone.
// The config starts every spec with the summary switched off; this file starts with it on.

test.use({ storageState: { cookies: [], origins: [] } });

async function enterAsFamily(page: Page) {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await expect(page).toHaveURL(/\/$/);
}

const summary = (page: Page) => page.getByRole('dialog', { name: /day, in brief/ });

test('the summary opens once a day with the latest day, a verdict and today’s list', async ({
  page,
  request,
}) => {
  await resetDemo(request);
  await enterAsFamily(page);

  const dialog = summary(page);
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Mdm Lim’s day, in brief');
  await expect(dialog).toContainText(/% of a usual day/);
  await expect(dialog.getByTestId('morning-verdict')).toContainText(
    /All’s good\.|Keep an eye on it\.|Keep monitoring\./,
  );
  await expect(dialog.getByRole('heading', { name: 'Today' })).toBeVisible();
  // Focus starts on the title, so the panel opens at its top, and Escape closes it.
  await expect(dialog.getByRole('heading', { name: /day, in brief/ })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();

  // Not again today, even after a reload.
  await page.reload();
  await expect(page.getByTestId('open-morning-summary')).toBeVisible();
  await expect(summary(page)).toBeHidden();

  // The button opens it at any time; "Got it" closes it.
  await page.getByTestId('open-morning-summary').click();
  await expect(summary(page)).toBeVisible();
  await summary(page).getByTestId('morning-close').click();
  await expect(summary(page)).toBeHidden();
});

test('a day the watch was not worn enough is not called good', async ({ page, request }) => {
  await resetDemo(request);
  await advance(request, 'low_wear');
  await enterAsFamily(page);
  const verdict = summary(page).getByTestId('morning-verdict');
  await expect(verdict).toContainText('Not enough watch wear to compare.');
  await expect(verdict).not.toContainText('All’s good');
  await expect(summary(page)).not.toContainText('% of a usual day');
});

test('"Show this each morning" off is remembered', async ({ page, request }) => {
  await resetDemo(request);
  await enterAsFamily(page);
  await expect(summary(page)).toBeVisible();
  await summary(page).getByLabel('Show this each morning').uncheck();
  await summary(page).getByTestId('morning-close').click();
  const stored = await page.evaluate(() => localStorage.getItem('careplus.morning.v1'));
  expect(stored).toBe('off');
});

test.describe('Home on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('tasks come before the family updates, which start folded, and the week is a link', async ({
    page,
    request,
  }) => {
    await resetDemo(request);
    await page.addInitScript(() => localStorage.setItem('careplus.morning.v1', 'off'));
    await enterAsFamily(page);

    const tasks = page.locator('#home-tasks');
    const feed = page.locator('#home-feed');
    await expect(tasks).toBeVisible();
    await expect(feed).toBeVisible();
    const tasksBox = await tasks.boundingBox();
    const feedBox = await feed.boundingBox();
    expect(tasksBox && feedBox && tasksBox.y < feedBox.y).toBe(true);

    // Folded: one line, and a button that opens the rest.
    const toggle = feed.getByTestId('feed-toggle');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(feed.getByTestId('feed-preview')).toBeVisible();
    await expect(page.locator('#home-feed-list')).toBeHidden();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#home-feed-list')).toBeVisible();

    // No week grid on a phone: one link to the calendar.
    await expect(page.locator('#home-week')).toHaveCount(0);
    await page.getByTestId('week-link').click();
    await expect(page).toHaveURL(/\/calendar$/);
  });
});
