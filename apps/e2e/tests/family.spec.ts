import { expect, test, type Locator, type Page } from '@playwright/test';

import { API_URL, resetDemo } from './support';

// The family calendar in a real browser, stored by the API. With sign-in off the API seeds Mdm
// Lim's family group (Sarah, John and Emily) and her schedule, and a demo reset puts them back, so
// each test starts alike with Sarah as the viewer.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

// The sample title uses a typographic apostrophe, so match around it.
const DOCTOR = /Doctor.s appointment/;

/** The day `offset` days from today, `YYYY-MM-DD`: the sample schedule is relative to today. */
function isoDay(offset: number): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/** True once the month on screen has finished sliding in (a press mid-slide lands beside its day). */
async function monthSettled(page: Page) {
  await expect(
    page.locator('tbody[class*="-enter-active"], tbody[class*="-leave-active"]'),
  ).toHaveCount(0);
}

/**
 * Waits until the page has stopped scrolling: the app scrolls smoothly, which takes a few hundred
 * milliseconds, so the position must hold for several frames in a row.
 */
async function scrollSettled(page: Page) {
  await page.waitForFunction(
    () =>
      new Promise<boolean>((resolve) => {
        const y = window.scrollY;
        let frames = 0;
        const check = () => {
          if (window.scrollY !== y) return resolve(false);
          if (++frames >= 10) return resolve(true);
          requestAnimationFrame(check);
        };
        requestAnimationFrame(check);
      }),
  );
}

/**
 * The first `count` days an appointment can go on, read from the calendar on screen rather than
 * worked out here: days in the month shown that are today or later, as the page drew them from what
 * the API returned. In the last days of a month there may be too few left, so it turns to the next
 * month, as a person would, and waits for that month to finish sliding in.
 */
async function bookableDays(page: Page, count: number): Promise<string[]> {
  const inMonth = page.locator('.cal-cell:not(.outside) .cal-day');
  const open = page.locator('.cal-cell:not(.outside) .cal-day:not(.past)');
  const isos = (cells: Locator) =>
    cells.evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.iso ?? ''));

  await expect(inMonth.first()).toBeVisible();
  await monthSettled(page);
  let days = await isos(open);
  if (days.length < count) {
    const shown = await inMonth.first().getAttribute('data-iso');
    await page.getByRole('button', { name: 'Next month' }).click();
    await expect(inMonth.first()).not.toHaveAttribute('data-iso', shown ?? '');
    await monthSettled(page);
    days = await isos(open);
  }
  expect(days.length, 'days left to book on the calendar').toBeGreaterThanOrEqual(count);
  return days.slice(0, count);
}

/** The open appointment's details panel. */
const details = (page: Page, title: RegExp) =>
  page.locator('article').filter({ has: page.getByRole('heading', { level: 2, name: title }) });

/** One person's row in a details panel or availability list. */
const row = (scope: Locator, name: string) => scope.getByRole('listitem').filter({ hasText: name });

test('the Care Team screen is gone, and an old link lands on the calendar', async ({ page }) => {
  await page.goto('/');
  const menu = page.getByRole('navigation', { name: 'Main' });
  await expect(menu.getByRole('link', { name: 'Care Team' })).toHaveCount(0);
  await expect(menu.getByRole('link', { name: 'Calendar' })).toBeVisible();
  await expect(menu.getByRole('link', { name: 'Family' })).toBeVisible();

  for (const oldLink of ['/care-team', '/care-team/cases/case-1']) {
    await page.goto(oldLink);
    await expect(page).toHaveURL('/calendar');
    await expect(page.getByRole('heading', { level: 1, name: 'Calendar' })).toBeVisible();
  }
});

test('the calendar lists what is coming up and opens an appointment’s details', async ({
  page,
}) => {
  await page.goto('/calendar');
  await expect(page.getByRole('heading', { level: 2, name: 'Coming up' })).toBeVisible();

  await page.getByRole('button', { name: DOCTOR }).click();
  const panel = details(page, DOCTOR);
  await expect(panel).toContainText('10:00 am to 12:00 pm');
  await expect(panel).toContainText('Neighbourhood polyclinic');
  await expect(panel).toContainText('Registration closes');

  // Two family members are free, one is not, and nobody has taken it yet.
  await expect(row(panel, 'Sarah')).toContainText('Available');
  await expect(row(panel, 'John')).toContainText('Available');
  await expect(row(panel, 'Emily')).toContainText('Not available');
  await expect(panel).not.toContainText('Helping');

  await panel.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByRole('button', { name: DOCTOR })).toContainText('Needs helper');
});

