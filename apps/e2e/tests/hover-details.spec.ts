import { expect, test } from '@playwright/test';

// Details that pop out on hover: the two-week chart's figures, and the calendar's appointments and
// tasks in full. A keyboard and a tap reach the chart's figures too.

test.use({ viewport: { width: 1440, height: 900 } });

test('sample activity counts back from the latest reading, and is labelled sample', async ({
  page,
}) => {
  await page.goto('/');
  const chart = page.getByRole('group', { name: /Steps on each of the last days/ });
  await expect(chart).toContainText('13 days ago');
  await expect(chart).toContainText('Latest');
  await expect(chart.getByRole('button').last()).toHaveAttribute('aria-label', /^Latest reading: /);
  await expect(page.getByTestId('fortnight-sample')).toHaveText('Sample');
  await expect(page.getByTestId('today-sample')).toHaveText('Sample');
  await expect(page.getByText('Demo day')).toHaveCount(0);

  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  await page.getByRole('tab', { name: 'Today', exact: true }).click();
  await expect(page.getByTestId('steps-sample')).toHaveText('Sample numbers');
  await expect(page.getByTestId('steps-from')).toContainText('These steps are from');
  const week = page.getByRole('group', { name: 'Steps on each day. Choose a day for details.' });
  await expect(week).toContainText('6 days ago');
  await expect(week).toContainText('Latest day');
  await expect(week.getByRole('button').first()).toHaveAttribute('aria-label', /^6 days ago, /);
});

test('the chart shows a day’s figures only while its bar is pointed at, focused or tapped', async ({
  page,
}) => {
  await page.goto('/');
  const chart = page.getByRole('group', { name: /Steps on each of the last days/ });
  const bars = chart.getByRole('button');
  const tip = page.getByTestId('chart-tip');
  await expect(bars).toHaveCount(14);
  await expect(tip).toHaveCount(0);

  // Hover: the figures for that bar pop out; moving off the chart hides them.
  await bars.nth(4).hover();
  await expect(tip).toContainText(/steps/);
  await expect(tip).toContainText(/% of her usual day/);
  const label = (await bars.nth(4).getAttribute('aria-label')) ?? '';
  // Counted back from the latest reading, never a calendar date.
  await expect(tip).toContainText(label.split(':')[0]);
  expect(label).toMatch(/^9 days ago: /);
  await page.mouse.move(5, 5);
  await expect(tip).toHaveCount(0);

  // Keyboard: focus shows them, the arrow keys move along, Escape hides them.
  await bars.last().focus();
  await expect(tip).toBeVisible();
  await page.keyboard.press('ArrowLeft');
  await expect(bars.nth(12)).toBeFocused();
  await expect(tip).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(tip).toHaveCount(0);

  // A tap keeps them showing after the pointer leaves; a second tap hides them.
  await bars.nth(2).click();
  await page.mouse.move(5, 5);
  await page.locator('body').evaluate((body) => (document.activeElement as HTMLElement)?.blur());
  await expect(tip).toBeVisible();
  await bars.nth(2).click();
  await page.mouse.move(5, 5);
  await page.locator('body').evaluate(() => (document.activeElement as HTMLElement)?.blur());
  await expect(tip).toHaveCount(0);
});

test('pointing at a calendar chip pops out the whole appointment, and "+ more" lists the rest', async ({
  page,
}) => {
  await page.goto('/calendar');
  const chip = page.locator('.cal-day:not(.past) .cal-chip:not(.kind-task)').first();
  await chip.scrollIntoViewIfNeeded();
  // The card is the chip's next sibling, inside the same `.cal-item`.
  const pop = chip.locator('xpath=following-sibling::*[1]');
  await expect(pop).toHaveAttribute('data-testid', 'cal-pop');
  await expect(pop).toBeHidden();

  await chip.hover();
  await expect(pop).toBeVisible();
  await expect(pop).toContainText(/\d{1,2}:\d{2} (am|pm) – \d{1,2}:\d{2} (am|pm)/);
  await expect(pop).toContainText((await chip.innerText()).trim());

  const more = page.locator('.cal-day:not(.past) .cal-more').first();
  const morePop = more.locator('xpath=following-sibling::*[1]');
  await more.hover();
  await expect(morePop).toBeVisible();
  const count = Number(/\d+/.exec(await more.innerText())?.[0]);
  await expect(morePop.locator('.cal-pop-row')).toHaveCount(count);
  await expect(pop).toBeHidden();
});
