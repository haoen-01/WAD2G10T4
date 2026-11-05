import { test, expect } from '@playwright/test';
import { resetDemo } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('family member login and lands on the Home Page', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Get started' }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('navigation', { name: 'Main' }).first().getByRole('link')).toHaveText([
  'Home', 'Watch', 'Walk', 'Calendar', 'Family',
]);
});