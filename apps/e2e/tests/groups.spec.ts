import { expect, test, type Page } from '@playwright/test';

import { API_URL, resetDemo } from './support';

// Family groups. The e2e run has sign-in off, so the API seeds a demo family member (`demo-family`)
// who already owns Mdm Lim's group, and a demo senior (`demo-senior`) who is Mdm Lim. A second
// family member is played through the API with the `X-Demo-Sub` header.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

async function enterAs(page: Page, audience: 'family' | 'senior') {
  await page.goto(`/login/${audience}`);
  await page.getByTestId(`continue-${audience}`).click();
}

const digitsOf = async (page: Page, testId: string) =>
  ((await page.getByTestId(testId).textContent()) ?? '').replace(/[^0-9]/g, '');

test('someone who joins with the PIN waits until a member lets them in', async ({
  page,
  request,
}) => {
  await enterAs(page, 'family');
  await page.goto('/family');
  const panel = page.getByTestId('group-panel');
  await expect(panel).toContainText('Caring for Mdm Lim');

  await page.getByTestId('new-join-pin').click();
  const pin = await digitsOf(page, 'join-pin');
  expect(pin).toMatch(/^[0-9]{6}$/);

  // Unique per run: the e2e database can outlive one run.
  const newcomer = `e2e-family-${Date.now()}`;
  const joined = await request.post(`${API_URL}/v1/groups/join`, {
    headers: { 'X-Demo-Sub': newcomer },
    data: { pin, relationship: 'Son' },
  });
  expect(joined.status()).toBe(200);
  expect((await joined.json()).my_status).toBe('pending');

  await page.reload();
  const waiting = page.getByTestId('pending-member');
  await expect(waiting).toHaveCount(1);
  await expect(waiting).toContainText('Son');
  await waiting.getByRole('button', { name: 'Let in' }).click();
  await expect(page.getByTestId('pending-member')).toHaveCount(0);
});

test('the senior shows a code, and a senior already in a group cannot get a second one', async ({
  page,
}) => {
  await enterAs(page, 'senior');
  await page.getByRole('tab', { name: 'Family', exact: true }).click();
  await page.getByTestId('add-family-member').click();
  await page.getByTestId('show-family-code').click();
  // The code on screen is always the live one: the old one left as soon as a new one was asked for.
  const code = await digitsOf(page, 'senior-link-pin');
  expect(code).toMatch(/^[0-9]{6}$/);

  // Back as family: starting a group for Mdm Lim is refused, because her family already has one.
  await page.getByRole('button', { name: 'Sign out' }).click();
  await enterAs(page, 'family');
  await page.goto('/groups/start');
  await expect(page.getByRole('heading', { name: 'Add another family group' })).toBeVisible();
  await page.getByTestId('choose-create').click();
  await page.getByTestId('senior-pin-input').fill(code);
  await page.getByRole('button', { name: 'Start the group' }).click();
  await expect(page.getByRole('alert')).toContainText('already has a family group');
});

test('a senior never sees a code that a newer request has ended', async ({ page }) => {
  await enterAs(page, 'senior');
  await page.getByRole('tab', { name: 'Family', exact: true }).click();
  const pinRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/v1/me/link-pin')) pinRequests.push(request.method());
  });

  // A quick close and reopen while the first code is on its way asks only once.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route('**/v1/me/link-pin', async (route) => {
    await held;
    await route.continue();
  });
  const open = page.getByTestId('add-family-member');
  await open.click();
  await open.click();
  await open.click();
  await expect(page.getByRole('status').filter({ hasText: 'Getting your code' })).toBeVisible();
  release();
  await expect(page.getByTestId('senior-link-pin')).toBeVisible();
  expect(pinRequests.filter((method) => method === 'POST')).toHaveLength(1);
  await page.unroute('**/v1/me/link-pin');

  // Asking for a new code takes the old one off the screen before the answer comes back.
  const first = await digitsOf(page, 'senior-link-pin');
  let finish: () => void = () => {};
  const waiting = new Promise<void>((resolve) => (finish = resolve));
  await page.route('**/v1/me/link-pin', async (route) => {
    await waiting;
    await route.continue();
  });
  await page.getByTestId('show-family-code').click();
  await expect(page.getByTestId('senior-link-pin')).toHaveCount(0);
  finish();
  await expect(page.getByTestId('senior-link-pin')).toBeVisible();
  expect(await digitsOf(page, 'senior-link-pin')).not.toBe(first);
  await page.unroute('**/v1/me/link-pin');

  // If the answer never arrives, the screen says so and offers to try again, with no old code left.
  await page.route('**/v1/me/link-pin', (route) => route.abort());
  await page.getByTestId('show-family-code').click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('senior-link-pin')).toHaveCount(0);
  await expect(page.getByTestId('show-family-code')).toHaveText('Try getting a code again');
});

// The smallest the digits may be at each size: the same as at 100% wherever the panel has room.
const NARROW_PHONE_DIGITS = 29; // 320 px at 150%: short of room, still above its 25.5 px body text.
const PHONE_DIGITS = 35.2;
const DESKTOP_DIGITS = 48;

