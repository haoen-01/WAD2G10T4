import { test, expect } from '@playwright/test';
import { resetDemo } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('family member cannot bypass and swap to senior screen', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Get started' }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await page.goto('/senior');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('navigation', { name: 'Main' }).first().getByRole('link')).toHaveText(
    ['Home', 'Watch', 'Walk', 'Calendar', 'Family'],
  );
});
