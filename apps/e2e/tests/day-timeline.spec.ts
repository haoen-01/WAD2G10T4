import { expect, test } from '@playwright/test';

import { resetDemo, showMoreOnHome } from './support';

// Home's day timeline: the senior's day by the hour, live. The demo family calendar has a doctor's
// appointment tomorrow from 10:00 am to 12:00 pm that nobody has taken yet.

test.beforeEach(async ({ page, request }) => {
  await resetDemo(request);
  // The timeline sits under Home's "See more about this week".
  await showMoreOnHome(page);
});

test('an appointment that needs someone can be taken from the timeline', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const timeline = page.getByTestId('day-timeline');
  await expect(timeline).toBeVisible();
  await expect(timeline).toContainText('Live');

  await timeline.getByRole('button', { name: 'Day after' }).click();
  await timeline.getByRole('listitem', { name: /Doctor.s appointment/ }).click();
  const details = page.getByTestId('timeline-details');
  await expect(details).toContainText('10:00 am – 12:00 pm');
  await expect(details).toContainText('Still needs someone to go along');

  await page.getByTestId('timeline-go').click();
  await expect(page.getByTestId('timeline-going')).toContainText('You’re going');
  await expect(page.getByTestId('timeline-go')).toHaveCount(0);

  // Changing your mind later does not need the toast: "Can't go" stays on the card.
  await page.getByTestId('timeline-cant-go').click();
  await expect(details).toContainText('Still needs someone to go along');
  await expect(page.getByTestId('timeline-go')).toBeVisible();
});

test('ticking a task in the Tasks panel shows on the timeline at once', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const timeline = page.getByTestId('day-timeline');
  await expect(timeline).toContainText('0/5 tasks done');

  await page.getByTestId('task-panel').locator('.task-label').first().click();
  await expect(timeline).toContainText('1/5 tasks done');
});

test('an earlier day shows what she did, and Today comes back', async ({ page }) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const timeline = page.getByTestId('day-timeline');
  await timeline.getByRole('button', { name: 'Day before' }).click();
  await expect(page.getByTestId('timeline-record')).toContainText('What');
  await page.getByTestId('timeline-today').click();
  await expect(page.getByTestId('timeline-record')).toHaveCount(0);
  await expect(timeline).toContainText('Live');
});