for (const [width, zoom, smallestDigits] of [
  [320, 125, PHONE_DIGITS],
  [320, 150, NARROW_PHONE_DIGITS],
  [375, 100, PHONE_DIGITS],
  [375, 125, PHONE_DIGITS],
  [375, 150, PHONE_DIGITS],
  [1440, 100, DESKTOP_DIGITS],
  [1440, 150, DESKTOP_DIGITS],
]) {
  test(`at ${width}px and ${zoom}% a new code keeps the page still and the focus on the button`, async ({
    page,
  }) => {
    await page.addInitScript(
      (percent) => window.localStorage.setItem('careplus.zoom.v1', String(percent)),
      zoom,
    );
    await page.setViewportSize({ width, height: 900 });
    await enterAs(page, 'senior');
    await page.getByRole('tab', { name: 'Family', exact: true }).click();
    await page.getByTestId('add-family-member').click();
    await expect(page.getByTestId('senior-link-pin')).toBeVisible();

    const button = page.getByTestId('show-family-code');
    const top = () =>
      button.evaluate((element) => element.getBoundingClientRect().top + window.scrollY);
    const before = await top();

    let finish: () => void = () => {};
    const waiting = new Promise<void>((resolve) => (finish = resolve));
    await page.route('**/v1/me/link-pin', async (route) => {
      await waiting;
      await route.continue();
    });
    await button.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('status').filter({ hasText: 'Getting your code' })).toBeAttached();
    await expect(button).toHaveAttribute('aria-disabled', 'true');
    await expect(button).toBeFocused();
    expect(await top()).toBe(before);

    finish();
    await expect(page.getByTestId('senior-link-pin')).toBeVisible();
    await expect(button).toBeFocused();
    expect(await top()).toBe(before);
    await expect(page.getByRole('status').filter({ hasText: 'Your code is ready' })).toBeAttached();

    // The six digits stay on one line, whole, inside their panel.
    const digits = await page.getByTestId('senior-link-pin').evaluate((element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const text = range.getBoundingClientRect();
      const panel = (element.parentElement as HTMLElement).getBoundingClientRect();
      return {
        height: text.height,
        fontSize: parseFloat(getComputedStyle(element).fontSize),
        bodySize: parseFloat(getComputedStyle(document.body).fontSize),
        fits: text.left >= panel.left && text.right <= panel.right,
      };
    });
    expect(digits.height).toBeLessThan(digits.fontSize * 2);
    expect(digits.fits).toBe(true);
    expect(digits.fontSize).toBeGreaterThanOrEqual(smallestDigits);
    expect(digits.fontSize).toBeGreaterThan(digits.bodySize);
    await page.unroute('**/v1/me/link-pin');
  });
}

test('the family join PIN keeps its full size on a desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await enterAs(page, 'family');
  await page.goto('/family');
  await page.getByTestId('new-join-pin').click();
  const pin = page.getByTestId('join-pin');
  await expect(pin).toBeVisible();
  await expect(pin).toHaveCSS('font-size', '48px');
  await pin.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const text = range.getBoundingClientRect();
    const panel = (element.parentElement as HTMLElement).getBoundingClientRect();
    if (text.right > panel.right) throw new Error('the PIN runs out of its panel');
  });
});

test('a wrong join PIN is turned down in plain words', async ({ page }) => {
  await enterAs(page, 'family');
  await page.goto('/groups/start');
  await page.getByTestId('choose-join').click();
  await page.getByTestId('join-pin-input').fill('000000');
  await page.getByRole('button', { name: 'Ask to join' }).click();
  await expect(page.getByRole('alert')).toContainText(/not right|expired|Too many/);
});

test('starting out offers two separate choices, and Back returns to them', async ({ page }) => {
  await enterAs(page, 'family');
  await page.goto('/groups/start');
  await expect(page.getByTestId('choose-join')).toContainText('Join a group');
  await expect(page.getByTestId('choose-create')).toContainText('Create a group');
  await expect(page.getByTestId('join-pin-input')).toHaveCount(0);

  await page.getByTestId('choose-create').click();
  await expect(page.getByTestId('senior-pin-input')).toBeVisible();
  await expect(page.getByText('It works once, for 10 minutes.')).toBeVisible();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByTestId('choose-join')).toBeVisible();
});

test('a new visitor finds the sign-up page from sign-in, and can pick senior or family', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByTestId('signup-link').click();
  await expect(page).toHaveURL(/\/signup$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Create your account' })).toBeVisible();
  await expect(page.getByText('I am the senior')).toBeVisible();
  await expect(page.getByText('I am family or a caregiver')).toBeVisible();
  for (const field of ['Your name', 'Email', 'Password', 'Type the password again']) {
    await expect(page.getByLabel(field, { exact: true })).toBeVisible();
  }
  // Sign-in is off in the e2e run, so the page says the form cannot be sent.
  await expect(page.getByRole('note')).toContainText('switched off');
  await page.getByTestId('signin-link').click();
  await expect(page).toHaveURL(/\/login$/);
});

test('the family group page is one click from Family, and /groups goes there too', async ({
  page,
}) => {
  await enterAs(page, 'family');
  await page.goto('/family');
  await page.getByTestId('to-groups').click();
  await expect(page).toHaveURL(/\/groups\/start$/);
  await page.goto('/groups');
  await expect(page).toHaveURL(/\/groups\/start$/);
  await expect(page.getByTestId('choose-join')).toBeVisible();
});
