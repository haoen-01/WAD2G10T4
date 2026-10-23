import { expect, test, type Page } from '@playwright/test';

import { demoOccurrence, resetDemo } from './support';

// The interaction layer added in the interface redesign: text size, calendar filters and keyboard
// moves, undo, taking an appointment away as a calendar file, and Home's links and chart. The
// family calendar is seeded by the API and a demo reset puts it back, so each test starts from the
// same sample (Mdm Lim's schedule with Sarah, John and Emily, Sarah as the viewer).

const DOCTOR = /Doctor.s appointment/;
const PHYSIO = /Physiotherapy session/;

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

/** "Sunday, 11 October": the app's long day format, for the day `offset` days from today. */
function longDay(offset: number): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  const weekday = day.toLocaleDateString('en-GB', { weekday: 'long' });
  const month = day.toLocaleDateString('en-GB', { month: 'long' });
  return `${weekday}, ${day.getDate()} ${month}`;
}

const details = (page: Page, title: RegExp) =>
  page.locator('article').filter({ has: page.getByRole('heading', { level: 2, name: title }) });

test('the chosen zoom applies to the whole app and is remembered', async ({ page }) => {
  await page.goto('/calendar');
  const html = page.locator('html');
  const value = page.getByTestId('zoom-value');
  await expect(value).toHaveText('100%');

  await page.getByRole('button', { name: 'Zoom in' }).click();
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await expect(value).toHaveText('125%');
  await expect(html).toHaveAttribute('style', /font-size: 125%/);

  await page.reload();
  await expect(value).toHaveText('125%');

  // Pressing the percentage puts it back to 100%.
  await value.click();
  await expect(value).toHaveText('100%');
  await expect(html).not.toHaveAttribute('style', /font-size/);
});

test('light and dark mode switch from the top bar and are remembered', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/');
  const html = page.locator('html');
  await expect(html).toHaveAttribute('data-bs-theme', 'light');

  await page.getByTestId('theme-toggle').click();
  await expect(html).toHaveAttribute('data-bs-theme', 'dark');
  await page.reload();
  await expect(html).toHaveAttribute('data-bs-theme', 'dark');

  await page.getByTestId('theme-toggle').click();
  await expect(html).toHaveAttribute('data-bs-theme', 'light');
});

test('the calendar can show only what still needs a helper, and everything again', async ({
  page,
}) => {
  await page.goto('/calendar');
  const coming = page.locator('section').filter({
    has: page.getByRole('heading', { level: 2, name: 'Coming up' }),
  });
  await expect(coming.getByRole('button', { name: /Morning Tai Chi/ })).toBeVisible();

  // Exact: appointment cards that need a helper say "Needs helper" too.
  const onlyOpen = page.getByRole('button', { name: 'Needs helper', exact: true });
  await onlyOpen.click();
  await expect(onlyOpen).toHaveAttribute('aria-pressed', 'true');
  await expect(coming.getByRole('button', { name: /Morning Tai Chi/ })).toHaveCount(0);
  // Today has nothing on it, so the calendar moves to the first day that still needs someone.
  await expect(page.getByRole('heading', { level: 2, name: longDay(1) })).toBeVisible();
  await expect(page.getByRole('button', { name: DOCTOR })).toBeVisible();

  await page.getByRole('button', { name: 'Show all' }).first().click();
  await expect(coming.getByRole('button', { name: /Morning Tai Chi/ })).toBeVisible();
});

