import { expect, test } from '@playwright/test';

import { demoOccurrence, resetDemo } from './support';

// Asking a helper (issue #16): Sarah asks Emily by name for a day nobody has taken, the day shows
// "Asked Emily · waiting" (it still needs a helper), Emily's bell shows the ask, and her "Yes, I'll
// go" makes her the helper. The eye check-up a week out needs a helper after the reset.
test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

test('ask someone, answer from the bell, and the asked member becomes the helper', async ({
  page,
}) => {
  await page.goto('/login/family');
  await page.getByTestId('continue-family').click();
  await page.goto(`/calendar?appointment=${encodeURIComponent(demoOccurrence('demo-eye', 7))}`);

  const details = page.locator('article.details');
  await expect(details.getByRole('heading', { name: 'Eye check-up' })).toBeVisible();

  // Sarah opens "Ask someone" and picks Emily from the list (each with when they are free).
  await details.getByRole('button', { name: /^Ask someone/ }).click();
  const who = details.getByRole('group', { name: 'Who to ask' });
  await expect(who.getByText('Free: Morning')).toBeVisible(); // John shared the morning
  await who.getByRole('button', { name: 'Ask Emily to go to Eye check-up' }).click();

  await expect(details.getByTestId('asked-tag')).toContainText('Asked Emily · waiting');
  // Still needs a helper: Sarah can still go herself, or take the ask back.
  await expect(details.getByRole('button', { name: /I’ll help/ })).toBeVisible();
  // Focus moves to what replaced the list, not to the page.
  await expect(details.getByRole('button', { name: /^Withdraw/ })).toBeFocused();
  await expect(details.getByRole('button', { name: /^Ask someone/ })).toHaveCount(0);
  await expect(details.getByText('Asked · waiting')).toBeVisible(); // Emily's row in the list

  // Emily: the bell has one unread notification.
  await page.getByLabel('Viewing as').selectOption({ label: 'Emily' });
  const bell = page.getByRole('button', { name: 'Notifications, 1 unread' });
  await expect(bell).toBeVisible();
  // On the card she answers instead of "I'll help".
  await expect(details.getByTestId('asked-tag')).toContainText('Sarah asked you');
  await expect(details.getByRole('button', { name: /I’ll help/ })).toHaveCount(0);

  await bell.click();
  const panel = page.getByRole('region', { name: 'Notifications' });
  const item = panel
    .getByRole('listitem')
    .filter({ hasText: 'Sarah asked you to go to Eye check-up' });
  await expect(item).toContainText('Mdm Lim');
  // Opening the bell marked it read.
  await expect(page.getByRole('button', { name: 'Notifications', exact: true })).toBeVisible();

  await item.getByRole('button', { name: /^Yes, I’ll go/ }).click();
  await expect(item.getByRole('button', { name: /^Yes, I’ll go/ })).toHaveCount(0);
  // The item says how it ended, and keeps focus, so Escape still closes the bell from there.
  await expect(item.getByTestId('ask-outcome')).toHaveText('You said yes');
  await expect(item).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId('notification-bell')).toBeFocused();

  // Emily is the helper now, and the ask's tag has gone.
  await expect(details.getByText('Emily is going with Mdm Lim.')).toBeVisible();
  await expect(details.getByTestId('asked-tag')).toHaveCount(0);
});
