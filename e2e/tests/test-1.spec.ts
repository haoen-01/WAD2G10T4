import { test, expect } from '@playwright/test';

test('saying i cannot make it, then changing your mind', async ({ page }) => {
  await page.goto('http://localhost:3000/calendar');
  
  await page.getByRole('button', { name: 'I can’t make it' }).click();
  await page.getByRole('button', { name: 'I’m available' }).click();
});