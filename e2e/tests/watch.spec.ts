import { expect, test } from '@playwright/test';

import { resetDemo } from './support';

// The Watch page: the senior's simulated watch in 3D, opened from Watch in the menu or from the
// watch in Home's hero. The points come out once it has spun in; opening one shows its details,
// and Back closes them.

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

test('tapping the watch on Home opens the Watch page; dragging or the arrows only turn it', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const hero = page.getByTestId('hero-watch');
  // The picture is a link to the Watch page, not a slider.
  const open = hero.getByRole('link', { name: 'Open Mdm Lim’s watch page' });
  await expect(open).toBeVisible();
  const turn = async () => Number(await open.getAttribute('data-turn'));
  const rest = await turn();

  // A drag turns it and stays on Home.
  const box = (await open.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, { steps: 8 });
  await expect.poll(turn).not.toBe(rest);
  await page.mouse.up();
  await expect(page).toHaveURL(/\/$/);

  // The visible buttons turn it too, without a drag.
  await expect.poll(turn, { timeout: 10_000 }).toBe(rest); // back to facing you
  await hero.getByRole('button', { name: 'Turn the watch right' }).click();
  await expect.poll(turn).toBeGreaterThan(rest);
  await hero.getByRole('button', { name: 'Turn the watch left' }).click();
  await expect(page).toHaveURL(/\/$/);

  // A tap opens the Watch page.
  await open.click();
  await expect(page).toHaveURL(/\/watch$/);
  await expect(page.getByTestId('watch-point-steps')).toBeVisible();

  // Enter does the same from the keyboard.
  await page.goto('/');
  await page.getByRole('link', { name: 'Open Mdm Lim’s watch page' }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/watch$/);
});

test('with reduced motion the Home watch turns only as far as asked, and stays there', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const hero = page.getByTestId('hero-watch');
  const open = hero.getByRole('link', { name: 'Open Mdm Lim’s watch page' });
  const turn = async () => Number(await open.getAttribute('data-turn'));
  const rest = await turn();

  // One press, one step, at once: no easing round and no swinging back on its own.
  await hero.getByRole('button', { name: 'Turn the watch right' }).click();
  await expect.poll(turn).toBe(rest + 45);
  await page.waitForTimeout(2500);
  expect(await turn()).toBe(rest + 45);
});
