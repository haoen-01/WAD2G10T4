import { test, expect } from '@playwright/test';
import { resetDemo } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('Asking kaki how many steps today', async ({ page }) => {
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  await page.getByTestId('assistant-orb').click();
  await page.getByRole('button', { name: 'How many steps today?' }).click();
  await expect(page.getByTestId('assistant-assistant').last()).toContainText(
    /your watch counted [\d,]+ steps/,
  );
});
