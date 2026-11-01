import { expect, test, type Page } from '@playwright/test';

import { openSettings, resetDemo } from './support';

// End-to-end user journeys through Care+, each chosen to show one testing idea:
//
//   1. Happy path         the senior gets through their day (setup -> action -> assert)
//   2. Failure path       a wrong join PIN is turned down in plain words
//   3. Boundary values    the join PIN needs exactly 6 digits
//   4. Across roles       family adds an appointment and the senior sees it (UI + API + database)
//   5. Validation         Kaki never lets an AI answer an emergency or a medicine question
//   6. Regression         problems fixed on 1 Nov 2026 stay fixed
//   7. Mocking            the watch battery bands, with the API answer faked by page.route()
//   8. Responsive         the family menu moves to a bottom tab bar on a phone
//
// The e2e run has sign-in off: "Continue" on a sign-in page enters as the demo family member
// (who looks after Mdm Lim) or as Mdm Lim herself. resetDemo() puts the demo data back before each
// test, so no test depends on what another one did (test isolation).

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

async function signIn(page: Page, who: 'senior' | 'family') {
  await page.goto(`/login/${who}`);
  await page.getByTestId(`continue-${who}`).click();
}

async function signOut(page: Page, who: 'senior' | 'family') {
  // Family keep Sign out in the Settings menu; the senior has it in the top bar.
  if (who === 'family') await openSettings(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
}

/** "YYYY-MM-DD" in the browser's local time, the format the calendar uses. */
function iso(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

// ── 1. Happy path ────────────────────────────────────────────────────────────

test.describe('happy path: the senior’s day', () => {
  // Tasks are kept in the browser. Start from an empty list so the test only sees its own task.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      const key = 'careplus.tasks.v1.mdm-lim';
      if (localStorage.getItem(key) === null) {
        localStorage.setItem(key, JSON.stringify({ schedules: [], completions: {} }));
      }
    });
  });

  test('the senior sees today’s steps, adds a task and ticks it off', async ({ page }) => {
    // Setup
    await signIn(page, 'senior');
    await expect(page.getByRole('heading', { name: 'My steps' })).toBeVisible();
    await expect(page.getByTestId('steps-today')).not.toBeEmpty();

    // Action: add a task, then mark it done
    const tasks = page.getByTestId('task-panel');
    await tasks.getByRole('button', { name: 'Add task' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Name', { exact: true }).fill('Take a short walk');
    await dialog.getByRole('button', { name: 'Add task', exact: true }).click();
    await expect(dialog).toBeHidden();
    await tasks.getByRole('button', { name: 'Mark Take a short walk done', exact: true }).click();

    // Assert: it is done, and still done after a reload
    const done = tasks.getByRole('button', { name: 'Mark Take a short walk not done' });
    await expect(done).toHaveAttribute('aria-pressed', 'true');
    await page.reload();
    await expect(done).toHaveAttribute('aria-pressed', 'true');
  });
});

// ── 2 and 3. Failure path and boundary values ───────────────────────────────

test.describe('joining a family group with a PIN', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, 'family');
    await page.goto('/groups/start');
    await page.getByTestId('choose-join').click();
  });

  test('a wrong PIN is turned down with a plain-words message', async ({ page }) => {
    await page.getByTestId('join-pin-input').fill('000000');
    await page.getByRole('button', { name: 'Ask to join' }).click();
    await expect(page.getByRole('alert')).toContainText(
      'That PIN is not right, or it has expired.',
    );
  });

  test('Ask to join stays disabled until exactly 6 digits are entered', async ({ page }) => {
    const pin = page.getByTestId('join-pin-input');
    const askToJoin = page.getByRole('button', { name: 'Ask to join' });

    await expect(askToJoin).toBeDisabled(); // 0 digits
    await pin.fill('12345');
    await expect(askToJoin).toBeDisabled(); // 5 digits: one short of the boundary
    await pin.fill('123456');
    await expect(askToJoin).toBeEnabled(); // 6 digits: on the boundary
  });
});

// ── 4. Across roles ──────────────────────────────────────────────────────────

test('an appointment the family adds shows on the senior’s own calendar', async ({ page }) => {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);

  // The family member adds it on the shared calendar (saved by the API in the database).
  await signIn(page, 'family');
  await page.goto('/calendar');
  await page.getByTestId('add-appointment').click();
  await page.getByTestId('add-title').fill('Grandson’s school concert');
  await page.getByLabel('Date', { exact: true }).fill(iso(tomorrow));
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Added' })).toBeVisible();

  // The senior signs in on "their phone" and finds it on their calendar.
  await signOut(page, 'family');
  await signIn(page, 'senior');
  await page.getByRole('tab', { name: 'Calendar', exact: true }).click();
  const myCalendar = page.getByRole('region', { name: 'My calendar' });
  await expect(myCalendar.getByText('Grandson’s school concert')).toBeVisible();
});

// ── 5. Validation: the product's safety rules ───────────────────────────────

