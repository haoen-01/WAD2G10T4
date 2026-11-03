import { expect, test, type Page } from '@playwright/test';

import { openSettings } from './support';

// The UI revamp (docs/ui-revamp.md): the living background, panels that glow near the mouse, the
// menu's glass bubble that follows the mouse, and the Care+ cursors with their switch.

test.use({ viewport: { width: 1280, height: 800 } });

async function enterAsFamily(page: Page) {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await expect(page).toHaveURL(/\/$/);
}

/** How far (px) the menu bubble's left edge is from a link's left edge. */
async function bubbleGap(page: Page, linkName: string) {
  return page.evaluate((name) => {
    const bubble = document.querySelector('.mainnav-indicator')?.getBoundingClientRect();
    const link = Array.from(document.querySelectorAll<HTMLElement>('.mainnav-link')).find(
      (element) => element.textContent?.trim() === name,
    );
    const box = link?.getBoundingClientRect();
    return bubble && box ? Math.abs(bubble.x - box.x) : 999;
  }, linkName);
}

test('the background sits behind the page, ignores clicks and is hidden from screen readers', async ({
  page,
}) => {
  await enterAsFamily(page);
  const layer = page.locator('.living');
  await expect(layer).toHaveCount(1);
  await expect(layer).toHaveAttribute('aria-hidden', 'true');
  await expect(layer).toHaveCSS('pointer-events', 'none');
  await expect(layer).toHaveCSS('position', 'fixed');
  await expect(layer).toHaveCSS('z-index', '-1');
});

test('a panel edge lights up when the mouse comes near and goes out when it leaves', async ({
  page,
}) => {
  await enterAsFamily(page);
  const panel = page.locator('main .sl-panel').first();
  await expect(panel).toBeVisible();
  const box = await panel.boundingBox();
  if (!box) throw new Error('no panel');

  await page.mouse.move(box.x + 40, box.y + 20, { steps: 4 });
  await expect
    .poll(() => panel.evaluate((element) => element.style.getPropertyValue('--sl-glow-on')))
    .toBe('1');
  // Far away (the bottom-right corner of the window, clear of the panel).
  await page.mouse.move(1270, 790, { steps: 4 });
  await page.mouse.move(box.x + box.width + 600, box.y + box.height + 600);
  await expect
    .poll(async () =>
      (await panel.boundingBox())
        ? panel.evaluate((element) => element.style.getPropertyValue('--sl-glow-on'))
        : '0',
    )
    .not.toBe('1');
});

test('the menu bubble follows the mouse, then goes back to the current page', async ({ page }) => {
  await enterAsFamily(page);
  const menu = page.getByRole('banner').getByRole('navigation', { name: 'Main' });
  await expect(page.locator('.mainnav-list.is-ready')).toHaveCount(1);
  await expect.poll(() => bubbleGap(page, 'Home')).toBeLessThanOrEqual(1);

  await menu.getByRole('link', { name: 'Family' }).hover();
  await expect.poll(() => bubbleGap(page, 'Family')).toBeLessThanOrEqual(1);
  // Still on Home: pointing is not choosing.
  await expect(menu.getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page');

  await page.mouse.move(640, 500);
  await expect.poll(() => bubbleGap(page, 'Home')).toBeLessThanOrEqual(1);
});

test('the bubble follows keyboard focus too', async ({ page }) => {
  await enterAsFamily(page);
  const menu = page.getByRole('banner').getByRole('navigation', { name: 'Main' });
  await expect(page.locator('.mainnav-list.is-ready')).toHaveCount(1);
  await menu.getByRole('link', { name: 'Calendar' }).focus();
  await expect.poll(() => bubbleGap(page, 'Calendar')).toBeLessThanOrEqual(1);
});

test('Care+ cursors are on by default, and the switch in Settings turns them off for good', async ({
  page,
}) => {
  await enterAsFamily(page);
  const html = page.locator('html');
  await expect(html).toHaveClass(/\bsl-cursors\b/);

  let panel = await openSettings(page);
  const toggle = panel.getByRole('button', { name: 'Care+ cursors' });
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(html).not.toHaveClass(/\bsl-cursors\b/);

  // Remembered in this browser.
  await page.reload();
  await expect(html).not.toHaveClass(/\bsl-cursors\b/);
  panel = await openSettings(page);
  await expect(panel.getByRole('button', { name: 'Care+ cursors' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
});

test('with reduced motion nothing in the background drifts or follows', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await enterAsFamily(page);
  const names = await page
    .locator('.living .glow')
    .evaluateAll((glows) => glows.map((glow) => getComputedStyle(glow).animationName));
  expect(names.length).toBeGreaterThan(0);
  for (const name of names) expect(name).toBe('none');
  await expect(page.locator('.living .follow')).toBeHidden();
});
