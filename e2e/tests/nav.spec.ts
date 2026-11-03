import { expect, test, type Page } from '@playwright/test';

import { resetDemo } from './support';

// One look for the menus: no menu links on the sign-in screens, and the senior's section tabs
// styled like the family menu (a pill on a wide screen, a bottom bar on a phone) while staying tabs.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

const nav = (page: Page) => page.getByRole('navigation', { name: 'Main' });

for (const path of ['/login', '/login/family', '/signup', '/signup/senior', '/welcome']) {
  test(`${path} shows no menu links, even before a demo view is chosen`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator('main h1').first()).toBeVisible();
    await expect(nav(page)).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Calendar', exact: true })).toHaveCount(0);
  });

  test(`${path} shows no menu links after choosing the family view`, async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem('careplus.demoView.v1', 'family'));
    await page.goto(path);
    await expect(page.locator('main h1').first()).toBeVisible();
    await expect(nav(page)).toHaveCount(0);
  });
}

async function openSenior(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem('careplus.demoView.v1', 'senior'));
  await page.goto('/senior');
  await expect(page.getByRole('tablist', { name: 'My day sections' })).toBeVisible();
}

test.describe('the senior tabs on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('are one bottom bar of 56px tabs, and the top bar scrolls away', async ({ page }) => {
    await openSenior(page);
    const tabs = page.getByRole('tablist', { name: 'My day sections' });
    const box = await tabs.boundingBox();
    expect(box && Math.abs(box.y + box.height - 844) <= 2).toBe(true);
    for (const tab of await tabs.getByRole('tab').all()) {
      expect((await tab.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(56);
    }
    // Only one pinned bar: after scrolling, the top bar has gone up with the page.
    await page.evaluate(() => window.scrollTo(0, 600));
    await expect
      .poll(async () => (await page.getByRole('banner').boundingBox())?.y ?? 0)
      .toBeLessThan(0);
    await expect(tabs).toBeInViewport();
  });
});

test.describe('the senior tabs on a wide screen', () => {
  test.use({ viewport: { width: 1366, height: 900 } });

  test('are a pill like the family menu, still tabs with arrow keys', async ({ page }) => {
    await openSenior(page);
    const today = page.getByRole('tab', { name: 'Today', exact: true });
    await expect(today).toHaveAttribute('aria-selected', 'true');
    await expect(today).toHaveCSS('border-radius', /999px|9\.99e\+?02px/);
    expect((await today.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(56);
    await today.focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tab', { name: 'Calendar', exact: true })).toBeFocused();
  });
});
