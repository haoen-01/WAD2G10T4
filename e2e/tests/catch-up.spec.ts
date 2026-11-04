import { expect, test, type APIRequestContext } from '@playwright/test';

import { API_URL, resetDemo } from './support';

// "Since you last visited" on Home. The e2e run keeps LLM_ENABLED=false, so Care+ assembles the
// catch-up itself and must say so; the agent path is covered by the API tests.

test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

async function groupId(request: APIRequestContext): Promise<string> {
  const response = await request.get(`${API_URL}/v1/me`, {
    headers: { 'X-Demo-Sub': 'demo-family' },
  });
  expect(response.ok()).toBe(true);
  const me = (await response.json()) as { groups: { group_id: string; my_status: string }[] };
  return me.groups.find((group) => group.my_status === 'active')!.group_id;
}

test('the first visit shows where things stand, the next one what changed since', async ({
  page,
  request,
}) => {
  await page.goto('/');
  const card = page.getByTestId('catch-up');
  await expect(card.getByRole('heading', { name: 'Where things stand' })).toBeVisible();
  await expect(card).toHaveAttribute('data-mode', 'fallback_disabled');
  await expect(card).toContainText('Put together by Care+');
  await expect(card).not.toContainText('assistant');
  await expect(card).toContainText('still need someone');

  // John visits after Sarah last looked: the next visit to Home names it.
  const response = await request.post(`${API_URL}/v1/groups/${await groupId(request)}/check-ins`, {
    headers: { 'X-Demo-Sub': 'demo-john' },
    data: { kind: 'visited' },
  });
  expect(response.status()).toBe(201);

  await page.reload();
  await expect(card.getByRole('heading', { name: 'Since you last visited' })).toBeVisible();
  await expect(card).toContainText('1 update from the family since you last looked.');
  await expect(card.getByRole('listitem').first()).toContainText('John visited Mdm Lim');
});
