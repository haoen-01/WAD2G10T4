import { test, expect } from '@playwright/test';
import { resetDemo } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('Task with no name is not added', async ({ page }) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const panel = page.getByTestId('task-panel');
  await page.getByTestId('add-task').click();
  await expect(panel.getByRole('checkbox')).toHaveCount(0);
});