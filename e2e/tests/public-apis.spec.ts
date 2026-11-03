import { expect, test } from '@playwright/test';

import { resetDemo, showMoreOnHome } from './support';

// The two public APIs the browser calls with Axios: NEA's 2-hour forecast (data.gov.sg) on Home
// and Singapore's public holidays (Nager.Date) on the calendar. Both are answered here with fixed
// data, so the tests never depend on today's weather, the holiday list or the network.

const FORECAST = '**/v2/real-time/api/two-hr-forecast';
const HOLIDAYS = '**/api/v3/PublicHolidays/**';

const forecastBody = {
  code: 0,
  data: {
    area_metadata: [],
    items: [
      {
        timestamp: '2026-10-13T09:30:00+08:00',
        valid_period: { text: '9.30 am to 11.30 am' },
        forecasts: [
          { area: 'Toa Payoh', forecast: 'Thundery Showers' },
          { area: 'Bedok', forecast: 'Partly Cloudy (Day)' },
        ],
      },
    ],
  },
};

/** Today in the browser's own time zone, as the calendar counts it. */
function todayIso(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

test.beforeEach(async ({ page, request }) => {
  await resetDemo(request);
  // The weather card sits under Home's "See more about this week".
  await showMoreOnHome(page);
});

test('Home shows the forecast for the chosen area and remembers it', async ({ page }) => {
  await page.route(FORECAST, (route) => route.fulfill({ json: forecastBody }));
  await page.goto('/');

  const card = page.getByTestId('weather-card');
  await expect(card.getByTestId('weather-forecast')).toHaveText('Thundery showers');
  await expect(card).toContainText('An indoor activity may be easier today.');
  await expect(card).toContainText('9.30 am to 11.30 am');

  // The sky behind the card follows the forecast: a storm, then a partly cloudy day.
  await expect(card).toHaveAttribute('data-scene', /^storm-(day|night)$/);
  await expect(card.locator('.sky canvas')).toHaveCount(1);

  await card.getByLabel('Area').selectOption('Bedok');
  await expect(card.getByTestId('weather-forecast')).toHaveText('Partly cloudy');
  await expect(card).toHaveAttribute('data-scene', 'partly-day');

  await page.reload();
  await expect(page.getByLabel('Area')).toHaveValue('Bedok');
});

test('Home still works when the forecast cannot be reached', async ({ page }) => {
  await page.route(FORECAST, (route) => route.abort());
  await page.goto('/');

  await expect(page.getByTestId('weather-card')).toContainText(
    'The weather forecast could not be loaded right now.',
  );
  // No forecast, no sky: the card keeps its plain look.
  await expect(page.getByTestId('weather-card')).not.toHaveAttribute('data-scene', /.+/);
  // The Care+ API's own data is unaffected.
  await expect(page.getByRole('heading', { name: 'The last two weeks' })).toBeVisible();
});

test('the calendar marks public holidays and lists the ones this month', async ({ page }) => {
  const today = todayIso();
  await page.route(HOLIDAYS, (route) =>
    route.fulfill({ json: [{ date: today, localName: 'Test Day', name: 'Test Day' }] }),
  );
  await page.goto('/calendar');

  await expect(page.getByTestId('public-holidays')).toContainText('Test Day');
  await expect(page.locator(`[data-iso="${today}"]`)).toHaveAttribute(
    'aria-label',
    /public holiday: Test Day/,
  );
  // Today is the chosen day when the calendar opens.
  await expect(page.getByText('Public holiday: Test Day')).toBeVisible();
});

test('the calendar still works when the holidays cannot be reached', async ({ page }) => {
  await page.route(HOLIDAYS, (route) => route.abort());
  await page.goto('/calendar');

  await expect(page.getByTestId('public-holidays')).toContainText(
    'The public holidays could not be loaded.',
  );
  await expect(page.getByRole('heading', { name: 'Calendar', level: 1 })).toBeVisible();
});

test('the weather sky stands still for readers who ask for less motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route(FORECAST, (route) => route.fulfill({ json: forecastBody }));
  await page.goto('/');
  const card = page.getByTestId('weather-card');
  await expect(card).toHaveAttribute('data-scene', /^storm-/);
  const moving = await card
    .locator('.sky-cloud')
    .evaluateAll((clouds) => clouds.filter((c) => getComputedStyle(c).animationName !== 'none'));
  expect(moving).toHaveLength(0);
});