test('turning on the helper filter closes details it hides and shows what matches', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/calendar?appointment=${encodeURIComponent(demoOccurrence('demo-taichi', 2))}`);
  await expect(details(page, /Morning Tai Chi/)).toBeVisible();

  await page.getByRole('button', { name: 'Needs helper', exact: true }).click();
  await expect(details(page, /Morning Tai Chi/)).toHaveCount(0);
  await expect(page.getByRole('button', { name: DOCTOR })).toBeVisible();
});

test('a kind can be hidden from the calendar with its legend chip', async ({ page }) => {
  await page.goto('/calendar');
  const medical = page.getByRole('button', { name: 'Medical visit', exact: true });
  await medical.click();
  await expect(medical).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: DOCTOR })).toHaveCount(0);
  await medical.click();
  await expect(page.getByRole('button', { name: DOCTOR })).toBeVisible();
});

test('the arrow keys move between days in the calendar', async ({ page }) => {
  await page.goto('/calendar');
  await expect(page.getByRole('heading', { level: 2, name: longDay(0) })).toBeVisible();

  await page.getByRole('button', { name: /, today:/ }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('heading', { level: 2, name: longDay(1) })).toBeVisible();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('heading', { level: 2, name: longDay(8) })).toBeVisible();
});

test('stepping back from an appointment can be undone', async ({ page }) => {
  await page.goto('/calendar');
  await page.getByRole('button', { name: PHYSIO }).click();
  const panel = details(page, PHYSIO);
  const sarah = panel.getByRole('listitem').filter({ hasText: 'Sarah' });
  await expect(sarah).toContainText('Helping');

  await page.getByRole('button', { name: 'Step back' }).click();
  await expect(sarah).not.toContainText('Helping');

  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(sarah).toContainText('Helping');
});

test('removing a shared time can be undone', async ({ page }) => {
  await page.goto('/family');
  // Sarah (the viewer) has said she cannot help on the ninth day out.
  const remove = page.getByRole('button', { name: /^Remove / });
  await expect(remove).toHaveCount(1);

  await remove.click();
  await expect(page.getByRole('button', { name: /^Remove / })).toHaveCount(0);

  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByRole('button', { name: /^Remove / })).toHaveCount(1);
});

test('an appointment can be saved as a calendar file', async ({ page }) => {
  await page.goto('/calendar');
  await page.getByRole('button', { name: DOCTOR }).click();

  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Add to my calendar' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^mdm-lim-doctor-s-appointment-\d{4}-\d{2}-\d{2}\.ics$/);
});

const needsSection = (page: Page) =>
  page.locator('section').filter({
    has: page.getByRole('heading', { name: 'Needs someone to go along' }),
  });

/** "Mon, 19 Oct": the app's short day format, for the day `offset` days from today. */
function shortDay(offset: number): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  const weekday = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][day.getDay()];
  const month = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ')[day.getMonth()];
  return `${weekday}, ${day.getDate()} ${month}`;
}

test('Home lists visits that need someone, and each opens in the calendar', async ({ page }) => {
  await page.goto('/');
  const needs = needsSection(page);
  // The actual day and its start and end, never "Tomorrow" or "In 7 days".
  await expect(needs.getByRole('link', { name: DOCTOR })).toContainText(
    `${shortDay(1)}, 10:00 am – 12:00 pm`,
  );
  await needs.getByRole('link', { name: DOCTOR }).click();

  await expect(page).toHaveURL(
    `/calendar?appointment=${encodeURIComponent(demoOccurrence('demo-doctor', 1))}`,
  );
  await expect(details(page, DOCTOR)).toBeVisible();
});

test('“I’ll go” on Home takes a visit without opening the calendar, and can be undone', async ({
  page,
}) => {
  await page.goto('/');
  const needs = needsSection(page);
  // Nobody is going yet, so the week ahead says so in words, not colour alone.
  await expect(page.locator('#home-week').getByText('No one going').first()).toBeVisible();

  await needs.getByRole('button', { name: /I’ll go with .* to Doctor.s appointment/ }).click();
  await expect(page.getByText(/You’re going to Doctor.s appointment/)).toBeVisible();
  await expect(needs.getByRole('link', { name: DOCTOR })).toHaveCount(0);
  await expect(page).toHaveURL('/');

  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(needs.getByRole('link', { name: DOCTOR })).toBeVisible();
});

test('Home’s fortnight chart reads out the day that is chosen', async ({ page }) => {
  await page.goto('/');
  const chart = page.getByRole('group', { name: /Steps on each of the last days/ });
  const bars = chart.getByRole('button');
  await expect(bars).toHaveCount(14);
  await expect(bars.last()).toHaveAttribute('aria-pressed', 'true');

  await bars.first().click();
  await expect(bars.first()).toHaveAttribute('aria-pressed', 'true');
  const label = (await bars.first().getAttribute('aria-label')) ?? '';
  const day = label.split(':')[0];
  await expect(page.locator('.chart-readout')).toContainText(/steps/);
  expect(day).toMatch(/^\w{3}, \d{1,2} \w{3}$/);
});
