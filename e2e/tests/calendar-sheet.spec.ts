import { expect, test, type Locator, type Page } from '@playwright/test';

import { isoDay, resetDemo } from './support';

// The calendar on a phone: a week strip, the day's agenda, and an appointment that opens in a
// bottom sheet (a real dialog) with the family's notes for that day. Every test resets the demo,
// which seeds one sample note by Sarah on tomorrow's doctor's visit.

test.use({ viewport: { width: 375, height: 812 } });

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

// The appointment itself, not the ask controls named after it ("Ask someone to go … to Doctor’s
// appointment", "Withdraw your ask … for …", "Yes, I’ll go to …", "Can’t go to …").
const DOCTOR = /^(?!Ask someone|Withdraw|Yes, I’ll go|Can’t go).*Doctor.s appointment/;
const dialog = (page: Page) => page.getByRole('dialog');
const appContent = (page: Page) => page.locator('#app');

/** Waits until an element has stopped moving (a sheet's spring has settled), then measures it. */
async function settledBox(locator: Locator) {
  let previous = '';
  await expect
    .poll(async () => {
      const box = await locator.boundingBox();
      const now = JSON.stringify(box);
      const same = now === previous;
      previous = now;
      return same;
    })
    .toBe(true);
  return (await locator.boundingBox())!;
}

/** Opens tomorrow's doctor's visit from the agenda; returns the card that opened it. */
async function openDoctor(page: Page, options: { visit?: boolean } = {}) {
  if (options.visit !== false) await page.goto('/calendar');
  await expect(page.getByTestId('week-strip')).toBeVisible();
  const tomorrow = page.locator(`[data-week-iso="${isoDay(1)}"]`);
  // Tomorrow can fall in next week (when today is a Saturday).
  if ((await tomorrow.count()) === 0) {
    await page.getByRole('button', { name: 'Next week' }).click();
  }
  await tomorrow.click();
  const card = page.getByRole('button', { name: DOCTOR });
  await card.click();
  await expect(dialog(page)).toBeVisible();
  return card;
}

test('the calendar is a week strip with buttons to change week, and no month grid', async ({
  page,
}) => {
  await page.goto('/calendar');
  const strip = page.getByTestId('week-strip');
  await expect(strip).toBeVisible();
  await expect(strip.locator('[data-week-iso]')).toHaveCount(7);
  await expect(page.locator('[data-iso]')).toHaveCount(0);

  const first = await strip.locator('[data-week-iso]').first().getAttribute('data-week-iso');
  await page.getByRole('button', { name: 'Next week' }).click();
  await expect(strip.locator('[data-week-iso]').first()).not.toHaveAttribute(
    'data-week-iso',
    first ?? '',
  );
  await page.getByRole('button', { name: 'Previous week' }).click();
  await expect(strip.locator('[data-week-iso]').first()).toHaveAttribute(
    'data-week-iso',
    first ?? '',
  );

  // A day's agenda sits right under the strip.
  await strip.locator(`[data-week-iso="${isoDay(0)}"]`).click();
  await expect(strip.locator(`[data-week-iso="${isoDay(0)}"]`)).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

test('the sheet is a real dialog: named, focused, and the page behind it is out of reach', async ({
  page,
}) => {
  await openDoctor(page);
  const sheet = dialog(page);
  await expect(sheet).toHaveAttribute('aria-modal', 'true');
  await expect(sheet).toHaveAccessibleName(DOCTOR);
  await expect(sheet.getByRole('heading', { level: 2, name: DOCTOR })).toBeFocused();
  await expect(appContent(page)).toHaveAttribute('inert', '');
  await expect(page.locator('body')).toHaveCSS('overflow', 'hidden');

  // It sits above the tab bar.
  await settledBox(sheet);
  const above = await page.evaluate(() => {
    const sheetBox = document.querySelector('[role="dialog"]')?.getBoundingClientRect();
    const top = sheetBox
      ? document.elementFromPoint(sheetBox.x + sheetBox.width / 2, sheetBox.bottom - 4)
      : null;
    return !!top?.closest('[role="dialog"]');
  });
  expect(above).toBe(true);

  // The appointment's own "Details" and the family's per-day notes are labelled apart.
  await expect(sheet.getByText('Details', { exact: true })).toBeVisible();
  await expect(sheet.getByRole('heading', { name: 'Family notes' })).toBeVisible();
});

test('Tab and Shift+Tab stay inside the sheet, wrapping at both ends', async ({ page }) => {
  await openDoctor(page);
  const sheet = dialog(page);
  const inside = () => page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'));
  const tabbables = sheet.locator(
    'a[href], button:not([disabled]), input:not([disabled]), select, textarea:not([disabled])',
  );
  const first = tabbables.first();
  const last = tabbables.last();

  await last.focus();
  await page.keyboard.press('Tab');
  await expect(first).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(last).toBeFocused();

  for (let step = 0; step < 40; step += 1) {
    await page.keyboard.press('Tab');
    expect(await inside(), `Tab ${step}`).toBe(true);
  }
  for (let step = 0; step < 40; step += 1) {
    await page.keyboard.press('Shift+Tab');
    expect(await inside(), `Shift+Tab ${step}`).toBe(true);
  }
});

test('Escape closes the sheet and focus goes back to the card that opened it', async ({ page }) => {
  const card = await openDoctor(page);
  await page.keyboard.press('Escape');
  await expect(dialog(page)).toHaveCount(0);
  await expect(card).toBeFocused();
  await expect(appContent(page)).not.toHaveAttribute('inert', /.*/);
  await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden');
});

test('the Close button and the backdrop close it', async ({ page }) => {
  const card = await openDoctor(page);
  await dialog(page).getByRole('button', { name: 'Close details' }).click();
  await expect(dialog(page)).toHaveCount(0);
  await expect(card).toBeFocused();

  await card.click();
  await expect(dialog(page)).toBeVisible();
  await page.getByTestId('sheet-backdrop').click({ position: { x: 187, y: 20 } });
  await expect(dialog(page)).toHaveCount(0);
});

test('dragging the top of the sheet down closes it; a short drag springs back', async ({
  page,
}) => {
  await openDoctor(page);
  const handle = page.locator('.sheet-handle');
  const box = await settledBox(handle);
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;

  // A short pull, then let go: back in place.
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 30, { steps: 6 });
  await page.waitForTimeout(400);
  await page.mouse.up();
  await expect(dialog(page)).toBeVisible();
  await expect
    .poll(async () => Math.abs(((await handle.boundingBox())?.y ?? 0) - box.y))
    .toBeLessThan(2);

  // A long pull closes it.
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 400, { steps: 12 });
  await page.mouse.up();
  await expect(dialog(page)).toHaveCount(0);
  await expect(appContent(page)).not.toHaveAttribute('inert', /.*/);
});

