import { expect, test, type Page } from '@playwright/test';

import { openSettings } from './support';

// The UI revamp (docs/ui-revamp.md): the living background, panels that glow near the mouse, the
// menu's glass bubble that follows the mouse, the Care+ cursors, and "Get started" on /login.

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

test('Care+ cursors are always on: links and buttons show the hand, and there is no switch', async ({
  page,
}) => {
  await enterAsFamily(page);
  const cursorOf = (selector: string) =>
    page
      .locator(selector)
      .first()
      .evaluate((element) => getComputedStyle(element).cursor);
  expect(await cursorOf('.mainnav-link')).toContain('/cursors/hand.svg');
  expect(await cursorOf('[data-testid="open-morning-summary"], button.btn-primary')).toContain(
    '/cursors/hand.svg',
  );
  const panel = await openSettings(page);
  await expect(panel.getByRole('button', { name: 'Care+ cursors' })).toHaveCount(0);
});

test('"Get started" jumps straight to the sign-in choices, without playing the story', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Get started' }).click();
  // At once: no smooth scroll through the story on the way.
  const top = await page.evaluate(() =>
    Math.round(document.getElementById('sign-in')!.getBoundingClientRect().top),
  );
  expect(Math.abs(top)).toBeLessThanOrEqual(1);
  await expect(page.locator('#sign-in')).toBeFocused();
  await expect(page.getByTestId('choose-family')).toBeInViewport();
});

test('the landing story has the whole screen: the top bar returns at the sign-in choices', async ({
  page,
}) => {
  await page.goto('/login');
  const bar = page.getByRole('banner');
  await expect(bar).toBeHidden();
  await page.getByRole('link', { name: 'Get started' }).click();
  await expect(bar).toBeVisible();
  // Leaving the page puts the bar back to normal.
  await page.getByTestId('choose-family').click();
  await expect(page).toHaveURL(/\/login\/family/);
  await expect(bar).toBeVisible();
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
