import { expect, test, type Page } from '@playwright/test';

import { openSettings } from './support';

// Kaki, the Care+ assistant, on every screen for seniors and their families. With no OpenAI key
// (as here, in the offline demo) the API's built-in helper answers. Voice typing uses a stand-in
// for the browser's speech recognition, since a test browser has no microphone.

const orb = (page: Page) => page.getByTestId('assistant-orb');
const panel = (page: Page) => page.getByTestId('assistant-panel');

async function enterAs(page: Page, who: 'senior' | 'family') {
  await page.goto(`/login/${who}`);
  await page.getByTestId(`continue-${who}`).click();
  await expect(orb(page)).toBeVisible();
}

test('the senior asks Kaki about her day, and the chat is kept when minimised', async ({
  page,
}) => {
  await enterAs(page, 'senior');
  await orb(page).click();
  await expect(panel(page).getByRole('heading', { name: 'Kaki' })).toBeVisible();
  await expect(panel(page)).toContainText('Hello, Mdm Lim! I’m Kaki.'.replace('’', "'"));
  await expect(page.getByTestId('assistant-input')).toBeFocused();

  // A suggestion asks straight away; the helper answers from her own steps.
  await page.getByTestId('assistant-chip').filter({ hasText: 'How many steps today?' }).click();
  await expect(page.getByTestId('assistant-assistant').last()).toContainText(
    /your watch counted [\d,]+ steps/,
  );

  // Enter sends; Shift + Enter is a new line; Send waits for words.
  const box = page.getByTestId('assistant-input');
  await expect(page.getByTestId('assistant-send')).toBeDisabled();
  await box.fill("What's coming up");
  await box.press('Shift+Enter');
  await box.type('tomorrow?');
  await expect(box).toHaveValue("What's coming up\ntomorrow?");
  await box.press('Enter');
  await expect(page.getByTestId('assistant-assistant').last()).toContainText('Next up:');
  await expect(box).toHaveValue('');

  // Minimise, and back: the conversation is still there. Escape minimises too.
  await page.getByTestId('assistant-minimise').click();
  await expect(panel(page)).toHaveCount(0);
  await expect(orb(page)).toBeFocused();
  await orb(page).click();
  await expect(page.getByTestId('assistant-user')).toHaveCount(2);
  await page.keyboard.press('Escape');
  await expect(panel(page)).toHaveCount(0);

  // It follows her to another tab.
  await page.getByRole('tab', { name: /Calendar/ }).click();
  await orb(page).click();
  await expect(page.getByTestId('assistant-user')).toHaveCount(2);
  await page.getByTestId('assistant-clear').click();
  await expect(page.getByTestId('assistant-user')).toHaveCount(0);
});

test('an emergency or a medicine question gets the fixed safety answer', async ({ page }) => {
  await enterAs(page, 'senior');
  await orb(page).click();
  await page.getByTestId('assistant-input').fill('I fell down and my hip hurts');
  await page.getByTestId('assistant-input').press('Enter');
  await expect(page.getByTestId('assistant-assistant').last()).toContainText('call 995');
  await page.getByTestId('assistant-input').fill('Can I take two pills?');
  await page.getByTestId('assistant-input').press('Enter');
  await expect(page.getByTestId('assistant-assistant').last()).toContainText(
    'doctor, nurse or pharmacist',
  );
});

test('family ask about her, and a reply that comes while minimised shows as new', async ({
  page,
}) => {
  await enterAs(page, 'family');
  // The answer takes a moment, as it would from the AI.
  await page.route('**/v1/assistant/chat', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.continue();
  });
  await orb(page).click();
  await expect(page.getByTestId('assistant-chip').first()).toHaveText(
    'How are Mdm Lim’s steps today?',
  );
  await page.getByTestId('assistant-input').fill('How many steps today?');
  await page.getByTestId('assistant-input').press('Enter');
  // Minimised before the answer arrives: a badge on the orb says there is one to read.
  await page.getByTestId('assistant-minimise').click();
  await expect(page.getByTestId('assistant-unread')).toHaveText('1');
  await expect(orb(page)).toHaveAttribute('aria-label', /1 new reply/);
  await orb(page).click();
  await expect(page.getByTestId('assistant-unread')).toHaveCount(0);
  await expect(page.getByTestId('assistant-assistant').last()).toContainText('Mdm Lim’s watch');
});

