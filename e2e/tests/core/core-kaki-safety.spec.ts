import { test, expect } from '@playwright/test';
import { resetDemo } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('Kaki to tell Senior to call 995', async ({ page }) => {
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  await page.getByTestId('assistant-orb').click();
  await page.getByTestId('assistant-input').fill('I fell down and my hip hurts');
  await page.getByTestId('assistant-input').press('Enter');
  await expect(page.getByTestId('assistant-assistant').last()).toContainText('call 995');
});
