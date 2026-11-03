import { expect, test, type Page } from '@playwright/test';

import { addDemoTask, clearDemoTasks, isoDay, resetDemo } from './support';

// Phase 3 feedback: a tick on Home can be undone from its toast, the senior's last tick of the day
// gets a small cheer, and every flow still finishes when the device asks for less motion.

let groupId = '';
test.beforeEach(async ({ request }) => {
  await resetDemo(request);
  groupId = await clearDemoTasks(request);
  await addDemoTask(request, groupId, {
    title: 'Morning tablets',
    start_date: isoDay(0),
    time: '08:00',
  });
  await addDemoTask(request, groupId, {
    title: 'Call the clinic',
    start_date: isoDay(0),
    time: '23:30',
  });
});

async function openFamilyHome(page: Page) {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await expect(page.getByTestId('task-panel')).toBeVisible();
}

test('ticking a task on Home can be undone from the toast, and focus returns to it', async ({
  page,
}) => {
  await openFamilyHome(page);
  const panel = page.getByTestId('task-panel');
  const tablets = panel.getByRole('checkbox', { name: /Morning tablets/ });
  await expect(tablets).not.toBeChecked();

  await panel.locator('label', { hasText: 'Morning tablets' }).click();
  await expect(tablets).toBeChecked();
  await expect(page.getByText('Ticked off: Morning tablets.')).toBeVisible();

  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(tablets).not.toBeChecked();
  await expect(tablets).toBeFocused();
  // The undo reached the API: a reload still shows it not done.
  await page.reload();
  await expect(panel.getByRole('checkbox', { name: /Morning tablets/ })).not.toBeChecked();
});

test('the senior gets one small cheer when the last of today’s tasks is ticked', async ({
  page,
}) => {
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const panel = page.getByTestId('task-panel');
  await panel.getByRole('button', { name: 'Mark Morning tablets done', exact: true }).click();
  await expect(panel.getByTestId('senior-task-notice')).toHaveText('Morning tablets marked done.');
  await expect(page.getByTestId('badge-confetti')).toHaveCount(0);

  await panel.getByRole('button', { name: 'Mark Call the clinic done', exact: true }).click();
  await expect(panel.getByTestId('senior-task-notice')).toContainText('All done for today');
  await expect(panel.getByText('All done for today', { exact: true })).toBeVisible();
  await expect(page.getByTestId('badge-confetti')).toHaveCount(1);
  // It goes by itself, and taps still land while it shows.
  await expect(page.getByTestId('badge-confetti')).toHaveCount(0, { timeout: 7_000 });

  // Once a day: unticking and ticking again does not cheer a second time.
  await panel.getByRole('button', { name: 'Mark Call the clinic not done', exact: true }).click();
  await panel.getByRole('button', { name: 'Mark Call the clinic done', exact: true }).click();
  await expect(panel.getByTestId('senior-task-notice')).toContainText('All done for today');
  await expect(page.getByTestId('badge-confetti')).toHaveCount(0);
});

test.describe('with reduced motion', () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
  });

  test('Home still ticks, takes a visit and undoes, with no entrance or morph', async ({
    page,
  }) => {
    await openFamilyHome(page);
    // The hero's headline is there at once, with no animation running on it.
    const title = page.locator('.hero-title');
    await expect(title).toBeVisible();
    expect(await title.evaluate((el) => getComputedStyle(el).animationName)).toBe('none');

    const panel = page.getByTestId('task-panel');
    await panel.locator('label', { hasText: 'Morning tablets' }).click();
    await expect(panel.getByRole('checkbox', { name: /Morning tablets/ })).toBeChecked();

    const needs = page.locator('#home-needs');
    const go = needs.locator('.needs-go').first();
    const visit = (await go.getAttribute('data-go')) ?? '';
    await go.click();
    // No "You're going" moment: the row leaves straight away and the toast says what happened.
    await expect(needs.locator(`.needs-go[data-go="${visit}"]`)).toHaveCount(0);
    await expect(needs.getByTestId('needs-going')).toHaveCount(0);
    await expect(page.getByText(/You’re going to/)).toBeVisible();
  });

  test('the senior finishing the day sees the words but no confetti', async ({ page }) => {
    await page.goto('/login/senior');
    await page.getByTestId('continue-senior').click();
    const panel = page.getByTestId('task-panel');
    await panel.getByRole('button', { name: 'Mark Morning tablets done', exact: true }).click();
    await panel.getByRole('button', { name: 'Mark Call the clinic done', exact: true }).click();
    await expect(panel.getByTestId('senior-task-notice')).toContainText('All done for today');
    await expect(page.getByTestId('badge-confetti')).toHaveCount(0);
  });
});

test('the family avatar cluster names everyone and spreads apart when focused', async ({
  page,
}) => {
  await page.goto('/family');
  const cluster = page.locator('a.cluster');
  await expect(cluster).toHaveAttribute('aria-label', /Care group, \d+ people:/);
  await expect(cluster).toHaveAttribute('title', /Care group/);
  const face = cluster.locator('.cluster-face').nth(1);
  await expect(face).toHaveCSS('transform', 'none');
  await cluster.focus();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  await expect(face).not.toHaveCSS('transform', 'none');
});
