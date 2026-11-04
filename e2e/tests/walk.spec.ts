import { expect, test, type Page } from '@playwright/test';

import { openSettings } from './support';

// The live walk: the senior's consent, the simulated watch on the 3D map, exploring the map, and
// the "Still for a while" check-in (raised on every family screen, answered by the family or by the
// senior's "I'm OK"). The map uses its offline sketch here (VITE_WALK_MAP=sketch in the config).

// The map loads MapLibre and the demo walk runs in (sped-up) real time, so these take longer.
test.describe.configure({ timeout: 60_000 });

const SHARING_ON = JSON.stringify({
  shareWalk: true,
  stillnessAlerts: true,
  limitMin: 120,
  notify: false,
});

/** The senior has already said yes to both (set once; later changes in the test are kept). */
async function seniorHasShared(page: Page) {
  await page.addInitScript((value) => {
    if (localStorage.getItem('careplus.walk.v1') === null) {
      localStorage.setItem('careplus.walk.v1', value);
    }
  }, SHARING_ON);
}

const menu = (page: Page) => page.getByRole('navigation', { name: 'Main' });

async function openWalkAsFamily(page: Page) {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(page.getByTestId('walk-map')).toHaveAttribute('data-ready', 'true', {
    timeout: 20_000,
  });
}

/** Starts the demo walk at 20× and waits until she is well away from home. */
async function walkAwayFromHome(page: Page) {
  await page.getByTestId('demo-start').click();
  await page.getByTestId('demo-speed-20').click();
  await expect(page.getByTestId('walk-state')).toContainText('Walking');
  await expect
    .poll(async () => parseInt(await page.getByTestId('walk-distance').innerText(), 10), {
      timeout: 20_000,
    })
    .toBeGreaterThanOrEqual(200);
}

/** Keeps her where she is and moves the demo's clock on two hours. */
async function stayTwoHours(page: Page) {
  await page.getByTestId('demo-stay').click();
  await page.getByTestId('demo-skip').click();
  await page.getByTestId('demo-skip').click();
}

test('the family sees no walk until the senior shares it, and only they can turn it on', async ({
  page,
}) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(page.getByTestId('walk-not-shared')).toBeVisible();
  await expect(page.getByTestId('walk-not-shared')).toContainText(
    'Mdm Lim is not sharing their walks',
  );
  // Care+ does not record gender: the senior is named, never "she" or "he".
  await expect(page.locator('main')).not.toContainText(/\b(she|her|he|his)\b/i);
  await expect(page.getByTestId('walk-map')).toHaveCount(0);

  await openSettings(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  const share = page.getByRole('switch', { name: /Share my walk with my family/ });
  const still = page.getByRole('switch', { name: /Tell my family if I stay in one place/ });
  await expect(share).not.toBeChecked();
  await expect(still).toBeDisabled();
  await share.check();
  await still.check();
  await expect(page.getByText('Your family can see your walk.')).toBeVisible();

  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(page.getByTestId('walk-sharing')).toHaveText('Mdm Lim is sharing their walk');
  await expect(page.getByTestId('walk-map')).toBeVisible();
});

test('the demo walk moves on the 3D map, and the map can be explored and replayed', async ({
  page,
}) => {
  await seniorHasShared(page);
  await openWalkAsFamily(page);
  const map = page.getByTestId('walk-map');
  await expect(map).toHaveAttribute('data-look', 'sketch');
  await expect(map).toHaveAttribute('data-three-d', 'true');

  await walkAwayFromHome(page);
  await expect(page.getByTestId('walk-pill')).toContainText('Walking');
  await expect(page.getByTestId('walk-updated')).toContainText('Last reading');

  // 2D and back.
  await page.getByTestId('map-3d').click();
  await expect(map).toHaveAttribute('data-three-d', 'false');
  await page.getByTestId('map-3d').click();
  await expect(map).toHaveAttribute('data-three-d', 'true');

  // The map's looks, closed again with Escape.
  await page.getByTestId('map-layers').click();
  const looks = page.getByRole('group', { name: 'Map look' });
  await expect(looks.getByRole('button')).toHaveText([/Streets/, /Quiet/, /Sketch/]);
  await page.keyboard.press('Escape');
  await expect(looks).toBeHidden();

  // Dragging the map to look around stops following her; "Back to" follows again.
  await page.getByTestId('demo-pause').click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await map.scrollIntoViewIfNeeded();
  const box = await map.boundingBox();
  if (!box) throw new Error('the map has no box');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 150, box.y + box.height / 2 - 80, { steps: 8 });
  await page.mouse.up();
  await expect(map).toHaveAttribute('data-follow', 'false');
  await page.getByTestId('map-back').click();
  await expect(map).toHaveAttribute('data-follow', 'true');

  // Replay from the start of the walk, then back to now.
  await page.getByTestId('walk-replay').focus();
  await page.keyboard.press('Home');
  await expect(page.getByTestId('walk-pill')).toContainText('Replaying');
  await page.getByTestId('walk-live').click();
  await expect(page.getByTestId('walk-pill')).not.toContainText('Replaying');
});

