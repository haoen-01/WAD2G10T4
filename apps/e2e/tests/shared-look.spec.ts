import { expect, test, type Page } from '@playwright/test';

// The shared look (feedback round 2, part A): the menu stays reachable in the top bar on a phone,
// and the colours in `theme.css` stay readable in light and dark mode.

const menu = (page: Page) => page.getByRole('banner').getByRole('navigation', { name: 'Main' });

/** WCAG contrast of an element's text against its own background colour. */
async function contrastOf(page: Page, selector: string): Promise<number[]> {
  return page.$$eval(selector, (elements) => {
    const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
    const lin = (v: number) => {
      const s = v / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const lum = ([r, g, b]: number[]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    return elements.map((el) => {
      const style = getComputedStyle(el);
      const a = lum(rgb(style.color));
      const b = lum(rgb(style.backgroundColor));
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    });
  });
}

test.describe('on a phone', () => {
  test.use({ viewport: { width: 375, height: 700 } });

  test('every screen is in the top bar, and the menu stays on screen while scrolling', async ({
    page,
  }) => {
    // The calendar, as Home is now too short on a phone to scroll the brand row away.
    await page.goto('/calendar');
    await expect(menu(page).getByRole('link')).toHaveText([
      'Home',
      'My day',
      'Walk',
      'Calendar',
      'Family',
    ]);

    // The brand row scrolls away; the menu row stays pinned at the very top.
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(300);
    await expect
      .poll(async () => {
        const box = await menu(page).boundingBox();
        return box ? Math.round(box.y) : -1;
      })
      .toBeLessThan(10);
    await expect(menu(page)).toBeInViewport();

    await menu(page).getByRole('link', { name: 'Family' }).click();
    await expect(page).toHaveURL(/\/family$/);
    await expect(menu(page).getByRole('link', { name: 'Family' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  test('sign out keeps its name when only its icon shows', async ({ page }) => {
    await page.goto('/login');
    await page.getByTestId('choose-family').click();
    await page.getByTestId('continue-family').click();
    await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
  });
});

test('every appointment kind and colour tone is readable in light and dark mode', async ({
  page,
}) => {
  await page.goto('/');
  await page.evaluate(() => {
    const box = document.createElement('div');
    box.id = 'swatches';
    for (const kind of ['medical', 'therapy', 'activity', 'errand', 'task']) {
      const badge = document.createElement('span');
      badge.className = `kind-badge kind-${kind}`;
      badge.textContent = kind;
      box.append(badge);
    }
    for (const tone of ['jade', 'coral', 'blue', 'purple', 'orange']) {
      const tag = document.createElement('span');
      tag.className = `sl-tag sl-tone-${tone}`;
      tag.textContent = tone;
      box.append(tag);
    }
    document.body.append(box);
  });

  for (const theme of ['light', 'dark']) {
    await page.evaluate((t) => document.documentElement.setAttribute('data-bs-theme', t), theme);
    const ratios = await contrastOf(page, '#swatches > span');
    expect(ratios).toHaveLength(10);
    for (const ratio of ratios) expect(ratio, `${theme} mode`).toBeGreaterThanOrEqual(4.5);
  }
});
