import { expect, test, type Page } from '@playwright/test';

import { resetDemo } from './support';

// When Care+ cannot be reached, the screen says so and offers Try again. Nobody is sent to sign in
// or to "join a family group" because a request failed, and the address stays the same.
//
// The e2e run has sign-in off, so the request the guard makes is `GET /v1/me` (the family view
// reads it to know whether this member is in a family group yet). The same decision covers
// `GET /v1/auth/me` with sign-in on; `client/src/lib/route-guard.test.ts` pins that side.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

/**
 * Records the requests a family screen makes for its data, and whether the given screen's root ever
 * appears in the page, from now on. Used to prove the screen hidden behind the panel never mounts.
 */
async function watchHiddenScreen(page: Page, selector: string) {
  const viewReads: string[] = [];
  page.on('request', (request) => {
    if (/\/v1\/(people|groups)\//.test(request.url())) viewReads.push(request.url());
  });
  await page.evaluate((sel) => {
    const flag = window as unknown as { __hiddenSeen: boolean };
    flag.__hiddenSeen = false;
    new MutationObserver(() => {
      if (document.querySelector(sel)) flag.__hiddenSeen = true;
    }).observe(document.body, { childList: true, subtree: true });
  }, selector);
  return {
    viewReads,
    seen: () => page.evaluate(() => (window as unknown as { __hiddenSeen: boolean }).__hiddenSeen),
  };
}

/** Enters the demo as the family before the page loads (sign-in is off in the e2e run). */
async function asFamily(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem('careplus.demoView.v1', 'family'));
}

test('an unreachable /v1/me shows the connection panel, keeps the URL, and Try again recovers', async ({
  page,
}) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) => route.abort());
  await page.goto('/');

  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();
  // One announcement path: focus moves to the heading (no nested alert live region).
  await expect(
    page.getByRole('region', { name: 'Can’t connect to Care+ right now' }),
  ).toHaveAttribute('data-testid', 'connection-problem');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(
    panel.getByRole('heading', { name: 'Can’t connect to Care+ right now' }),
  ).toBeFocused();
  await expect(panel).toContainText('Care+ could not reach its service.');
  await expect(page).toHaveURL('/');
  // Not sent to "join a family group", and the menu links are hidden meanwhile.
  await expect(page.getByRole('heading', { name: /family group/i })).toHaveCount(0);
  await expect(page.getByRole('navigation', { name: 'Main' })).toHaveCount(0);

  await page.unroute('**/v1/me');
  await panel.getByRole('button', { name: 'Try again' }).click();
  await expect(panel).toHaveCount(0);
  await expect(page).toHaveURL('/');
  await expect(page.locator('.home')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible();
});

test('a server error on /v1/me shows the panel on a deep link, not the group start page', async ({
  page,
}) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) =>
    route.fulfill({
      status: 503,
      body: 'down',
      headers: { 'Access-Control-Allow-Origin': '*' },
    }),
  );
  await page.goto('/calendar');
  await expect(page.getByTestId('connection-problem')).toBeVisible();
  await expect(page).toHaveURL('/calendar');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByTestId('connection-problem')).toContainText(
    'Care+ could not complete this request.',
  );
});

test('a retry that fails again keeps the panel, mounts no screen, and leaves focus alone', async ({
  page,
}) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) => route.abort());
  await page.goto('/');

  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();
  const retry = panel.getByRole('button', { name: 'Try again' });
  await retry.focus();

  // Count what Home would read if it mounted behind the panel.
  const viewReads: string[] = [];
  page.on('request', (request) => {
    if (/\/v1\/(people|groups)\//.test(request.url())) viewReads.push(request.url());
  });
  await retry.click();
  await expect(retry).toHaveText(/Try again/);
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('status')).toHaveText(/Still can’t connect/);
  await expect(page.locator('.home')).toHaveCount(0);
  expect(viewReads).toEqual([]);
  // The panel was not mounted again, so focus stays on Try again rather than jumping to the
  // heading.
  await expect(retry).toBeFocused();
  await expect(page).toHaveURL('/');
});