test('a family member can take an appointment, and the others see who is helping', async ({
  page,
}) => {
  await page.goto('/calendar');
  await page.getByRole('button', { name: DOCTOR }).click();
  const panel = details(page, DOCTOR);

  // Sarah is the viewer to begin with.
  await page.getByRole('button', { name: /I.ll help/ }).click();
  await expect(row(panel, 'Sarah')).toContainText('Helping');
  await expect(panel.getByText(/You.re helping with this/)).toBeVisible();

  // The choice is kept when the page is opened again.
  await page.reload();
  await page.getByRole('button', { name: DOCTOR }).click();
  await expect(row(panel, 'Sarah')).toContainText('Helping');

  // John sees that Sarah has it, and can help as well: more than one person can.
  await page.getByLabel('Viewing as').selectOption({ label: 'John' });
  await expect(row(panel, 'Sarah')).toContainText('Helping');
  await page.getByRole('button', { name: /I.ll help/ }).click();
  await expect(row(panel, 'John')).toContainText('Helping');
  await panel.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByRole('button', { name: DOCTOR })).toContainText('Sarah, John');

  // Stepping back takes only that person off.
  await page.getByRole('button', { name: DOCTOR }).click();
  await page.getByRole('button', { name: 'Step back' }).click();
  await expect(row(panel, 'John')).not.toContainText('Helping');
  await expect(row(panel, 'Sarah')).toContainText('Helping');
});

test('a family member can say they cannot make it, and change their mind', async ({ page }) => {
  await page.goto('/calendar');
  await page.getByRole('button', { name: DOCTOR }).click();
  const panel = details(page, DOCTOR);

  await page.getByRole('button', { name: /I can.t make it/ }).click();
  await expect(row(panel, 'Sarah')).toContainText('Not available');

  await page.getByRole('button', { name: /I.m available/ }).click();
  await expect(row(panel, 'Sarah')).toContainText('Available');
  await expect(row(panel, 'Sarah')).not.toContainText('Not available');
});

test('a family member can share when they are free, and everyone sees it', async ({ page }) => {
  await page.goto('/family');
  // The demo can switch between its family members; with sign-in on you are always yourself.
  await page.getByRole('button', { name: /I.m John/ }).click();
  const card = page.locator('.card').filter({
    has: page.getByRole('heading', { level: 3, name: 'John' }),
  });
  await expect(card).toContainText('You');

  // "Kopi & Chat" is on the fourth day out, from 3:00 to 4:30 pm: paint 3 pm and 4 pm free by
  // pressing on the 3 pm hour and dragging down to 4 pm.
  await paint(page, isoDay(4), 7, 8);
  const johnsWindow = row(page.locator('main'), 'John').filter({ hasText: '3:00 pm to 5:00 pm' });
  await expect(johnsWindow).toContainText('Available');

  // Saved by the API: still there after a reload.
  await page.reload();
  await expect(johnsWindow).toContainText('Available');

  await page.goto('/calendar');
  await page.getByRole('button', { name: /Kopi & Chat/ }).click();
  await expect(row(details(page, /Kopi & Chat/), 'John')).toContainText('Available');
});

test('a weekly appointment can be added, and shows on each week', async ({ page, request }) => {
  await page.goto('/calendar');
  await page.getByTestId('add-appointment').click();
  await page.getByTestId('add-title').fill('Swimming');
  await page.getByLabel('Date', { exact: true }).fill(isoDay(1));
  await page.getByLabel('From', { exact: true }).fill('16:00');
  await page.getByLabel('To', { exact: true }).fill('17:00');
  await page.getByTestId('add-repeat').selectOption('weekly');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Added Swimming' })).toBeVisible();

  // Stored once, shown on every week: the API lists a day for each week ahead.
  const calendar = await (await request.get(`${API_URL}/v1/people/mdm-lim/calendar`)).json();
  const weeks = calendar.appointments
    .filter((o: { title: string }) => o.title === 'Swimming')
    .map((o: { date: string }) => o.date);
  expect(weeks.slice(0, 2)).toEqual([isoDay(1), isoDay(8)]);

  await page
    .getByRole('button', { name: /Swimming/ })
    .first()
    .click();
  await expect(details(page, /Swimming/)).toContainText('Every week');

  // Removing it removes every week of it.
  page.once('dialog', (dialog) => void dialog.accept());
  await page.getByTestId('remove-appointment').click();
  await expect(page.getByRole('status').filter({ hasText: 'Deleted Swimming' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Swimming/ })).toHaveCount(0);
});

/** One hour of the availability painter: `slot` 0 is 8 am. */
const hour = (page: Page, day: string, slot: number) =>
  page.locator(`.painter [data-day="${day}"][data-slot="${slot}"]`);

/** Presses on one hour and drags to another, like a person painting their week. */
async function paint(page: Page, day: string, from: number, to: number) {
  // The painter is under "Choose exact hours"; the quick picks come first.
  const exact = page.getByTestId('exact-hours-toggle');
  if ((await exact.getAttribute('aria-expanded')) !== 'true') await exact.click();
  // Centred, so the hour the drag ends on is on screen too.
  await hour(page, day, from).evaluate((el) =>
    el.scrollIntoView({ block: 'center', behavior: 'instant' }),
  );
  const start = await hour(page, day, from).boundingBox();
  const end = await hour(page, day, to).boundingBox();
  if (!start || !end) throw new Error('painter hour not on screen');
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2, { steps: 4 });
  await page.mouse.up();
}

