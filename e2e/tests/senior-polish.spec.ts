import { expect, test } from '@playwright/test';

import { advance, resetDemo } from './support';

// The senior screen is for older readers: the answers to a suggestion must be big targets, and the
// app's own zoom setting (up to 150%) must not push the page sideways.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
  await advance(request, 'activity_declines');
});

test('the suggestion answers are at least 56px tall on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/senior');
  const yes = page.getByRole('button', { name: /^Yes/ });
  const notNow = page.getByRole('button', { name: 'Not for me' });
  const read = page.getByRole('button', { name: 'Read this to me' });
  for (const button of [yes, notNow, read]) {
    await expect(button).toBeVisible();
    const box = await button.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(56);
  }
});

test('the senior screen has no horizontal overflow at 150% zoom', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('careplus.zoom.v1', '150'));
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/senior');
  await expect(page.getByRole('button', { name: /^Yes/ })).toBeVisible();
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});
