import { expect, test, type Page } from '@playwright/test';

import { resetDemo } from './support';

// Words and geometry around daily readings: what a bar's height says against the Usual day line,
// when the screens may say "today", and the Now label staying on the page at any hour.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

async function openSeniorToday(page: Page) {
  await page.goto('/senior');
  await page.getByRole('tab', { name: 'Today', exact: true }).click();
  await expect(page.locator('.week-chart .bar-btn')).toHaveCount(7);
}

/** Each bar's height as a share of the Usual day line's height, with the % its own name gives. */
function barReadings(page: Page) {
  return page.evaluate(() => {
    const plot = document.querySelector('.week-chart .plot') as HTMLElement;
    const line = document.querySelector('.week-chart .usual-line') as HTMLElement;
    const box = plot.getBoundingClientRect();
    const baseline = box.top + plot.clientTop + plot.clientHeight;
    const lineHeight = baseline - line.getBoundingClientRect().bottom;
    return [...document.querySelectorAll('.week-chart .bar-btn')].map((button) => {
      const bar = (button.querySelector('.bar') as HTMLElement).getBoundingClientRect();
      const label = button.getAttribute('aria-label') ?? '';
      return {
        label,
        stated: Number(/(\d+)% of your usual day/.exec(label)?.[1]),
        drawn: (bar.height / lineHeight) * 100,
        gap: Math.abs(baseline - bar.bottom),
      };
    });
  });
}

test.describe('the senior chart', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('a bar reads true against the Usual day line, chosen or not', async ({ page }) => {
    await openSeniorToday(page);
    for (const reading of await barReadings(page)) {
      expect(Math.abs(reading.drawn - reading.stated), reading.label).toBeLessThan(2.5);
      expect(reading.gap, reading.label).toBeLessThan(1);
    }
    // A tapped bar keeps its place on the baseline, so it cannot seem to pass the line.
    await page.locator('.week-chart .bar-btn').nth(5).click();
    for (const reading of await barReadings(page)) {
      expect(Math.abs(reading.drawn - reading.stated), reading.label).toBeLessThan(2.5);
      expect(reading.gap, reading.label).toBeLessThan(1);
    }
  });

  test('the axis says what the first bar says', async ({ page }) => {
    await openSeniorToday(page);
    const first = (await page.locator('.week-chart .bar-btn').first().getAttribute('aria-label'))!;
    const axis = page.locator('.week-chart .labels');
    await expect(axis.locator('span').first()).toHaveText(first.split(',')[0]);
    await expect(axis).toContainText('Latest day');
  });

  test('a visible hint says the bars can be tapped, and tapping shows that day', async ({
    page,
  }) => {
    await openSeniorToday(page);
    const hint = page.getByTestId('week-hint');
    await expect(hint).toHaveText('Tap a bar to see that day.');
    const group = page.getByRole('group', { name: 'Steps on each day. Choose a day for details.' });
    await expect(group).toHaveAttribute(
      'aria-describedby',
      new RegExp(`(^| )${await hint.getAttribute('id')}( |$)`),
    );

    const bar = page.locator('.week-chart .bar-btn').first();
    await bar.click();
    await expect(bar).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.chart-detail')).toContainText('6 days ago');
  });
});

test.describe('saying today', () => {
  test('Home names the day of an older reading and never says today for it', async ({ page }) => {
    await page.clock.setFixedTime(new Date(2026, 10, 1, 12, 0));
    await page.goto('/');
    await expect(page.getByTestId('today-sample')).toBeVisible();
    await expect(page.locator('#today-heading')).toHaveText('Mdm Lim on Tue, 18 Aug');
    await expect(page.getByTestId('hero-steps-label')).toHaveText('Steps on Tue, 18 Aug');
    await expect(page.locator('.hero-lede')).toContainText(/She walked .* on Tue, 18 Aug,/);
    await expect(page.locator('.hero')).not.toContainText(/today|so far/i);
    await expect(page.getByTestId('counted-back')).toHaveText(
      'Days are counted back from the latest reading, Tue, 18 Aug.',
    );
  });

  test('Home says today when the reading is from today', async ({ page }) => {
    await page.clock.setFixedTime(new Date(2026, 7, 18, 12, 0));
    await page.goto('/');
    await expect(page.locator('#today-heading')).toHaveText('Today with Mdm Lim');
    await expect(page.getByTestId('hero-steps-label')).toHaveText('Today so far');
    await expect(page.getByTestId('fortnight-sample')).toBeVisible();
    await expect(page.getByTestId('counted-back')).toHaveCount(0);
  });

  test('the senior is told the numbers are samples, and from when', async ({ page }) => {
    await page.clock.setFixedTime(new Date(2026, 10, 1, 12, 0));
    await openSeniorToday(page);
    await expect(page.getByTestId('steps-sample')).toHaveText('Sample numbers');
    await expect(page.getByTestId('steps-from')).toHaveText('These steps are from Tue, 18 Aug.');
    await expect(page.getByTestId('steps-sample-note')).toHaveText(
      'These are sample numbers, not your own steps.',
    );
    await expect(page.getByTestId('week-counted-back')).toHaveText(
      '“Days ago” means days before Tue, 18 Aug.',
    );
    // The date stays whole, and the note is part of the chart's description.
    await expect(page.getByTestId('week-counted-back')).toContainText('Tue,\u00a018\u00a0Aug');
    const hintId = await page.getByTestId('week-hint').getAttribute('id');
    const noteId = await page.getByTestId('week-counted-back').getAttribute('id');
    await expect(
      page.getByRole('group', { name: 'Steps on each day. Choose a day for details.' }),
    ).toHaveAttribute('aria-describedby', `${hintId} ${noteId}`);
  });

  test('the senior needs no counted-back line when the steps are from today', async ({ page }) => {
    await page.clock.setFixedTime(new Date(2026, 7, 18, 12, 0));
    await openSeniorToday(page);
    await expect(page.getByTestId('steps-from')).toHaveText('These steps are from today.');
    await expect(page.getByTestId('week-counted-back')).toHaveCount(0);
    await expect(
      page.getByRole('group', { name: 'Steps on each day. Choose a day for details.' }),
    ).toHaveAttribute(
      'aria-describedby',
      (await page.getByTestId('week-hint').getAttribute('id'))!,
    );
  });

  test('the Home axis says what the first bar says', async ({ page }) => {
    await page.goto('/');
    const chart = page.getByRole('group', { name: /Steps on each of the last days/ });
    const first = (await chart.getByRole('button').first().getAttribute('aria-label'))!;
    await expect(chart.locator('.labels span').first()).toHaveText(first.split(':')[0]);
  });
});