test('a reload that cannot reach Care+ keeps the family view and offers Sign out, not Sign in', async ({
  page,
}) => {
  await asFamily(page);
  await page.goto('/family');
  await expect(page.locator('h1').first()).toBeVisible();

  await page.route('**/v1/me', (route) => route.abort());
  await page.reload();
  await expect(page.getByTestId('connection-problem')).toBeVisible();
  await expect(page).toHaveURL('/family');
  await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign in' })).toHaveCount(0);

  // No horizontal scroll on a phone.
  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const box = await page.getByTestId('connection-retry').boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});

test('a retry that gets through but is sent elsewhere never mounts the screen behind the panel', async ({
  page,
}) => {
  await asFamily(page);
  // First unreachable; then Care+ answers, but this member is in no family group yet.
  let reachable = false;
  await page.route('**/v1/me', async (route) => {
    if (!reachable) return route.abort();
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    return route.fulfill({ response, json: { ...body, groups: [] } });
  });
  await page.goto('/calendar');
  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();

  const hidden = await watchHiddenScreen(page, '.calendar-page');
  reachable = true;
  await panel.getByRole('button', { name: 'Try again' }).click();
  await expect(page).toHaveURL('/groups/start');
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
  expect(await hidden.seen()).toBe(false);
  expect(hidden.viewReads).toEqual([]);
});

test('signing out from the panel never mounts the screen behind it', async ({ page }) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) => route.abort());
  await page.goto('/family');
  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();

  const hidden = await watchHiddenScreen(page, '.family-page');
  await page.getByRole('button', { name: /sign out/i }).click();
  await expect(page).toHaveURL(/\/login/);
  await expect(panel).toHaveCount(0);
  expect(await hidden.seen()).toBe(false);
  expect(hidden.viewReads).toEqual([]);
});

test('going back from the panel to another screen never mounts the hidden one', async ({
  page,
}) => {
  await asFamily(page);
  await page.route('**/v1/me', (route) => route.abort());
  await page.goto('/family');
  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();
  // Within the app (no page load): the brand link to Home, still unreachable, so still the panel.
  await page.locator('.brand').click();
  await expect(page).toHaveURL('/');
  await expect(panel).toBeVisible();

  // Care+ answers again; Back goes to the Family page, and Home (hidden behind the panel at `/`)
  // never mounts on the way.
  const hidden = await watchHiddenScreen(page, '.home');
  await page.unroute('**/v1/me');
  await page.goBack();
  await expect(page).toHaveURL('/family');
  await expect(panel).toHaveCount(0);
  await expect(page.locator('.family-page')).toBeVisible();
  expect(await hidden.seen()).toBe(false);
  expect(hidden.viewReads.filter((url) => /\/(wearable|metrics|activity)\b/.test(url))).toEqual([]);
});

/**
 * `GET /v1/me` that fails (`abort`), goes through (`pass`), or waits until released (`hang`). A
 * held request, once released, follows the mode set by then: it fails, or goes through after
 * `mode = 'pass'`. Returns the switch and a way to release the request being held.
 */
async function controlMe(page: Page) {
  const state: { mode: 'abort' | 'hang' | 'pass'; release: (() => void) | null } = {
    mode: 'abort',
    release: null,
  };
  const modeNow = () => state.mode;
  await page.route('**/v1/me', async (route) => {
    if (state.mode === 'pass') return route.fallback();
    if (state.mode === 'hang') {
      await new Promise<void>((resolve) => (state.release = resolve));
      // Read again: the test may have switched it while the request was held.
      if (modeNow() === 'pass') return route.fallback();
    }
    return route.abort();
  });
  return state;
}

/** Lets the app finish handling what just arrived: a frame, then the tasks queued during it. */
async function settle(page: Page) {
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0))),
  );
}

