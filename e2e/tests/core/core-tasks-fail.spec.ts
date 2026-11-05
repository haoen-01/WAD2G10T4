import { test, expect } from '@playwright/test';
import { resetDemo, clearDemoTasks } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
  await clearDemoTasks(request);
});

test('Task with no name is not added', async ({ page }) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const panel = page.getByTestId('task-panel');
  await panel.getByRole('button', { name: 'Add task', exact: true }).click();
  await page.getByTestId('add-task').click();
  await expect(panel.getByRole('checkbox')).toHaveCount(0);
  await expect(panel.getByLabel('Name', { exact: true })).toBeVisible(); // shows that the app kept the form open for the user to fix
});