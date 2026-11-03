import { expect, test, type Page } from '@playwright/test';

// Walking badges: worked out from the senior's daily steps (Mdm Lim's fixture: 29 days from
// 21 Jul 2026, about 5,850 steps a day) and from walks finished on the Walk page. The senior claims
// what she has earned on her own page; the family sees the same shelf on the Walk page.

test.describe.configure({ timeout: 60_000 });

const menu = (page: Page) => page.getByRole('navigation', { name: 'Main' });
const badge = (page: Page, id: string) => page.getByTestId(`badge-${id}`);

async function openMyBadges(page: Page) {
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  await page.getByRole('tab', { name: /Badges/ }).click();
  await expect(page.getByTestId('badge-summary')).toContainText('earned');
}

test('the senior claims an earned badge, and its dates are on the back', async ({ page }) => {
  await openMyBadges(page);

  // Earned from her steps, waiting to be claimed; the tab says how many.
  const first = badge(page, 'first-steps');
  await expect(first).toHaveAttribute('data-state', 'ready');
  const count = page.getByTestId('badges-ready-count');
  const before = Number((await count.innerText()).match(/\d+/)?.[0]);
  expect(before).toBeGreaterThan(1);

  // Not earned yet: locked, with how close she is and no Claim button.
  const tenK = badge(page, 'steps-10k');
  await expect(tenK).toHaveAttribute('data-state', 'locked');
  await expect(tenK).toContainText(/Best day so far: [\d,]+ of 10,000 steps/);
  await expect(page.getByTestId('claim-steps-10k')).toHaveCount(0);

  await page.getByTestId('claim-first-steps').click();
  await expect(first).toHaveAttribute('data-state', 'claimed');
  await expect(first).toContainText('Earned Tue, 21 Jul 2026');
  await expect(page.getByTestId('badge-announce')).toHaveText(
    'Well done! You claimed First Steps.',
  );
  await expect(count).toContainText(String(before - 1));

  // Up close, full screen with no card: the medal, its name, and one line about it.
  await first.getByRole('button', { name: /First Steps/ }).click();
  const viewer = page.getByTestId('badge-viewer');
  await expect(viewer.getByRole('heading', { name: 'First Steps' })).toBeVisible();
  await expect(viewer.getByTestId('badge-viewer-line')).toHaveText(
    'You earned this for walking 1,000 steps in one day, on Tue, 21 Jul 2026.',
  );
  await expect(viewer.getByTestId('badge-claimed-on')).toHaveText(
    /Claimed .+ \d{4}, \d{1,2}:\d{2} [ap]m$/,
  );
  await expect(viewer.locator('.badge-engraving')).toContainText('EARNED BY MDM LIM');
  await viewer.getByTestId('badge-turn').click();
  await expect(viewer.getByTestId('badge-turn')).toContainText('Show the front');
  await page.keyboard.press('Escape');
  await expect(viewer).toBeHidden();
  await expect(first.getByRole('button', { name: /First Steps/ })).toBeFocused();

  // Kept in this browser.
  await page.reload();
  await page.getByRole('tab', { name: /Badges/ }).click();
  await expect(badge(page, 'first-steps')).toHaveAttribute('data-state', 'claimed');
});

const turnOf = (page: Page, scope: string) => async () =>
  Number(
    (await page.locator(`${scope} .coin-body`).first().getAttribute('style'))?.match(
      /rotateY\(([-\d.]+)deg\)/,
    )?.[1] ?? 0,
  );

test('claiming up close keeps focus and says so; the medal spins by hand and lands face on', async ({
  page,
}) => {
  await openMyBadges(page);
  await badge(page, 'weekend-walker')
    .getByRole('button', { name: /Weekend Walker/ })
    .click();
  const viewer = page.getByTestId('badge-viewer');
  await viewer.getByTestId('viewer-claim').click();

  await expect(viewer.getByTestId('badge-viewer-said')).toHaveText(
    'Congratulations! You earned a new badge: Weekend Walker.',
  );
  await expect(viewer.getByTestId('badge-cheer')).toContainText('Congratulations!');
  await expect(viewer.getByTestId('badge-turn')).toBeFocused();
  await expect(badge(page, 'weekend-walker')).toHaveAttribute('data-state', 'claimed');

  // Two turns to celebrate, then it rests face on, and stays there.
  const turn = turnOf(page, '[data-testid="badge-viewer"]');
  await expect.poll(turn).toBe(720);
  await page.waitForTimeout(600);
  expect(await turn()).toBe(720);

  // Dragged across and let go: it turns with the hand and lands on a face.
  const stage = viewer.locator('.viewer-stage');
  const box = await stage.boundingBox();
  if (!box) throw new Error('no stage');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, { steps: 8 });
  expect(await turn()).not.toBe(720);
  await page.mouse.up();
  await expect.poll(async () => (await turn()) % 180, { timeout: 8_000 }).toBe(0);

  // "Back" sends it home to the shelf.
  await viewer.getByTestId('badge-viewer-back').click();
  await expect(viewer).toBeHidden();
});

