import { test, expect } from '@playwright/test';
import { resetDemo, openSettings } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('Family adds a daily task for the senior; Senior ticks it off and its saved', async ({
  page,
}) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const panel = page.getByTestId('task-panel');
  await panel.getByRole('button', { name: 'Add task', exact: true });
  await panel.getByRole('textbox', { name: 'Name' }).click();
  await panel.getByRole('textbox', { name: 'Name' }).fill('Water the plants');
  await panel.getByLabel('Repeat').selectOption('daily');
  await panel.getByTestId('task-form').getByRole('button', { name: 'Add task' }).click();
  await openSettings(page);
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByRole('link', { name: 'Get started' }).click();
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  await page.getByRole('button', { name: 'Mark Water the plants done' }).click();
  await page.reload();
  await expect(
    panel.getByRole('button', { name: 'Mark Water the plants not done' }),
  ).toHaveAttribute('aria-pressed', 'true');
});
