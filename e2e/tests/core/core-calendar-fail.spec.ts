import { test, expect, type Page, type Locator } from '@playwright/test';
import { resetDemo } from '../support';

const DOCTOR = /^(?!Ask someone|Withdraw|Yes, I’ll go|Can’t go).*Doctor.s appointment/;
const details = (page: Page, title: RegExp) =>
  page.locator('article').filter({ has: page.getByRole('heading', { level: 2, name: title }) });
const row = (scope: Locator, name: string) => scope.getByRole('listitem').filter({ hasText: name });

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('saying i cannot make it, then changing your mind', async ({ page }) => {
  await page.goto('/calendar');
  await page.getByRole('button', { name: DOCTOR }).click();
  const panel = details(page, DOCTOR);

  await page.getByRole('button', { name: 'I can’t make it' }).click();
  await expect(row(panel, 'Sarah')).toContainText('Not available');
  await page.getByRole('button', { name: 'I’m available' }).click();
  await expect(row(panel, 'Sarah')).toContainText('Available');
  await expect(row(panel, 'Sarah')).not.toContainText('Not available');
});
