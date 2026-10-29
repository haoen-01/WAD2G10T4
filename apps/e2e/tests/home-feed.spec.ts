import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

import { API_URL, resetDemo } from './support';

// The family activity feed and check-ins on Home. Every test resets the demo, which seeds six sample
// feed entries (Sarah, John and Emily in Mdm Lim's group).

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

const feed = (page: Page) => page.locator('#home-feed');

/** Mdm Lim's group id, read the way the app does (as Sarah). */
async function groupId(request: APIRequestContext): Promise<string> {
  const response = await request.get(`${API_URL}/v1/me`, {
    headers: { 'X-Demo-Sub': 'demo-family' },
  });
  expect(response.ok()).toBe(true);
  const me = (await response.json()) as { groups: { group_id: string; my_status: string }[] };
  return me.groups.find((group) => group.my_status === 'active')!.group_id;
}

async function checkInAs(request: APIRequestContext, sub: string, note: string) {
  const response = await request.post(`${API_URL}/v1/groups/${await groupId(request)}/check-ins`, {
    headers: { 'X-Demo-Sub': sub },
    data: { kind: 'visited', note },
  });
  expect(response.status()).toBe(201);
}

test('Home shows the seeded family updates, each tagged as a sample', async ({ page }) => {
  await page.goto('/');
  await expect(feed(page).getByRole('heading', { name: 'Family updates' })).toBeVisible();
  await expect(feed(page).locator('li')).toHaveCount(6);
  await expect(feed(page).getByText('Sample', { exact: true })).toHaveCount(6);
  await expect(feed(page)).toContainText('You called Mdm Lim');
  await expect(feed(page)).toContainText('She sounded cheerful');
});

test('a check-in shows at once, survives a reload, and is Sarah’s (not “You”) to John', async ({
  page,
}) => {
  await page.goto('/');
  await expect(feed(page).locator('li')).toHaveCount(6);

  await page.getByLabel('Add a note (optional)').fill('Brought her kaya toast');
  await page
    .getByRole('group', { name: 'How you were in touch' })
    .getByRole('button', { name: 'Called', exact: true })
    .click();

  const mine = feed(page).locator('li', { hasText: 'Brought her kaya toast' });
  await expect(mine).toContainText('You called Mdm Lim');
  await expect(mine.getByText('Sample')).toHaveCount(0);
  await expect(page.getByLabel('Add a note (optional)')).toHaveValue('');

  await page.reload();
  await expect(feed(page).locator('li', { hasText: 'Brought her kaya toast' })).toContainText(
    'You called Mdm Lim',
  );

  // The other members see it under Sarah's name.
  await page.goto('/calendar');
  await page.getByLabel('Viewing as').selectOption({ label: 'John' });
  await page.getByRole('link', { name: 'Home', exact: true }).first().click();
  const johns = feed(page).locator('li', { hasText: 'Brought her kaya toast' });
  await expect(johns).toContainText('Sarah called Mdm Lim');
  await expect(johns).not.toContainText('You called');
});

test('a refused check-in is taken back out of the feed with a message', async ({ page }) => {
  await page.route('**/check-ins', (route) => route.fulfill({ status: 500, body: 'nope' }));
  await page.goto('/');
  await expect(feed(page).locator('li')).toHaveCount(6);
  await page.getByLabel('Add a note (optional)').fill('This will fail');
  await page.getByRole('button', { name: 'Messaged', exact: true }).click();
  await expect(page.getByText('Could not share that.')).toBeVisible();
  await expect(feed(page).locator('li')).toHaveCount(6);
  await expect(page.getByLabel('Add a note (optional)')).toHaveValue('This will fail');
});

test('the feed refreshes every 30 seconds and when the window gains focus', async ({
  page,
  request,
}) => {
  await page.clock.install();
  await page.goto('/');
  await expect(feed(page).locator('li')).toHaveCount(6);

  await checkInAs(request, 'demo-john', 'Dropped off soup');
  await page.clock.runFor(31_000);
  await expect(feed(page).locator('li', { hasText: 'Dropped off soup' })).toContainText(
    'John visited Mdm Lim',
  );

  await checkInAs(request, 'demo-emily', 'Quick hello at lunch');
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(feed(page).locator('li', { hasText: 'Quick hello at lunch' })).toContainText(
    'Emily visited Mdm Lim',
  );
});

test('the senior screen never asks for the family feed', async ({ page }) => {
  const asked: string[] = [];
  page.on('request', (request) => {
    if (/\/v1\/groups\/[^/]+\/activity/.test(request.url())) asked.push(request.url());
  });
  await page.goto('/login');
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  await expect(page).toHaveURL(/\/senior$/);
  await expect(page.getByRole('heading', { name: 'My steps' })).toBeVisible();
  await expect(page.getByTestId('steps-today')).not.toBeEmpty();
  await page.waitForLoadState('networkidle');
  expect(asked).toEqual([]);
});

test('with reduced motion the percentage shows its final value at once', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const ticker = page.locator('.number-ticker').first();
  const digits = ticker.getByTestId('ticker-digits');
  await expect(digits).toBeVisible();
  const final = (await ticker.locator('.visually-hidden').textContent())!.trim();
  expect(final).toMatch(/^\d+$/);
  // Read straight away: no counting up through smaller numbers.
  expect((await digits.textContent())!.trim()).toBe(final);
});
