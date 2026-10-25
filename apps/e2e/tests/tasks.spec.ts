import { expect, test } from '@playwright/test';

import { openSettings, resetDemo } from './support';

// Tasks live in the browser, and Mdm Lim starts with a sample checklist. These tests start from
// an empty list instead, so they only see the tasks they add (set once; a reload keeps changes).
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const key = 'careplus.tasks.v1.mdm-lim';
    if (localStorage.getItem(key) === null) {
      localStorage.setItem(key, JSON.stringify({ schedules: [], completions: {} }));
    }
  });
});

test('caregiver creates a daily task, senior completes it, and changes persist', async ({
  page,
  request,
}) => {
  await resetDemo(request);
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const panel = page.getByTestId('task-panel');
  await panel.getByRole('button', { name: 'Add task', exact: true }).click();
  await panel.getByLabel('Name', { exact: true }).fill('Water the balcony plants');
  await panel.getByLabel('Repeat', { exact: true }).selectOption('daily');
  await panel.getByLabel('Notes (optional)').fill('Use the small watering can');
  // The same "Add task" button at the top now adds it: no separate save step.
  await panel.getByTestId('add-task').click();
  await expect(panel.getByRole('checkbox', { name: /Water the balcony plants/ })).toBeVisible();
  await page.reload();
  await expect(panel.getByRole('checkbox', { name: /Water the balcony plants/ })).not.toBeChecked();

  await openSettings(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  await expect(panel.getByRole('button', { name: 'Add task' })).toHaveCount(0);
  // The tick box is drawn by its label, which sits on top of the real checkbox: tap the label.
  await panel.locator('label', { hasText: 'Water the balcony plants' }).click();
  await expect(panel.getByRole('checkbox', { name: /Water the balcony plants/ })).toBeChecked();
  await page.reload();
  await expect(panel.getByRole('checkbox', { name: /Water the balcony plants/ })).toBeChecked();

  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await expect(panel.getByRole('checkbox', { name: /Water the balcony plants/ })).toBeChecked();
  await panel.getByRole('button', { name: 'Edit Water the balcony plants', exact: true }).click();
  await panel.getByLabel('Name', { exact: true }).fill('Water the herbs');
  await panel.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(panel.getByRole('checkbox', { name: /Water the herbs/ })).toBeChecked();
  // Delete deletes straight away: no confirmation dialog.
  await panel.getByRole('button', { name: 'Edit Water the herbs', exact: true }).click();
  page.on('dialog', () => {
    throw new Error('Deleting a task should not ask for confirmation');
  });
  await panel.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(panel.getByText('No tasks.', { exact: true })).toBeVisible();
  await page.reload();
  await expect(panel.getByRole('checkbox')).toHaveCount(0);
});

test('a new task shows on the calendar, where it can be edited and deleted', async ({ page }) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const panel = page.getByTestId('task-panel');
  await panel.getByRole('button', { name: 'Add task', exact: true }).click();
  await panel.getByTestId('add-task').click();
  // The name is a required field, so the browser itself stops a task with no name.
  const name = panel.getByLabel('Name', { exact: true });
  expect(await name.evaluate((input: HTMLInputElement) => input.validity.valueMissing)).toBe(true);
  await expect(panel.getByRole('checkbox')).toHaveCount(0);

  // The form's own button says "Add task" too.
  await name.fill('Call my family');
  await panel.getByTestId('task-form').getByRole('button', { name: 'Add task' }).click();
  await expect(panel.getByRole('status')).toContainText('Added to the calendar.');
  await panel.getByRole('link', { name: 'View' }).click();
  const dayTasks = page.getByTestId('day-tasks');
  await expect(dayTasks).toContainText('Call my family');

  // Edit and delete it from the calendar itself.
  await dayTasks.getByRole('button', { name: 'Edit Call my family', exact: true }).click();
  await dayTasks.getByLabel('Name', { exact: true }).fill('Call my son');
  await dayTasks.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dayTasks).toContainText('Call my son');
  await dayTasks.getByRole('button', { name: 'Edit Call my son', exact: true }).click();
  await dayTasks.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(page.getByTestId('day-tasks')).toHaveCount(0);
});

test('the task form fits a phone in portrait and landscape', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const panel = page.getByTestId('task-panel');
  await panel.getByRole('button', { name: 'Add task', exact: true }).click();
  await panel.getByLabel('Name', { exact: true }).fill('Call my family');
  await panel.getByLabel('Repeat', { exact: true }).selectOption('weekly');
  for (const [width, height] of [
    [390, 844],
    [844, 390],
  ]) {
    await page.setViewportSize({ width, height });
    await expect(
      panel.getByTestId('task-form').getByRole('button', { name: 'Add task' }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await panel.screenshot({ path: testInfo.outputPath('task-form.png') });
});
