import { expect, test } from '@playwright/test';

import { resetDemo } from './support';

// The calendar's month grid keeps to appointments and one-off tasks: the demo's daily tasks (the
// blood pressure tablet, the water, the stretching) would otherwise fill every cell. And choosing an
// empty day from today on opens the add form for that day.

test.use({ viewport: { width: 1366, height: 900 } });

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

test('repeating tasks stay off the month grid until asked for, and the day still lists them', async ({
  page,
}) => {
  await page.goto('/calendar');
  const toggle = page.getByTestId('show-repeating');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('.cal-day:not(.past) .cal-chip.kind-task')).toHaveCount(0);
  // The chosen day (today) still lists its tasks.
  await expect(page.getByTestId('day-tasks')).toContainText('Blood pressure tablet');

  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.cal-day:not(.past) .cal-chip.kind-task').first()).toBeVisible();

  // Remembered in this browser.
  await page.reload();
  await expect(page.getByTestId('show-repeating')).toHaveAttribute('aria-pressed', 'true');
});

test('choosing an empty future day opens the add form with that date', async ({ page }) => {
  await page.goto('/calendar');
  // Wait for the appointments, so an empty day really is empty.
  await expect(page.locator('.cal-day .cal-chip:not(.kind-task)').first()).toBeVisible();
  const candidate = page
    .locator(
      '.cal-day:not(.past):not(.today)[aria-label*="nothing planned"], .cal-day:not(.past):not(.today)[aria-label*="no appointments"]',
    )
    .first();
  const iso = (await candidate.getAttribute('data-iso'))!;
  const empty = page.locator(`.cal-day[data-iso="${iso}"]`);
  expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}$/);

  await empty.click();
  await expect(page.getByLabel('Date', { exact: true })).toHaveValue(iso);
  // Focus stays on the day that was chosen.
  await expect(page.locator(`.cal-day[data-iso="${iso}"]`)).toBeFocused();

  // A day with an appointment opens its list, not the form.
  await page.keyboard.press('Escape');
  await expect(page.getByLabel('Date', { exact: true })).toHaveCount(0);
  const booked = page
    .locator('.cal-day:not(.past)')
    .filter({ has: page.locator('.cal-chip:not(.kind-task)') })
    .first();
  await booked.click();
  await expect(page.getByLabel('Date', { exact: true })).toHaveCount(0);
});

test('a form that opened by itself never takes over the next day clicked', async ({ page }) => {
  await page.goto('/calendar');
  await expect(page.locator('.cal-day .cal-chip:not(.kind-task)').first()).toBeVisible();
  const emptyDays = page.locator(
    '.cal-day:not(.past):not(.today)[aria-label*="nothing planned"], .cal-day:not(.past):not(.today)[aria-label*="no appointments"]',
  );
  const first = (await emptyDays.nth(0).getAttribute('data-iso'))!;
  const second = (await emptyDays.nth(1).getAttribute('data-iso'))!;
  const date = page.getByLabel('Date', { exact: true });

  await page.locator(`.cal-day[data-iso="${first}"]`).click();
  await expect(date).toHaveValue(first);

  // A booked day is shown, and the untouched form that opened by itself closes.
  const booked = page
    .locator('.cal-day:not(.past)')
    .filter({ has: page.locator('.cal-chip:not(.kind-task)') })
    .first();
  await booked.click();
  await expect(booked).toHaveAttribute('aria-pressed', 'true');
  await expect(date).toHaveCount(0);

  // Another empty day opens the form for that day, not the first one.
  await page.locator(`.cal-day[data-iso="${second}"]`).click();
  await expect(date).toHaveValue(second);

  // Once the person starts filling it in, the form is theirs: a day click moves its date.
  await page.getByLabel('What', { exact: true }).fill('Lunch with Mei');
  await page.locator(`.cal-day[data-iso="${first}"]`).click();
  await expect(date).toHaveValue(first);
  await expect(page.getByLabel('What', { exact: true })).toHaveValue('Lunch with Mei');
});
