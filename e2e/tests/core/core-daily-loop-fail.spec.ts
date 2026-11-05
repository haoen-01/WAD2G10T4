import { test, expect } from '@playwright/test';
import { advance, resetDemo } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('a day the watch was not worn gives no suggestion', async ({ page, request }) => {
  const result = await advance(request, 'low_wear');
  expect(result.state.last_decision).toBe('no_action');
  expect(result.created_intervention).toBeFalsy();
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  await expect(page.getByRole('heading', { name: 'My steps' })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Yes/ })).toHaveCount(0);
});