test.describe('Kaki, the assistant, keeps to the safety rules', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, 'senior');
    await page.getByTestId('assistant-orb').click();
  });

  async function ask(page: Page, question: string) {
    await page.getByTestId('assistant-input').fill(question);
    await page.getByTestId('assistant-input').press('Enter');
    return page.getByTestId('assistant-assistant').last();
  }

  test('an emergency gets the fixed “call 995” answer', async ({ page }) => {
    await expect(await ask(page, 'I fell down and cannot get up')).toContainText('call 995');
  });

  test('a medicine question is sent to a doctor or pharmacist', async ({ page }) => {
    await expect(await ask(page, 'Can I take two of my pills?')).toContainText(
      'doctor, nurse or pharmacist',
    );
  });

  test('an everyday question gets a normal answer, not the safety one', async ({ page }) => {
    const reply = await ask(page, 'How many steps today?');
    await expect(reply).toContainText(/your watch counted [\d,]+ steps/);
    await expect(reply).not.toContainText('995');
  });
});

// ── 6. Regression: problems fixed on 1 Nov 2026 ─────────────────────────────

test.describe('regression', () => {
  test('Kaki tells a family member to invite others with the group’s join PIN', async ({
    page,
  }) => {
    // PR #29: Kaki used to send everyone to the senior's one-time code, which cannot add anyone
    // to a group that already exists.
    await signIn(page, 'family');
    await page.getByTestId('assistant-orb').click();
    await page.getByTestId('assistant-input').fill('How do I invite my brother?');
    await page.getByTestId('assistant-input').press('Enter');
    const reply = page.getByTestId('assistant-assistant').last();
    await expect(reply).toContainText('Show a join PIN');
    await expect(reply).toContainText('Join a group');
  });

  test('an appointment early in the month can still be dragged to the next day', async ({
    page,
  }) => {
    // PR #28: the old drag test passed all October, then failed on 1 Nov. Adding an appointment
    // scrolls the page down, and on the 1st the appointment sits in the calendar's top row, so it
    // went off screen and the drag missed it. The app was fine; the test depended on the date.
    // Freezing the browser's clock on the 1st of next month makes this test always cover that
    // case, whatever today's date is.
    const now = new Date();
    const first = new Date(now.getFullYear(), now.getMonth() + 1, 1, 10, 0);
    const second = new Date(first.getFullYear(), first.getMonth(), 2);
    await page.clock.setFixedTime(first);
    await page.setViewportSize({ width: 1280, height: 900 });

    await signIn(page, 'family');
    await page.goto('/calendar');
    await page.getByTestId('add-appointment').click();
    await page.getByTestId('add-title').fill('Haircut');
    await page.getByLabel('Date', { exact: true }).fill(iso(first));
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Added Haircut' })).toBeVisible();

    // Like a person would: bring the day back on screen, then drag the appointment.
    const firstDay = page.locator(`[data-iso="${iso(first)}"]`);
    const secondDay = page.locator(`[data-iso="${iso(second)}"]`);
    const haircut = firstDay.locator('[data-appt]').filter({ hasText: 'Haircut' });
    await haircut.scrollIntoViewIfNeeded();
    await expect(haircut).toBeInViewport();
    await haircut.dragTo(secondDay);

    await expect(page.getByRole('status').filter({ hasText: 'Moved to' })).toBeVisible();
    await expect(secondDay.locator('[data-appt]').filter({ hasText: 'Haircut' })).toBeVisible();
  });
});

// ── 7. Mocking: faking the API's answer ─────────────────────────────────────

// Boundary values around the two cut-offs (20% and 50%), like grade boundaries 79/80. The watch is
// simulated, so its real battery level changes with the time of day; faking the answer with
// page.route() makes each case certain.
const batteryCases = [
  { percent: 19, words: '19%, needs charging', band: 'critical' },
  { percent: 20, words: '20%, getting low', band: 'low' },
  { percent: 49, words: '49%, getting low', band: 'low' },
  { percent: 50, words: '50%', band: 'good' },
];

for (const { percent, words, band } of batteryCases) {
  test(`Home shows a ${percent}% watch battery as “${words}”`, async ({ page }) => {
    await page.route('**/v1/people/*/wearable', (route) =>
      route.fulfill({
        json: {
          connected: true,
          last_synced_at: new Date().toISOString(),
          battery_percent: percent,
          charging: false,
          source: 'synthetic',
        },
      }),
    );
    await signIn(page, 'family');
    const battery = page.getByTestId('watch-battery');
    // The element starts with "Watch battery" for screen readers (visually hidden).
    await expect(battery).toHaveText(`Watch battery ${words}`);
    await expect(battery).toHaveClass(new RegExp(`battery-${band}`));
  });
}

// ── 8. Responsive: the same menu on a phone and on a desktop ────────────────

test('the family menu is a bottom tab bar on a phone and sits at the top on a desktop', async ({
  page,
}) => {
  const menu = page.getByRole('navigation', { name: 'Main' });

  await page.setViewportSize({ width: 375, height: 812 }); // phone
  await signIn(page, 'family');
  const onPhone = await menu.boundingBox();
  expect(onPhone).not.toBeNull();
  expect(onPhone!.y + onPhone!.height).toBeGreaterThan(812 - 5); // touches the bottom edge

  // The tab bar still works: it takes the family member to the calendar.
  await menu.getByRole('link', { name: /Calendar/ }).click();
  await expect(page).toHaveURL(/\/calendar$/);

  await page.setViewportSize({ width: 1280, height: 900 }); // desktop
  const onDesktop = await menu.boundingBox();
  expect(onDesktop).not.toBeNull();
  expect(onDesktop!.y).toBeLessThan(120); // in the header at the top
});
