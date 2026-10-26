import { expect, test } from '@playwright/test';
import { resetDemo } from './support';

test.use({ timezoneId: 'Asia/Singapore' });
test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

test('Next up presents individual date, time, location and companion boxes on a phone', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const list = page.getByTestId('upcoming-events');
  const boxes = list.getByRole('listitem');
  await expect(boxes).toHaveCount(3);
  for (const box of await boxes.all()) {
    await expect(box).toHaveClass(/border.*rounded-3/);
    await expect(box.locator('time')).toHaveAttribute('datetime', /^\d{4}-\d{2}-\d{2}$/);
    await expect(box.locator('.date-weekday')).toHaveText(/^[A-Z]{3}$/);
    await expect(box.locator('.event-time')).toContainText(/am|pm/);
    await expect(box.getByRole('heading')).not.toBeEmpty();
    await expect(box.locator('.event-place')).not.toBeEmpty();
    await expect(box.getByRole('button')).toHaveCount(0);
  }
  await expect(list.getByText('Family is arranging who comes')).toBeVisible();
  await expect(list.getByText(/is coming with you/).first()).toBeVisible();
  for (const theme of ['light', 'dark']) {
    await page.evaluate((value) => {
      document.documentElement.dataset.bsTheme = value;
      document.documentElement.style.zoom = '1.5';
    }, theme);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
  }
  await page.getByRole('button', { name: 'See my calendar' }).click();
  await expect(page.getByRole('tab', { name: 'Calendar', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

test('completed tasks keep their chronological position and Next moves to the next undone task', async ({
  page,
}) => {
  await page.clock.install({ time: new Date('2026-10-25T00:00:00Z') });
  await page.addInitScript(() => {
    localStorage.setItem(
      'careplus.tasks.v1.mdm-lim',
      JSON.stringify({
        schedules: [
          { task_id: 'third', title: 'Third task', time: '17:00' },
          { task_id: 'first', title: 'First task', time: '09:00' },
          { task_id: 'second', title: 'Second task', time: '12:00' },
        ].map((task) => ({
          ...task,
          start_date: '2026-10-25',
          repeat: 'daily',
          repeat_until: null,
          notes: '',
          kind: 'task',
        })),
        completions: {},
      }),
    );
  });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const panel = page.getByTestId('task-panel');
  const titles = panel.locator('.task-title');
  await expect(titles).toHaveText(['First task', 'Second task', 'Third task']);
  await expect(panel.locator('.next-task .task-title')).toHaveText('First task');
  await panel.getByRole('button', { name: 'Mark First task done', exact: true }).click();
  await expect(titles).toHaveText(['First task', 'Second task', 'Third task']);
  await expect(panel.locator('.task-row').first()).toHaveClass(/completed/);
  await expect(panel.locator('.next-task .task-title')).toHaveText('Second task');
  await panel.getByRole('button', { name: 'Mark First task not done', exact: true }).click();
  await expect(titles).toHaveText(['First task', 'Second task', 'Third task']);
  await expect(panel.locator('.next-task .task-title')).toHaveText('First task');
});
