import { expect, test } from '@playwright/test';

// Backs the "All four product routes pass at a 390 x 844 Chromium viewport without horizontal
// overflow" line in docs/manual-ui-checklist.md, which used to describe Simulator-era coverage
// that no longer exists. 390 x 844 is the checklist's own iPhone-class viewport.

const ROUTES = ['/', '/senior', '/calendar', '/family'];

test.use({ viewport: { width: 390, height: 844 } });

for (const route of ROUTES) {
  test(`${route || '/'} has no horizontal overflow at 390px`, async ({ page }) => {
    await page.goto(route);
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  });
}
