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
