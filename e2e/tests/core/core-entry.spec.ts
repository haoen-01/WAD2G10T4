import { test, expect } from '@playwright/test';
import { resetDemo } from '../support';

test('test', async ({ page }) => {
  await page.goto('http://localhost:3000/login');
  await page.getByRole('link', { name: 'Get started' }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await expect(page).toHaveURL(/\/$/)
});

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});