test('quick picks save a part of the day, show it, and turn it off again', async ({ page }) => {
  await page.goto('/family');
  const day = isoDay(3);
  const picks = page.getByTestId('quick-picks').locator(`[data-day="${day}"]`);
  const morning = picks.getByRole('button', { name: 'Morning', exact: true });
  await expect(morning).toHaveAttribute('aria-pressed', 'false');

  await morning.click();
  await expect(morning).toHaveAttribute('aria-pressed', 'true');
  const sarahs = row(page.locator('main'), 'Sarah').filter({ hasText: 'Morning' });
  await expect(sarahs.first()).toBeVisible();

  // Saved through the API: still on after a reload.
  await page.reload();
  await expect(morning).toHaveAttribute('aria-pressed', 'true');

  // All day takes the place of the morning; the hour painter is still one click away.
  await picks.getByRole('button', { name: 'All day', exact: true }).click();
  await expect(picks.getByRole('button', { name: 'All day', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(morning).toHaveAttribute('aria-pressed', 'false');
  await page.getByTestId('exact-hours-toggle').click();
  await expect(page.getByTestId('exact-hours-toggle')).toHaveAttribute('aria-expanded', 'true');
  await expect(hour(page, day, 0)).toHaveClass(/available/);

  await picks.getByRole('button', { name: 'All day', exact: true }).click();
  await expect(picks.getByRole('button', { name: 'All day', exact: true })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
});

test('painting busy hours, clearing them, and using the keyboard', async ({ page }) => {
  await page.goto('/family');
  const day = isoDay(2);

  // Busy mode: the painted hours are busy.
  await page.getByTestId('exact-hours-toggle').click();
  await page.getByRole('button', { name: 'Busy', exact: true }).click();
  await paint(page, day, 2, 4);
  for (const slot of [2, 3, 4]) await expect(hour(page, day, slot)).toHaveClass(/unavailable/);

  // Starting a drag on an hour already busy clears instead.
  await paint(page, day, 2, 4);
  for (const slot of [2, 3, 4]) await expect(hour(page, day, slot)).toHaveClass(/empty/);

  // A keyboard ticks one hour at a time.
  await page.getByRole('button', { name: 'Free', exact: true }).click();
  await hour(page, day, 0).focus();
  await page.keyboard.press('Enter');
  await expect(hour(page, day, 0)).toHaveClass(/available/);
  await page.keyboard.press('Enter');
  await expect(hour(page, day, 0)).toHaveClass(/empty/);
});

test('adding an appointment shades the calendar by who is free, and a day can be tapped', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/calendar');
  const [day] = await bookableDays(page, 1);
  await page.getByTestId('add-appointment').click();
  // The demo family is free on some days and not others, so some days are shaded.
  await expect(page.locator('.cal-day.heat').first()).toBeVisible();

  await page.locator(`[data-iso="${day}"]`).click();
  await expect(page.getByLabel('Date', { exact: true })).toHaveValue(day);
  await expect(page.getByTestId('free-then')).toBeVisible();
});

test('a one-off appointment can be dragged to another day, and edited', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/calendar');
  // Two days in the month on screen, so adding the appointment does not turn the month.
  const [fromDay, toDay] = await bookableDays(page, 2);
  await page.getByTestId('add-appointment').click();
  await page.getByTestId('add-title').fill('Haircut');
  await page.getByLabel('Date', { exact: true }).fill(fromDay);
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Added Haircut' })).toBeVisible();
  await monthSettled(page);
  // Adding it scrolls the day's list under the calendar into view, which takes a day early in the
  // month off the top of the screen: bring the day back, as a person would, before dragging.
  await scrollSettled(page);
  await page
    .locator(`[data-iso="${fromDay}"]`)
    .evaluate((el) => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await scrollSettled(page);

  const chip = page.locator('[data-appt]').filter({ hasText: 'Haircut' });
  const from = await chip.boundingBox();
  const to = await page.locator(`[data-iso="${toDay}"]`).boundingBox();
  if (!from || !to) throw new Error('calendar not on screen');
  await page.mouse.move(from.x + 5, from.y + 5);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByRole('status').filter({ hasText: 'Moved to' })).toBeVisible();
  await expect(
    page.locator(`[data-iso="${toDay}"] [data-appt]`).filter({ hasText: 'Haircut' }),
  ).toBeVisible();

  await page.locator(`[data-iso="${toDay}"]`).click();
  await page.getByRole('button', { name: /Haircut/ }).click();
  await page.getByTestId('edit-appointment').click();
  await page.getByTestId('add-title').fill('Haircut and shave');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('button', { name: /Haircut and shave/ }).first()).toBeVisible();
});
