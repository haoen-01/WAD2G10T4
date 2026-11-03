import { expect, test } from '@playwright/test';

import { resetDemo } from './support';

// The Family page's own pieces: the care-group avatars, the invite PIN card and the reserved spot
// for a possible future location feature.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

test('the avatar cluster names everyone in the care group', async ({ page }) => {
  await page.goto('/family');
  const cluster = page.getByRole('link', { name: /^Care group/ });
  await expect(cluster).toBeVisible();
  await expect(cluster).toHaveAttribute('href', '#family-group');
  for (const name of ['Sarah', 'John', 'Emily']) {
    await expect(cluster).toHaveAttribute('aria-label', new RegExp(name));
  }
});

test('the location slot is only a placeholder that promises nothing', async ({ page }) => {
  await page.goto('/family');
  const slot = page.locator('[data-slot="senior-location"]');
  await expect(slot).toBeVisible();
  await expect(slot).toContainText('not available yet');
  await expect(slot).not.toContainText(/emergency|track|safety/i);
});

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`the invite PIN shows all six digits as text at once (${reducedMotion})`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion });
    await page.goto('/family');
    await page.getByTestId('new-join-pin').click();
    const pin = page.getByTestId('join-pin');
    // Text, not an image: read at once, before any animation could have finished.
    await expect(pin).toHaveText(/^\d{3} \d{3}$/);
    await expect(pin).toBeVisible();
  });
}