test('a Try again still waiting when someone signs out never pulls them back', async ({ page }) => {
  await asFamily(page);
  const me = await controlMe(page);
  await page.goto('/family');
  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();

  me.mode = 'hang';
  await panel.getByRole('button', { name: 'Try again' }).click();
  await expect.poll(() => me.release !== null).toBe(true);
  await page.getByRole('button', { name: /sign out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(panel).toHaveCount(0);

  // The retry's read now comes back (and Care+ answers again): it must not reopen /family.
  me.mode = 'pass';
  const answered = page.waitForEvent('requestfinished', (request) =>
    request.url().endsWith('/v1/me'),
  );
  me.release?.();
  await answered;
  await settle(page);
  await expect(page).toHaveURL(/\/login$/);
  await expect(panel).toHaveCount(0);
});

test('a guard overtaken by a newer navigation never shows the panel over it', async ({ page }) => {
  await asFamily(page);
  const me = await controlMe(page);
  await page.goto('/family');
  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();

  // Home is asked for, but its guard waits on /v1/me; meanwhile the person signs out.
  me.mode = 'hang';
  await page.locator('.brand').click();
  await expect.poll(() => me.release !== null).toBe(true);
  await page.getByRole('button', { name: /sign out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(panel).toHaveCount(0);

  // The abandoned guard's read now fails: it must not cover the sign-in page with the panel.
  const failed = page.waitForEvent('requestfailed', (request) => request.url().endsWith('/v1/me'));
  me.release?.();
  await failed;
  await settle(page);
  await expect(page).toHaveURL(/\/login$/);
  await expect(panel).toHaveCount(0);
});

/**
 * `GET /v1/me` answered in turn from a list: each request takes the next step, and a `hang` step
 * waits for `release()` and then fails. Requests past the end of the list go through.
 */
async function meInTurn(page: Page, steps: ('abort' | 'hang')[]) {
  const held: { release: (() => void) | null } = { release: null };
  await page.route('**/v1/me', async (route) => {
    const step = steps.shift();
    if (!step) return route.fallback();
    if (step === 'hang') await new Promise<void>((resolve) => (held.release = resolve));
    return route.abort();
  });
  return held;
}

test('pressing the current screen cancels a waiting retry, which then never reports', async ({
  page,
}) => {
  await asFamily(page);
  // The first read fails (the panel); Try again's own read fails too; its guard's read waits.
  const me = await meInTurn(page, ['abort', 'abort', 'hang']);
  await page.goto('/');
  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();

  await panel.getByRole('button', { name: 'Try again' }).click();
  await expect.poll(() => me.release !== null).toBe(true);
  // Home, the screen already showing: the router cancels the retry's navigation without a guard.
  await page.locator('.brand').click();

  const failed = page.waitForEvent('requestfailed', (request) => request.url().endsWith('/v1/me'));
  me.release?.();
  await failed;
  await settle(page);
  // The cancelled guard did not report: no "Still can't connect", and Try again works.
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('status')).not.toHaveText(/Still can’t connect/);
  await panel.getByRole('button', { name: 'Try again' }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.locator('.home')).toBeVisible();
});

test('pressing the current screen while Try again reads leaves the retry to finish', async ({
  page,
}) => {
  await asFamily(page);
  const state = await controlMe(page);
  await page.goto('/');
  const panel = page.getByTestId('connection-problem');
  await expect(panel).toBeVisible();

  // Try again's own read waits; nothing is navigating, so pressing Home cancels nothing.
  state.mode = 'hang';
  await panel.getByRole('button', { name: 'Try again' }).click();
  await expect.poll(() => state.release !== null).toBe(true);
  await page.locator('.brand').click();

  // Care+ answers: the retry carries on and opens Home.
  state.mode = 'pass';
  state.release?.();
  await expect(panel).toHaveCount(0);
  await expect(page.locator('.home')).toBeVisible();
});
