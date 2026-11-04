import { expect, test } from '@playwright/test';

import { resetDemo, showMoreOnHome } from './support';

// The Watch page: the senior's simulated watch in 3D, opened from the watch status on Home. The
// points come out once it has spun in; opening one shows its details, and Back closes them.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

test('the menu opens the watch, and a point opens and closes its details', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();

  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Watch' }).click();
  await expect(page).toHaveURL(/\/watch$/);
  await expect(page.getByRole('heading', { name: 'Watch', level: 1 })).toBeVisible();

  // The points appear once the watch has spun in.
  const sleep = page.getByTestId('watch-point-sleep');
  await expect(sleep).toBeVisible();
  await sleep.click();

  const details = page.getByTestId('watch-detail-sleep');
  await expect(details).toBeVisible();
  await expect(details.getByRole('heading', { name: 'Sleep' })).toBeFocused();

  await details.getByRole('button', { name: 'Back' }).click();
  await expect(details).toHaveCount(0);
  await expect(sleep).toBeFocused();
});

test('the watch turns with the buttons as well as by dragging, and never mentions heart rate', async ({
  page,
}) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await page.goto('/watch');

  const stage = page.getByRole('slider', { name: 'Turn the watch' });
  await expect(page.getByTestId('watch-point-steps')).toBeVisible();
  await page.getByTestId('watch-spin').click(); // stop the slow turn so the angle is steady
  const before = Number(await stage.getAttribute('aria-valuenow'));
  await page.getByRole('button', { name: 'Turn right' }).click();
  await expect.poll(async () => Number(await stage.getAttribute('aria-valuenow'))).not.toBe(before);

  await expect(page.getByTestId('watch-stage')).not.toContainText(/heart|bpm/i);

  // Escape closes an open point too.
  await page.getByTestId('watch-point-water').click();
  await expect(page.getByTestId('watch-detail-water')).toContainText('Example');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('watch-detail-water')).toHaveCount(0);
});

test('tapping the watch on Home opens the Watch page; dragging only turns it', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await showMoreOnHome(page); // keeps the morning summary from opening over Home
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const stage = page.getByRole('slider', { name: /Turn the watch/ });
  await expect(stage).toBeVisible();

  // A drag turns it and stays on Home.
  const box = (await stage.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect(page).toHaveURL(/\/$/);

  // A tap opens the Watch page.
  await stage.click();
  await expect(page).toHaveURL(/\/watch$/);
  await expect(page.getByTestId('watch-point-steps')).toBeVisible();

  // Enter does the same from the keyboard.
  await page.goto('/');
  await page.getByRole('slider', { name: /Turn the watch/ }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/watch$/);
});