test('Kaki can be dragged without opening, stays on screen, and is remembered', async ({
  page,
}) => {
  await enterAs(page, 'family');
  const start = await orb(page).boundingBox();
  if (!start) throw new Error('no orb');
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(400, 300, { steps: 10 });
  await page.mouse.up();
  await expect(panel(page)).toHaveCount(0);
  await expect
    .poll(async () => Math.round((await orb(page).boundingBox())?.y ?? 0))
    .toBeLessThan(start.y - 100);

  // Dragged off the edge: it stays on screen, snapped against the side.
  await page.mouse.move(400, 300);
  const now = await orb(page).boundingBox();
  if (!now) throw new Error('no orb');
  await page.mouse.move(now.x + now.width / 2, now.y + now.height / 2);
  await page.mouse.down();
  await page.mouse.move(-200, now.y + now.height / 2, { steps: 10 });
  await page.mouse.up();
  await expect.poll(async () => Math.round((await orb(page).boundingBox())?.x ?? -1)).toBe(12);

  // Arrow keys move it too, and its place is kept after a reload.
  await orb(page).focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(async () => Math.round((await orb(page).boundingBox())?.x ?? -1)).toBe(36);
  await page.reload();
  await expect.poll(async () => Math.round((await orb(page).boundingBox())?.x ?? -1)).toBe(36);
});

test('its eyes follow the pointer', async ({ page }) => {
  await enterAs(page, 'family');
  const eye = page.locator('[data-testid="assistant-orb"] .orb-eye').first();
  /** How far the eye has moved down (negative: up). */
  const down = async () =>
    Number(((await eye.getAttribute('style')) ?? '').match(/translate: \S+px (\S+)px/)?.[1] ?? 0);
  const size = page.viewportSize();
  if (!size) throw new Error('no viewport');
  await page.mouse.move(5, 5);
  await expect.poll(down).toBeLessThan(-1);
  await page.mouse.move(5, size.height - 2);
  await expect.poll(down).toBeGreaterThan(0);
});

test('voice typing asks first, then types what she says for her to send', async ({ page }) => {
  // A stand-in for the browser's speech recognition.
  await page.addInitScript(() => {
    class StandIn {
      onresult: ((event: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      onerror: ((event: unknown) => void) | null = null;
      start() {
        setTimeout(() => {
          this.onresult?.({
            resultIndex: 0,
            results: [{ isFinal: true, 0: { transcript: 'what is coming up' } }],
          });
          this.onend?.();
        }, 200);
      }
      stop() {
        this.onend?.();
      }
      abort() {}
    }
    Object.assign(window, { SpeechRecognition: StandIn, webkitSpeechRecognition: StandIn });
  });
  await enterAs(page, 'senior');
  await orb(page).click();
  await page.getByTestId('assistant-mic').click();
  // The first time, where the voice goes is explained, and nothing listens until she agrees.
  await expect(panel(page).getByRole('dialog', { name: 'Voice typing' })).toContainText(
    'Google or Apple',
  );
  await page.getByTestId('voice-agree').click();
  await expect(page.getByTestId('assistant-input')).toHaveValue('what is coming up');
  // Nothing is sent until she presses Send.
  await expect(page.getByTestId('assistant-user')).toHaveCount(0);
  await page.getByTestId('assistant-send').click();
  await expect(page.getByTestId('assistant-assistant').last()).toContainText('Next up:');

  // Next time it listens straight away.
  await page.getByTestId('assistant-mic').click();
  await expect(page.getByTestId('voice-agree')).toHaveCount(0);
  await expect(page.getByTestId('assistant-input')).toHaveValue('what is coming up');
});

test('signing out forgets the conversation, so the next person starts afresh', async ({ page }) => {
  await enterAs(page, 'family');
  await orb(page).click();
  await page.getByTestId('assistant-input').fill('How many steps today?');
  await page.getByTestId('assistant-input').press('Enter');
  await expect(page.getByTestId('assistant-assistant')).toHaveCount(1);
  await page.getByTestId('assistant-minimise').click();
  await expect(orb(page)).toBeFocused();

  await openSettings(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByTestId('choose-senior').click();
  await page.getByTestId('continue-senior').click();
  await orb(page).click();
  await expect(page.getByTestId('assistant-user')).toHaveCount(0);
  await expect(page.getByTestId('assistant-chip').first()).toHaveText('How many steps today?');
});

test('there is no Kaki on the sign-in screens', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByTestId('assistant-orb')).toHaveCount(0);
});