/** The hour marks still showing that the Now label touches. */
function marksTouchingNow(page: Page) {
  return page.evaluate(() => {
    const label = document.querySelector('.timeline-now-label')!.getBoundingClientRect();
    return [...document.querySelectorAll<HTMLElement>('.timeline-hour')]
      .filter((mark) => getComputedStyle(mark).visibility === 'visible')
      .filter((mark) => {
        const box = mark.getBoundingClientRect();
        return box.left < label.right && box.right > label.left;
      })
      .map((mark) => mark.textContent);
  });
}

test.describe('the Now label and the hour marks', () => {
  test('stay apart when the window or the zoom changes on an open page', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 812 });
    await page.clock.setFixedTime(new Date(2026, 10, 1, 12, 45));
    await page.goto('/');
    await expect(page.locator('.timeline-now-label')).toBeVisible();
    await expect.poll(() => marksTouchingNow(page)).toEqual([]);

    for (const width of [375, 800, 1280]) {
      await page.setViewportSize({ width, height: 812 });
      await expect.poll(() => marksTouchingNow(page), `at ${width}px`).toEqual([]);
    }

    // The app's own zoom buttons, as a person would press them. Some widths keep them in Settings.
    const zoomIn = page.getByRole('button', { name: 'Zoom in' });
    if (!(await zoomIn.isVisible())) await page.getByRole('button', { name: 'Settings' }).click();
    await zoomIn.click();
    await expect.poll(() => marksTouchingNow(page), 'one step in').toEqual([]);
    await zoomIn.click();
    await expect.poll(() => marksTouchingNow(page), 'two steps in').toEqual([]);
  });

  for (const [width, hour, minute] of [
    [375, 22, 30],
    [375, 23, 30],
    [375, 12, 45],
    [1280, 12, 45],
    [1280, 21, 30],
  ]) {
    test(`at ${width}px and ${hour}:${minute} no hour mark peeks out from behind it`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.clock.setFixedTime(new Date(2026, 10, 1, hour, minute));
      await page.goto('/');
      await expect(page.locator('.timeline-now-label')).toBeVisible();
      await expect.poll(() => marksTouchingNow(page)).toEqual([]);
    });
  }
});

test.describe('Home at 375 px', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('the day buttons fit at 150% zoom, today and on an earlier day', async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem('careplus.zoom.v1', '150'));
    await page.goto('/');
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
    await expect(page.getByTestId('day-timeline')).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);
    await page.getByRole('button', { name: 'Day before' }).click();
    await expect(page.getByTestId('timeline-today')).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);
  });

  for (const [hour, minute] of [
    [0, 5],
    [6, 30],
    [12, 0],
    [18, 30],
    [20, 30],
    [21, 30],
    [22, 30],
    [23, 59],
  ]) {
    test(`does not scroll sideways at ${hour}:${String(minute).padStart(2, '0')}`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(new Date(2026, 10, 1, hour, minute));
      await page.goto('/');
      const label = page.locator('.timeline-now-label');
      await expect(label).toBeVisible();
      const { scrollWidth, clientWidth, left, right } = await label.evaluate((element) => {
        const box = element.getBoundingClientRect();
        const root = document.documentElement;
        return {
          scrollWidth: root.scrollWidth,
          clientWidth: root.clientWidth,
          left: box.left,
          right: box.right,
        };
      });
      expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
      expect(left).toBeGreaterThanOrEqual(0);
      expect(right).toBeLessThanOrEqual(clientWidth);
    });
  }
});
