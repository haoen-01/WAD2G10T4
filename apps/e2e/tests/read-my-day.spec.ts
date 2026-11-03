import { expect, test } from '@playwright/test';

import { resetDemo } from './support';

// "Read my day" on the senior's Today tab. The e2e run keeps LLM_ENABLED=false, so Care+ writes
// the run-through itself and must say so; the agent path is covered by the API tests.

test.use({ timezoneId: 'Asia/Singapore' });
test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

test('the senior asks for their day and gets it read and shown', async ({ page }) => {
  // Count what the page asks the browser to say, without making a sound.
  await page.addInitScript(() => {
    const spoken: string[] = [];
    (window as unknown as { spoken: string[] }).spoken = spoken;
    window.speechSynthesis.speak = (utterance: SpeechSynthesisUtterance) => {
      spoken.push(utterance.text);
    };
  });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();

  const card = page.getByTestId('read-my-day');
  await card.getByRole('button', { name: 'Read my day' }).click();
  const script = card.getByTestId('my-day-script');
  await expect(script).toHaveAttribute('data-mode', 'fallback_disabled');
  await expect(script).toContainText(/^Good (morning|afternoon|evening), Mdm Lim\./);
  await expect(script).toContainText('Put together by Care+ from your calendar.');
  await expect(script).not.toContainText('assistant');

  const spoken = await page.evaluate(() => (window as unknown as { spoken: string[] }).spoken);
  expect(spoken).toHaveLength(1);
  expect(spoken[0]).toMatch(/^Good (morning|afternoon|evening), Mdm Lim\./);
});