test('leaving the page with the sheet open does not leave the app locked', async ({ page }) => {
  // Open it from a page we can go back to inside the app.
  await page.goto('/');
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Calendar' })
    .click();
  await openDoctor(page, { visit: false });
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await expect(appContent(page)).not.toHaveAttribute('inert', /.*/);
  await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden');
});

test('the sample note is there; Sarah adds a note and deletes it', async ({ page }) => {
  await openDoctor(page);
  const notes = dialog(page).getByTestId('family-notes');
  await expect(notes.getByTestId('family-note')).toHaveCount(1);
  await expect(notes).toContainText("I'll bring her NRIC and health booklet");
  // Sarah wrote it, and she is the one looking.
  await expect(notes.getByTestId('family-note').first()).toContainText('You');

  await notes.getByLabel('Add a note').fill('Taxi is booked for 9 am');
  await notes.getByRole('button', { name: 'Add note' }).click();
  const added = notes.getByTestId('family-note').filter({ hasText: 'Taxi is booked for 9 am' });
  await expect(added).toBeVisible();
  await expect(notes.getByLabel('Add a note')).toHaveValue('');
  // Oldest first: the sample, then the new one.
  await expect(notes.getByTestId('family-note').last()).toContainText('Taxi is booked');

  // It is saved: still there after a reload.
  await page.reload();
  await page.getByRole('button', { name: DOCTOR }).click();
  await expect(dialog(page).getByText('Taxi is booked for 9 am')).toBeVisible();

  await dialog(page)
    .getByRole('button', { name: /^Delete your note: Taxi is booked/ })
    .click();
  // It asks first; Keep leaves the note alone.
  await expect(dialog(page).getByText('Delete this note?')).toBeVisible();
  await expect(dialog(page).getByRole('button', { name: 'Keep' })).toBeFocused();
  await dialog(page).getByRole('button', { name: 'Keep' }).click();
  await expect(dialog(page).getByText('Taxi is booked for 9 am')).toBeVisible();
  await dialog(page)
    .getByRole('button', { name: /^Delete your note: Taxi is booked/ })
    .click();
  await dialog(page).getByRole('button', { name: 'Yes, delete this note' }).click();
  await expect(dialog(page).getByText('Taxi is booked for 9 am')).toHaveCount(0);
  await expect(dialog(page).getByTestId('family-note')).toHaveCount(1);
});