test('a long stop away from home raises a check-in on every family screen', async ({ page }) => {
  await seniorHasShared(page);
  await openWalkAsFamily(page);
  await walkAwayFromHome(page);
  await stayTwoHours(page);
  await expect(page.getByTestId('checkin-line')).toContainText('The family has been told');
  await expect(page.getByTestId('walk-dot')).toBeVisible();

  // On Home: the banner, with Call and Message opening the phone's own apps.
  await menu(page).getByRole('link', { name: 'Home' }).click();
  const banner = page.getByTestId('checkin-banner');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText(/has been in one place for 2 h/);
  await expect(banner).not.toContainText(/fall|emergency/i);
  await expect(banner.getByTestId('checkin-call')).toHaveAttribute('href', /^tel:\+65/);
  await expect(banner.getByTestId('checkin-message')).toHaveAttribute('href', /^sms:\+65/);

  // "I'm checking in" tells the rest of the family; "Mdm Lim is fine" closes it.
  await banner.getByTestId('checkin-claim').click();
  await expect(banner).toContainText('Sarah is checking in.');
  await expect(banner.getByTestId('checkin-fine')).toHaveText('Mdm Lim is fine');
  await banner.getByTestId('checkin-fine').click();
  await expect(banner).toHaveCount(0);
  await expect(page.getByTestId('walk-dot')).toHaveCount(0);

  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(page.getByTestId('checkin-log')).toContainText('Sarah marked Mdm Lim fine');
  await expect(page.getByTestId('checkin-line')).toContainText('Marked fine for this stop');
});

test('there is no check-in at home, however long she stays', async ({ page }) => {
  await seniorHasShared(page);
  await openWalkAsFamily(page);
  await page.getByTestId('demo-start').click();
  await stayTwoHours(page);
  await page.getByTestId('demo-skip').click();
  await expect(page.getByTestId('checkin-line')).toContainText('At home');
  await expect(page.getByTestId('demo-pause')).toBeVisible();
  await expect(page.getByTestId('walk-dot')).toHaveCount(0);
  await expect(page.getByTestId('checkin-log')).toHaveCount(0);
});

test('the senior is asked first, and "I\'m OK" before the limit means the family is never told', async ({
  page,
}) => {
  await seniorHasShared(page);
  await openWalkAsFamily(page);
  await page.getByTestId('still-limit').selectOption('30');
  await walkAwayFromHome(page);
  await page.getByTestId('demo-stay').click();
  await page.getByTestId('demo-skip-15').click();
  // Paused, so the 15 minutes before the family is told do not run out during the test.
  await page.getByTestId('demo-pause').click();
  await expect(page.getByTestId('checkin-line')).toContainText(
    'Mdm Lim is being asked if they are OK',
  );
  await expect(page.getByTestId('walk-dot')).toHaveCount(0);

  await openSettings(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  const prompt = page.getByTestId('still-prompt');
  await expect(prompt).toContainText('Your family will be told at');
  await prompt.getByRole('button', { name: 'I’m OK' }).click();
  await expect(page.getByTestId('im-ok-thanks')).toBeVisible();

  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(page.getByTestId('checkin-line')).not.toContainText('being asked');
  await expect(page.getByTestId('checkin-log')).toHaveCount(0);
});

test('after the family is told, the senior\'s "I\'m OK" tells them', async ({ page }) => {
  await seniorHasShared(page);
  await openWalkAsFamily(page);
  await walkAwayFromHome(page);
  await stayTwoHours(page);
  await expect(page.getByTestId('walk-dot')).toBeVisible();

  await openSettings(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  const prompt = page.getByTestId('still-prompt');
  await expect(prompt).toContainText('Your family has been told');
  await prompt.getByRole('button', { name: 'I’m OK' }).click();
  await expect(page.getByTestId('im-ok-thanks')).toContainText('Your family knows you are OK');

  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await expect(page.getByTestId('checkin-banner')).toHaveCount(0);
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(page.getByTestId('checkin-log')).toContainText('Mdm Lim said they are OK');
});

test('when the senior stops sharing, her walk and any check-in disappear for the family', async ({
  page,
}) => {
  await seniorHasShared(page);
  await openWalkAsFamily(page);
  await walkAwayFromHome(page);
  await stayTwoHours(page);
  await expect(page.getByTestId('walk-dot')).toBeVisible();

  await openSettings(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  await page.getByRole('switch', { name: /Share my walk with my family/ }).uncheck();
  await expect(page.getByRole('switch', { name: /Tell my family/ })).not.toBeChecked();

  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await expect(page.getByTestId('checkin-banner')).toHaveCount(0);
  await expect(page.getByTestId('home-walk-link')).toHaveCount(0);
  await expect(page.getByTestId('walk-dot')).toHaveCount(0);
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(page.getByTestId('walk-not-shared')).toBeVisible();
  await expect(page.getByTestId('walk-map')).toHaveCount(0);
});
