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
  await page.getByRole('link', { name: 'Calendar' }).click();
  await page.getByRole('button', { name: 'Friday, 6 November: 1' }).click();
  await page.getByRole('button', { name: "10:00 am – 12:00 pm Doctor’s" }).click();
  await page.getByRole('button', { name: "I’ll help" }).click();
  await page.getByText("You’re helping with this,").click();
  await page.locator('#main').press('Tab');
  await page.goto('http://localhost:3000/calendar');
});