test('John sees Sarah’s note, and has no way to delete it', async ({ page }) => {
  await openDoctor(page);
  await dialog(page).getByRole('button', { name: 'Close details' }).click();
  // The sheet slides away for a moment: let it go before looking for the card again.
  await expect(dialog(page)).toHaveCount(0);
  await page.getByLabel('Viewing as').selectOption({ label: 'John' });
  await page.getByRole('button', { name: DOCTOR }).click();

  const note = dialog(page).getByTestId('family-note');
  await expect(note).toHaveCount(1);
  await expect(note).toContainText('Sarah');
  await expect(note).not.toContainText('You');
  await expect(note.getByRole('button')).toHaveCount(0);
});

test('a refused note shows a message and keeps what was typed', async ({ page }) => {
  await page.route('**/notes', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'This day already has the most notes it can hold' }),
        })
      : route.continue(),
  );
  await openDoctor(page);
  const notes = dialog(page).getByTestId('family-notes');
  await notes.getByLabel('Add a note').fill('One more');
  await notes.getByRole('button', { name: 'Add note' }).click();
  await expect(notes.getByRole('alert')).toContainText('100');
  await expect(notes.getByLabel('Add a note')).toHaveValue('One more');
});

test('with reduced motion the sheet still opens and closes', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const card = await openDoctor(page);
  // No slide: it is already fully on screen, not still travelling up.
  const box = (await dialog(page).boundingBox())!;
  expect(Math.round(box.y + box.height)).toBe(812);
  await page.keyboard.press('Escape');
  await expect(dialog(page)).toHaveCount(0);
  await expect(card).toBeFocused();

  await card.click();
  await dialog(page).getByRole('button', { name: 'Close details' }).click();
  await expect(dialog(page)).toHaveCount(0);
});

test('the senior’s screen never asks for notes or the family feed', async ({ page }) => {
  const asked: string[] = [];
  page.on('request', (request) => {
    if (
      /\/(notes|activity)(\?|$)/.test(
        new URL(request.url()).pathname + new URL(request.url()).search,
      )
    ) {
      asked.push(request.url());
    }
  });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  await expect(page).toHaveURL(/\/senior$/);
  await page.waitForLoadState('networkidle');
  expect(asked).toEqual([]);
});

test('the sheet’s own messages are announced and reachable, and Undo works', async ({ page }) => {
  await openDoctor(page);
  const sheet = dialog(page);
  await sheet.getByRole('button', { name: /^I.ll help$/ }).click();
  await sheet.getByRole('button', { name: 'Step back' }).click();

  // The toast lives outside the inert app, above the sheet, in a live region.
  const toast = page.locator('.sl-toast').filter({ hasText: 'You stepped back' });
  await expect(toast).toBeVisible();
  await expect(page.locator('#app .sl-toast')).toHaveCount(0);
  await expect(page.locator('.sl-toasts')).toHaveAttribute('aria-live', 'polite');
  // By keyboard: Tab from the sheet's last control reaches Undo, Enter uses it.
  await sheet.locator('button:not([disabled]), textarea').last().focus();
  await page.keyboard.press('Tab');
  await expect(toast.getByRole('button', { name: 'Undo' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(toast).toHaveCount(0);
  // The toast held focus and is gone: focus is back in the sheet, not on the page body.
  await expect
    .poll(() => page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]')))
    .toBe(true);
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole('button', { name: 'Step back' })).toBeVisible();

  await sheet.getByRole('button', { name: 'Add to my calendar' }).click();
  await expect(page.locator('.sl-toast').filter({ hasText: 'Calendar file saved' })).toBeVisible();
});

test('opening from a deep link, closing lands on the day heading, not the page top', async ({
  page,
}) => {
  await page.goto(`/calendar?appointment=${encodeURIComponent(`demo-doctor@${isoDay(1)}`)}`);
  await expect(dialog(page)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog(page)).toHaveCount(0);
  await expect(page.locator('#day-heading')).toBeFocused();
});

test.describe('on a wide screen', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('a half-typed note does not follow you to another appointment', async ({ page }) => {
    await page.goto(`/calendar?appointment=${encodeURIComponent(`demo-doctor@${isoDay(1)}`)}`);
    const panel = page.getByTestId('family-notes');
    await expect(panel).toBeVisible();
    await panel.getByLabel('Add a note').fill('Meant for the doctor only');

    await page
      .getByRole('button', { name: /Physio|Tai Chi|Groceries|Kopi|Eye|Karaoke|Follow/ })
      .first()
      .click();
    await expect(page.getByTestId('family-notes').getByLabel('Add a note')).toHaveValue('');
  });
});
