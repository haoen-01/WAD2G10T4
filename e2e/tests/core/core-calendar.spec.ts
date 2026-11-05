import { test, expect, type Page, type Locator } from '@playwright/test';
import { resetDemo } from '../support';

const DOCTOR = /^(?!Ask someone|Withdraw|Yes, I’ll go|Can’t go).*Doctor.s appointment/;
const details = (page: Page, title: RegExp) =>
  page.locator('article').filter({ has: page.getByRole('heading', { level: 2, name: title }) });
const row = (scope: Locator, name: string) => scope.getByRole('listitem').filter({ hasText: name });

test.beforeEach(async ({ request }) => {
  await resetDemo(request); // every test starts from the same demo data
});

test('Family member takes on an appointment and it remembers', async ({ page }) => {
  await page.goto('/calendar');
  await page.getByRole('button', { name: DOCTOR }).click();
  const panel = details(page, DOCTOR);
  await page.getByRole('button', { name: "I’ll help" }).click();
  await expect(row(panel, 'Sarah')).toContainText('Helping');
  await expect(panel.getByText("You're helping with this")).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: DOCTOR }).click();
  await expect(row(panel, 'Sarah')).toContainText('Helping');
});