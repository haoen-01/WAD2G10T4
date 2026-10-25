import { expect, test } from '@playwright/test';

// The sign-in and onboarding screens on a phone: nothing spills sideways and the two big
// "who is signing in" choices are comfortable to tap.

test.use({ viewport: { width: 375, height: 812 } });

for (const path of ['/login', '/signup', '/welcome', '/groups/start']) {
  test(`${path} has no horizontal overflow at 375px`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator('h1').first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test('the who-is-signing-in choices are at least 44px tall', async ({ page }) => {
  await page.goto('/login');
  for (const id of ['choose-family', 'choose-senior']) {
    const box = await page.getByTestId(id).boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
});
