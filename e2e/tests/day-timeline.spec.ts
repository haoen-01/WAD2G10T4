import { expect, test } from '@playwright/test';

import { API_URL, isoDay, resetDemo, showMoreOnHome } from './support';

// Home's day timeline: the senior's day by the hour, live. The demo family calendar has a doctor's
// appointment tomorrow from 10:00 am to 12:00 pm that nobody has taken yet.

test.beforeEach(async ({ page, request }) => {
  await resetDemo(request);
  // The timeline sits under Home's "See more about this week".
  await showMoreOnHome(page);
});

test('an appointment that needs someone can be taken from the timeline', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const timeline = page.getByTestId('day-timeline');
  await expect(timeline).toBeVisible();
  await expect(timeline).toContainText('Live');

  await timeline.getByRole('button', { name: 'Day after' }).click();
  await timeline.getByRole('listitem', { name: /Doctor.s appointment/ }).click();
  const details = page.getByTestId('timeline-details');
  await expect(details).toContainText('10:00 am – 12:00 pm');
  await expect(details).toContainText('Still needs someone to go along');

  await page.getByTestId('timeline-go').click();
  await expect(page.getByTestId('timeline-going')).toContainText('You’re going');
  await expect(page.getByTestId('timeline-go')).toHaveCount(0);

  // Changing your mind later does not need the toast: "Can't go" stays on the card.
  await page.getByTestId('timeline-cant-go').click();
  await expect(details).toContainText('Still needs someone to go along');
  await expect(page.getByTestId('timeline-go')).toBeVisible();
});

test('ticking a task in the Tasks panel shows on the timeline at once', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const timeline = page.getByTestId('day-timeline');
  await expect(timeline).toContainText('0/5 tasks done');

  await page.getByTestId('task-panel').locator('.task-label').first().click();
  await expect(timeline).toContainText('1/5 tasks done');
});

test('an earlier day shows what she did, and Today comes back', async ({ page }) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const timeline = page.getByTestId('day-timeline');
  await timeline.getByRole('button', { name: 'Day before' }).click();
  await expect(page.getByTestId('timeline-record')).toContainText('What');
  await page.getByTestId('timeline-today').click();
  await expect(page.getByTestId('timeline-record')).toHaveCount(0);
  await expect(timeline).toContainText('Live');
});

test('a family update is a round avatar at its time, and says who changed what', async ({
  page,
  request,
}) => {
  // John moves the eye check-up to another day, through the API, as the calendar would.
  const headers = { 'X-Demo-Sub': 'demo-john' };
  const me = (await (await request.get(`${API_URL}/v1/me`, { headers })).json()) as {
    groups: { group_id: string; my_status: string }[];
  };
  const groupId = me.groups.find((group) => group.my_status === 'active')!.group_id;
  const calendar = (await (
    await request.get(`${API_URL}/v1/people/mdm-lim/calendar`, { headers })
  ).json()) as {
    appointments: {
      appointment_id: string;
      title: string;
      kind: string;
      date: string;
      start: string;
      end: string;
      location: string | null;
      repeat: string;
    }[];
  };
  const eye = calendar.appointments.find((item) => item.title === 'Eye check-up')!;
  const moved = await request.put(
    `${API_URL}/v1/groups/${groupId}/appointments/${eye.appointment_id}`,
    {
      headers,
      data: { ...eye, date: isoDay(9), repeat: eye.repeat ?? 'none' },
    },
  );
  expect(moved.ok()).toBe(true);

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  const timeline = page.getByTestId('day-timeline');
  const marker = timeline.locator('.marker-family', { hasText: 'J' }).last();
  await expect(marker).toBeVisible();
  // The initial sits in a filled circle, centred, like the task markers.
  const avatar = marker.locator('.avatar');
  await expect(avatar).toHaveCSS('border-radius', '50%');
  const fill = await avatar.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(fill).not.toBe('rgba(0, 0, 0, 0)');
  const [box, circle] = [await marker.boundingBox(), await avatar.boundingBox()];
  expect(Math.abs(box!.x + box!.width / 2 - (circle!.x + circle!.width / 2))).toBeLessThan(2);

  // Tapping it says who changed which appointment, and to which day, from the stored history.
  await marker.click();
  const details = page.getByTestId('timeline-details');
  await expect(details).toContainText('John changed Eye check-up');
  await expect(details).toContainText(/on \w{3}, \d{1,2} \w{3}/);
});
