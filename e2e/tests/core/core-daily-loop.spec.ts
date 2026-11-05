import { test, expect } from '@playwright/test';
import { advance, resetDemo } from '../support';

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('a quiet day becomes a suggestion, and the senior answers it', async ({ page, request }) => {
  const result = await advance(request, 'activity_declines');
  expect(result.state.last_decision).toBe('gentle_nudge');
  const title = result.created_intervention?.title ?? '';
  expect(title).not.toBe('');
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  await expect(page.getByRole('heading', { name: title })).toBeVisible();
  await page.getByRole('button', { name: /^Yes/ }).click();
  await expect(page.getByTestId('thanks')).toContainText('Nothing is booked');
  await expect(page.getByRole('heading', { name: title })).toHaveCount(0);
});
