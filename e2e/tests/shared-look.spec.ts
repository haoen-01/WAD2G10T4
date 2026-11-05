import { expect, test, type Page } from '@playwright/test';

import { addDemoTask, clearDemoTasks, isoDay, openSettings, resetDemo } from './support';

// The shared look (feedback round 2, part A): the menu stays reachable on a phone (a bottom tab
// bar since the redesign) and in the header on a wide screen, the senior keeps the small top bar,
// and the colours in `theme.css` stay readable in light and dark mode.

const menu = (page: Page) => page.getByRole('navigation', { name: 'Main' });

async function enterAs(page: Page, audience: 'family' | 'senior') {
  await page.goto('/login');
  await page.getByTestId(`choose-${audience}`).click();
  await page.getByTestId(`continue-${audience}`).click();
}

/** Scrolls to the very bottom, again if the page grows while its data arrives. */
async function scrollToBottom(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => {
        window.scrollTo(0, document.documentElement.scrollHeight);
        return (
          window.scrollY > 300 && window.scrollY + innerHeight >= document.body.scrollHeight - 1
        );
      }),
    )
    .toBe(true);
}

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

  test('every screen is in the bottom tab bar, which stays on screen while scrolling', async ({
    page,
  }) => {
    // The calendar, as Home is too short on a phone to scroll.
    await page.goto('/calendar');
    await expect(menu(page).getByRole('link')).toHaveText([
      'Home',
      'My day',
      'Watch',
      'Walk',
      'Calendar',
      'Family',
    ]);

    // At the bottom of the page the bar is still on screen, flush with the bottom edge.
    await scrollToBottom(page);
    await expect(menu(page)).toBeInViewport();
    await expect
      .poll(async () => {
        const [box, height] = [await menu(page).boundingBox(), page.viewportSize()?.height ?? 0];
        return box ? Math.abs(box.y + box.height - height) <= 4 : false;
      })
      .toBe(true);

    // Every tab is an easy target.
    for (const link of await menu(page).getByRole('link').all()) {
      const box = await link.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    }

    // The footer, the last thing on the page, is not covered by the bar.
    const bar = await menu(page).boundingBox();
    const footer = await page.locator('footer').boundingBox();
    expect(footer && bar && footer.y + footer.height <= bar.y + 1).toBe(true);
    // Nor is the last element in <main>.
    const last = await page.locator('main > *:last-child').boundingBox();
    expect(last && bar && last.y + last.height <= bar.y).toBe(true);

    await menu(page).getByRole('link', { name: 'Family' }).click();
    await expect(page).toHaveURL(/\/family$/);
    await expect(menu(page).getByRole('link', { name: 'Family' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  test('sign out is in the Settings menu, named, and still icon-only for the senior', async ({
    page,
  }) => {
    await enterAs(page, 'family');
    const panel = await openSettings(page);
    await panel.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);

    // The senior keeps the small top bar: Sign out shows only its icon, but keeps its name.
    await enterAs(page, 'senior');
    await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
  });

  test('a toast sits above the tab bar', async ({ page, request }) => {
    await resetDemo(request);
    await page.goto('/calendar');
    await page.getByTestId('add-appointment').click();
    await page.getByTestId('add-title').fill('Toast check');
    await page.getByLabel('Date', { exact: true }).fill(isoDay(1));
    await page.getByLabel('From', { exact: true }).fill('16:00');
    await page.getByLabel('To', { exact: true }).fill('17:00');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    const toast = page.locator('.sl-toast').filter({ hasText: 'Added Toast check' });
    await expect(toast).toBeVisible();
    await expect(menu(page)).toBeVisible();
    // Let the toast finish sliding in before measuring.
    await page.waitForTimeout(500);
    const toastBox = await toast.boundingBox();
    const barBox = await menu(page).boundingBox();
    expect(toastBox && barBox && toastBox.y + toastBox.height <= barBox.y).toBe(true);
  });
});

test.describe('the family tab bar at the largest text size', () => {
  test.use({ viewport: { width: 375, height: 700 } });

  /** Every label's font size, and whether each stays whole inside its own tab. */
  async function checkTabs(page: Page, where: string): Promise<number> {
    const links = menu(page).getByRole('link');
    const sizes: number[] = [];
    for (const link of await links.all()) {
      const { fits, size } = await link.evaluate((el) => {
        const label = el.querySelector('.mainnav-label')!;
        const box = label.getBoundingClientRect();
        const tab = el.getBoundingClientRect();
        return {
          fits:
            box.left >= tab.left - 0.5 &&
            box.right <= tab.right + 0.5 &&
            box.top >= tab.top - 0.5 &&
            box.bottom <= tab.bottom + 0.5,
          size: parseFloat(getComputedStyle(label).fontSize),
        };
      });
      expect(fits, `${await link.innerText()} ${where}`).toBe(true);
      expect((await link.boundingBox())?.width ?? 0, where).toBeGreaterThanOrEqual(44);
      sizes.push(size);
    }
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth, where).toBeLessThanOrEqual(clientWidth);
    // The page's last content clears the bar, however many rows it has.
    const padding = await page.evaluate(() =>
      parseFloat(getComputedStyle(document.querySelector('.shell--tabs')!).paddingBottom),
    );
    const bar = (await menu(page).boundingBox())!;
    expect(padding, where).toBeGreaterThanOrEqual(bar.height - 1);
    // Labels side by side keep a little room between them (or the bar takes another row), and the
    // highlight pill never runs past either edge of the screen.
    const gaps = await menu(page).evaluate((nav) => {
      const boxes = [...nav.querySelectorAll('.mainnav-label')].map((label) =>
        label.getBoundingClientRect(),
      );
      return boxes
        .slice(1)
        .flatMap((box, i) =>
          Math.abs(box.top - boxes[i].top) < 2 ? [box.left - boxes[i].right] : [],
        );
    });
    for (const gap of gaps) expect(gap, where).toBeGreaterThanOrEqual(12);
    // Polled: the pill springs to its new place when the text size changes.
    await expect
      .poll(
        () =>
          menu(page).evaluate((nav) => {
            const pill = nav.querySelector('.mainnav-indicator')!.getBoundingClientRect();
            const edge = nav.getBoundingClientRect();
            return pill.left >= edge.left - 0.5 && pill.right <= edge.right + 0.5;
          }),
        { message: `the highlight stays inside the bar ${where}` },
      )
      .toBe(true);
    return Math.min(...sizes);
  }

  for (const { who, tabs } of [
    { who: 'the family', tabs: ['Home', 'Watch', 'Walk', 'Calendar', 'Family'] },
    { who: 'no view chosen', tabs: ['Home', 'My day', 'Watch', 'Walk', 'Calendar', 'Family'] },
  ]) {
    test(`with ${who}, labels grow with the text size and stay inside their own tab`, async ({
      page,
    }) => {
      if (who === 'the family') await enterAs(page, 'family');
      else await page.goto('/');
      await expect(menu(page).getByRole('link')).toHaveText(tabs);
      for (const width of [375, 320]) {
        await page.setViewportSize({ width, height: 700 });
        await page.evaluate(() => (document.documentElement.style.fontSize = '100%'));
        const normal = await checkTabs(page, `at ${width}px, 100%`);
        await page.evaluate(() => (document.documentElement.style.fontSize = '125%'));
        await checkTabs(page, `at ${width}px, 125%`);
        await page.evaluate(() => (document.documentElement.style.fontSize = '150%'));
        const large = await checkTabs(page, `at ${width}px, 150%`);
        // The zoom setting is never undone by squeezing the labels to fit.
        expect(large, `at ${width}px`).toBeCloseTo(normal * 1.5, 0);
      }
    });
  }
});

test.describe('on a very small phone', () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test('the family screen fits: no sideways scroll, a visible tab bar, header clear of content', async ({
    page,
  }) => {
    await page.goto('/');
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
    await expect(menu(page)).toBeInViewport();
    for (const link of await menu(page).getByRole('link').all()) {
      expect((await link.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    const header = await page.getByRole('banner').boundingBox();
    const heading = await page.locator('main h1').first().boundingBox();
    expect(header && heading && heading.y >= header.y + header.height - 1).toBe(true);
    // One slim row: the tools collapse into the Settings button.
    expect(header?.height ?? 99).toBeLessThan(80);
  });
});

test.describe('on a wide screen', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('the menu is a pill inside the header row, with the current page marked', async ({
    page,
  }) => {
    await page.goto('/calendar');
    const header = page.getByRole('banner');
    const nav = header.getByRole('navigation', { name: 'Main' });
    await expect(nav.getByRole('link')).toHaveText([
      'Home',
      'My day',
      'Watch',
      'Walk',
      'Calendar',
      'Family',
    ]);
    await expect(nav.getByRole('link', { name: 'Calendar' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await expect(nav.getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current');
    // No bottom bar: the one menu is in the header.
    await expect(menu(page)).toHaveCount(1);

    // The page's first heading starts below the pinned header, and the header stays at the top.
    const heading = await page.locator('main h1').first().boundingBox();
    const bar = await header.boundingBox();
    expect(bar && heading && heading.y >= bar.y + bar.height).toBe(true);
    await page.evaluate(() => window.scrollTo(0, 200));
    await expect.poll(async () => Math.round((await header.boundingBox())?.y ?? -1)).toBe(0);
  });

  test('every tab stays whole from the tablet width up, at the largest text size', async ({
    page,
  }) => {
    await page.goto('/calendar');
    const nav = page.getByRole('banner').getByRole('navigation', { name: 'Main' });
    const cases = [
      { width: 768, zoom: '100%' },
      { width: 768, zoom: '150%' },
      { width: 1280, zoom: '150%' },
    ];
    for (const { width, zoom } of cases) {
      await page.setViewportSize({ width, height: 800 });
      await page.evaluate((z) => (document.documentElement.style.fontSize = z), zoom);
      for (const link of await nav.getByRole('link').all()) {
        const box = await link.boundingBox();
        const inside = !!box && box.x >= 0 && box.x + box.width <= width;
        expect(inside, `${width}px at ${zoom}`).toBe(true);
      }
      const { scrollWidth, clientWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(scrollWidth, `${width}px at ${zoom}`).toBeLessThanOrEqual(clientWidth);
    }
  });
});

test.describe('the senior', () => {
  test.use({ viewport: { width: 375, height: 700 } });

  test('keeps the top bar: one My day link in the banner and no bottom tab bar', async ({
    page,
    request,
  }) => {
    await resetDemo(request);
    await enterAs(page, 'senior');
    await expect(page).toHaveURL(/\/senior$/);
    const nav = page.getByRole('banner').getByRole('navigation', { name: 'Main' });
    await expect(nav.getByRole('link')).toHaveText(['My day']);
    await expect(menu(page)).toHaveCount(1);
    // In the top bar, not fixed to the bottom of the screen.
    const box = await nav.boundingBox();
    expect(!!box && box.y < 200).toBe(true);
    // The controls stay in the top bar: no Settings menu.
    await expect(page.getByTestId('zoom-value')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Settings' })).toHaveCount(0);
  });

  test('keeps only the menu row pinned while scrolling on a phone', async ({ page, request }) => {
    await resetDemo(request);
    await enterAs(page, 'senior');
    await scrollToBottom(page);
    const nav = page.getByRole('banner').getByRole('navigation', { name: 'Main' });
    await expect(nav).toBeInViewport();
    await expect.poll(async () => ((await nav.boundingBox())?.y ?? 99) < 10).toBe(true);
    // The brand row has scrolled out of view above the menu row.
    const brand = await page.getByRole('banner').getByRole('link', { name: /Care/ }).boundingBox();
    expect(!!brand && brand.y + brand.height <= 0).toBe(true);
  });
});

test.describe("the senior's section bar at a large text size", () => {
  test.use({ viewport: { width: 375, height: 700 } });

  const sections = (page: Page) => page.getByRole('tablist', { name: 'My day sections' });

  /** Every label's font size, after checking each is whole, inside its tab, and clear of Kaki. */
  async function checkSections(page: Page, where: string): Promise<number> {
    const sizes: number[] = [];
    for (const tab of await sections(page).getByRole('tab').all()) {
      const { lines, fits, size } = await tab.evaluate((el) => {
        const label = el.querySelector('.senior-tab-label')!;
        const box = label.getBoundingClientRect();
        const own = el.getBoundingClientRect();
        return {
          // One box per line: a word broken across lines ("Calen/dar") gives two.
          lines: label.getClientRects().length,
          fits:
            box.left >= own.left - 0.5 &&
            box.right <= own.right + 0.5 &&
            box.top >= own.top - 0.5 &&
            box.bottom <= own.bottom + 0.5,
          size: parseFloat(getComputedStyle(label).fontSize),
        };
      });
      const name = `${await tab.innerText()} ${where}`;
      expect(lines, name).toBe(1);
      expect(fits, name).toBe(true);
      const box = (await tab.boundingBox())!;
      expect(box.width, name).toBeGreaterThanOrEqual(48);
      expect(box.height, name).toBeGreaterThanOrEqual(48);
      sizes.push(size);
    }
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth, where).toBeLessThanOrEqual(clientWidth);
    // The page's last line clears the bar, however many rows it has (polled: the bar is measured
    // after the text size changes).
    await expect
      .poll(
        async () => {
          const bar = (await sections(page).boundingBox())!;
          const padding = await page.evaluate(() =>
            parseFloat(getComputedStyle(document.body).paddingBottom),
          );
          return padding >= bar.height - 1;
        },
        { message: `the page keeps room for the bar ${where}` },
      )
      .toBe(true);
    // Kaki sits above the bar, never over a tab.
    await expect
      .poll(
        async () => {
          const bar = (await sections(page).boundingBox())!;
          const orb = (await page.getByTestId('assistant-orb').boundingBox())!;
          return orb.y + orb.height <= bar.y;
        },
        { message: `Kaki stays above the bar ${where}` },
      )
      .toBe(true);
    return Math.min(...sizes);
  }

  test('labels grow with the text size, stay whole inside their tab, and Kaki stays clear', async ({
    page,
    request,
  }) => {
    await resetDemo(request);
    await enterAs(page, 'senior');
    await expect(sections(page).getByRole('tab')).toHaveCount(4);
    for (const width of [375, 320]) {
      await page.setViewportSize({ width, height: 700 });
      await page.evaluate(() => (document.documentElement.style.fontSize = '100%'));
      const normal = await checkSections(page, `at ${width}px, 100%`);
      await page.evaluate(() => (document.documentElement.style.fontSize = '125%'));
      await checkSections(page, `at ${width}px, 125%`);
      await page.evaluate(() => (document.documentElement.style.fontSize = '150%'));
      const large = await checkSections(page, `at ${width}px, 150%`);
      // The zoom setting is never undone by squeezing the labels to fit.
      expect(large, `at ${width}px`).toBeCloseTo(normal * 1.5, 0);
    }
    // On two rows the tabs still work as tabs: the arrow keys move along them.
    const today = sections(page).getByRole('tab', { name: 'Today', exact: true });
    await today.click();
    await today.press('ArrowRight');
    const calendar = sections(page).getByRole('tab', { name: 'Calendar', exact: true });
    await expect(calendar).toHaveAttribute('aria-selected', 'true');
    await expect(calendar).toBeFocused();
    await calendar.press('ArrowLeft');
    await expect(today).toHaveAttribute('aria-selected', 'true');
  });

  test('the saved text size is followed from the first paint', async ({ page, request }) => {
    await resetDemo(request);
    await page.addInitScript(() => window.localStorage.setItem('careplus.zoom.v1', '150'));
    await page.setViewportSize({ width: 320, height: 640 });
    await enterAs(page, 'senior');
    await expect(sections(page).getByRole('tab')).toHaveCount(4);
    await checkSections(page, 'at 320px, saved 150%');
  });
});

test.describe('the calendar at a large text size', () => {
  test('no sideways scroll on a phone, with a task and the add buttons showing', async ({
    page,
    request,
  }) => {
    await resetDemo(request);
    const groupId = await clearDemoTasks(request);
    await addDemoTask(request, groupId, {
      title: 'Blood pressure tablet',
      start_date: isoDay(0),
      time: '08:00',
      repeat: 'daily',
    });
    await enterAs(page, 'family');
    await page.goto('/calendar');
    const tasks = page.getByTestId('day-tasks');
    const edit = tasks.getByRole('button', { name: 'Edit Blood pressure tablet', exact: true });
    await expect(edit).toBeVisible();
    await expect(page.getByLabel('Viewing as')).toBeVisible();
    await expect(page.getByTestId('add-appointment')).toBeVisible();
    for (const width of [375, 320]) {
      for (const zoom of ['125%', '150%']) {
        const where = `at ${width}px, ${zoom}`;
        await page.setViewportSize({ width, height: 700 });
        await page.evaluate((z) => (document.documentElement.style.fontSize = z), zoom);
        await expect
          .poll(
            () =>
              page.evaluate(
                () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
              ),
            { message: `no sideways scroll ${where}` },
          )
          .toBeLessThanOrEqual(0);
        // "Edit" stays one whole word, inside the screen.
        const { lines, right } = await edit.evaluate((el) => {
          const range = document.createRange();
          range.selectNodeContents(el);
          return {
            lines: new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size,
            right: el.getBoundingClientRect().right,
          };
        });
        expect(lines, where).toBe(1);
        expect(right, where).toBeLessThanOrEqual(width);
      }
    }
  });
});

test.describe('Settings menu', () => {
  test('opens, closes with Escape and returns focus, and closes on an outside click', async ({
    page,
  }) => {
    await enterAs(page, 'family');
    const button = page.getByRole('button', { name: 'Settings', exact: true });
    await expect(button).toHaveAttribute('aria-expanded', 'false');
    await button.click();
    await expect(button).toHaveAttribute('aria-expanded', 'true');
    const panel = page.getByRole('group', { name: 'Settings' });
    await expect(panel.getByTestId('zoom-value')).toBeVisible();
    await expect(panel.getByTestId('theme-toggle')).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();

    // Tab walks through the controls inside the panel.
    await page.keyboard.press('Tab');
    await expect(panel.getByRole('button', { name: 'Zoom out' })).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    await expect(button).toHaveAttribute('aria-expanded', 'false');
    await expect(button).toBeFocused();

    await button.click();
    await expect(panel).toBeVisible();
    await page.locator('main').click({ position: { x: 5, y: 5 } });
    await expect(panel).toHaveCount(0);
  });
});

test.describe('reduced motion', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('the menu highlight moves instantly', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    const indicator = page.locator('.mainnav-indicator');
    await expect(indicator).toHaveCount(1);
    // Whatever it transitions (it only gets a transition once the page has settled), it takes 0s.
    await expect
      .poll(() =>
        indicator.evaluate((el) =>
          getComputedStyle(el)
            .transitionDuration.split(',')
            .every((d) => parseFloat(d) === 0),
        ),
      )
      .toBe(true);

    // Settled: the page has painted once and the highlight may now transition (`.is-ready`).
    await expect(page.locator('.mainnav-list.is-ready')).toHaveCount(1);
    await expect
      .poll(() => indicator.evaluate((el) => getComputedStyle(el).transitionDuration))
      .toMatch(/^(0s(, )?)+$/);

    // Straight after a click it is already under the new link: no sliding to wait for.
    const family = menu(page).getByRole('link', { name: 'Family' });
    await family.click();
    await expect(page).toHaveURL(/\/family$/);
    const gap = await page.evaluate(() => {
      const bar = document.querySelector('.mainnav-indicator')?.getBoundingClientRect();
      const link = document.querySelector('.mainnav-link.active')?.getBoundingClientRect();
      return bar && link ? Math.abs(bar.x - link.x) : -1;
    });
    expect(gap).toBeGreaterThanOrEqual(0);
    expect(gap).toBeLessThanOrEqual(1);
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