test('the first look at a new badge fills the screen with celebration, once for each viewer', async ({
  page,
}) => {
  await openMyBadges(page);
  await page.getByTestId('claim-steps-5k').click();
  const tile = badge(page, 'steps-5k').getByRole('button', { name: /5,000 Step Day/ });

  // First look: confetti over the whole screen, light behind the medal, "Congratulations!".
  await tile.click();
  const viewer = page.getByTestId('badge-viewer');
  await expect(viewer.getByTestId('badge-cheer')).toContainText('You earned a new badge');
  await expect(viewer.getByTestId('badge-confetti')).toBeVisible();
  const size = await viewer.getByTestId('badge-confetti').boundingBox();
  expect(size?.width).toBe(page.viewportSize()?.width);
  expect(size?.height).toBe(page.viewportSize()?.height);
  await expect(viewer.locator('.viewer-rays')).toHaveCount(1);
  await viewer.getByTestId('badge-viewer-back').click();
  await expect(viewer).toBeHidden();

  // Second look: the calm view.
  await tile.click();
  await expect(viewer.getByRole('heading', { name: '5,000 Step Day' })).toBeVisible();
  await expect(viewer.getByTestId('badge-cheer')).toHaveCount(0);
  await expect(viewer.getByTestId('badge-confetti')).toHaveCount(0);
  await page.keyboard.press('Escape');

  // Her family's first look is celebrated too, for them.
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await badge(page, 'steps-5k')
    .getByRole('button', { name: /5,000 Step Day/ })
    .click();
  await expect(viewer.getByTestId('badge-cheer')).toContainText('Mdm Lim earned a new badge');
  await expect(viewer.getByTestId('badge-viewer-line')).toHaveText(
    'Mdm Lim earned this for walking 5,000 steps in one day, on Tue, 21 Jul 2026.',
  );
});

test('a medal on the shelf spins when dragged, without opening', async ({ page }) => {
  await openMyBadges(page);
  await page.getByTestId('claim-steps-3k').click();
  await page.waitForTimeout(1900); // the claim's own two turns
  const stage = badge(page, 'steps-3k').locator('.tile-stage');
  const box = await stage.boundingBox();
  if (!box) throw new Error('no stage');
  const turn = turnOf(page, '[data-testid="badge-steps-3k"]');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 90, box.y + box.height / 2, { steps: 8 });
  expect(await turn()).toBeLessThan(-40);
  await page.mouse.up();
  await expect(page.getByTestId('badge-viewer')).toBeHidden();
  await expect.poll(async () => (await turn()) % 180, { timeout: 8_000 }).toBe(0);
});

test('a claimed badge turns while the mouse rests on it, then settles face up', async ({
  page,
}) => {
  await openMyBadges(page);
  await page.getByTestId('claim-steps-5k').click();
  const coin = badge(page, 'steps-5k').locator('.coin-body');
  const turn = async () =>
    Number((await coin.getAttribute('style'))?.match(/rotateY\(([-\d.]+)deg\)/)?.[1] ?? 0);

  await page.waitForTimeout(1900); // the claim's own two turns
  await badge(page, 'steps-5k')
    .getByRole('button', { name: /5,000 Step Day/ })
    .hover();
  await expect.poll(turn).toBeGreaterThan(20);
  await page.mouse.move(0, 0);
  // It finishes the turn it is on and rests face up.
  await expect.poll(async () => (await turn()) % 360, { timeout: 10_000 }).toBe(0);

  // Not claimed yet: no turn.
  await badge(page, 'steps-3k')
    .getByRole('button', { name: /3,000 Step Day/ })
    .hover();
  await page.waitForTimeout(600);
  const still = await badge(page, 'steps-3k').locator('.coin-body').getAttribute('style');
  expect(still ?? '').toContain('rotateY(0deg)');
});

test('claim all, and the family sees the shelf without a Claim button', async ({ page }) => {
  await openMyBadges(page);
  await page.getByTestId('claim-all').click();
  await expect(page.getByTestId('badges-ready-count')).toHaveCount(0);
  await expect(page.locator('[data-state="ready"]')).toHaveCount(0);
  await expect(page.getByTestId('badge-announce')).toContainText(/You claimed \d+ badges/);

  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-family').click();
  await page.getByTestId('continue-family').click();
  await menu(page).getByRole('link', { name: /^Walk/ }).click();

  const shelf = page.getByTestId('badge-shelf');
  await expect(shelf.getByRole('heading', { name: 'Mdm Lim’s walking badges' })).toBeVisible();
  await expect(badge(page, 'first-steps')).toHaveAttribute('data-state', 'claimed');
  await expect(shelf.getByRole('button', { name: /^Claim/ })).toHaveCount(0);
});

test('a walk finished while shared earns Park Loop', async ({ page }) => {
  await page.addInitScript(() => {
    if (localStorage.getItem('careplus.walk.v1') === null) {
      localStorage.setItem(
        'careplus.walk.v1',
        JSON.stringify({ shareWalk: true, stillnessAlerts: false, limitMin: 120, notify: false }),
      );
    }
  });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await menu(page).getByRole('link', { name: /^Walk/ }).click();
  await expect(badge(page, 'park-loop')).toHaveAttribute('data-state', 'locked');

  await page.getByTestId('demo-start').click();
  await page.getByTestId('demo-skip').click();
  await page.getByTestId('demo-skip').click();
  await expect(page.getByTestId('walk-state')).toContainText('Back home');
  await expect(badge(page, 'park-loop')).toHaveAttribute('data-state', 'ready');
  await expect(badge(page, 'park-loop')).toContainText('Earned, not claimed yet');
});
