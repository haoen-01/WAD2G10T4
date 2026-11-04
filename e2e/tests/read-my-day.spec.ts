import { expect, test, type Page } from '@playwright/test';

import { resetDemo } from './support';

// "Read my day" on the senior's Today tab. The e2e run keeps LLM_ENABLED=false, so Care+ writes
// the run-through itself and must say so; the agent path is covered by the API tests.

test.use({ timezoneId: 'Asia/Singapore' });
test.beforeEach(async ({ request }) => {
  await resetDemo(request);
});

interface Said {
  text: string;
  rate: number;
  pitch: number;
  voice: string | null;
}

/** The voices the fake browser offers: Edge's local ones at once, and any `late` ones after 400 ms. */
interface FakeVoice {
  name: string;
  lang: string;
  /** Whether the device speaks it itself; by default the `first` ones do and the `late` ones
   *  (Edge's online voices) do not. */
  localService?: boolean;
}
interface VoiceSetup {
  first: FakeVoice[];
  late?: FakeVoice[];
}

const EDGE_LOCAL = [
  { name: 'Microsoft David - English (United States)', lang: 'en-US' },
  { name: 'Microsoft Mark - English (United States)', lang: 'en-US' },
  { name: 'Microsoft Zira - English (United States)', lang: 'en-US' },
];
const EDGE_ONLINE = [
  { name: 'Microsoft Wayne Online (Natural) - English (Singapore)', lang: 'en-SG' },
  { name: 'Microsoft Luna Online (Natural) - English (Singapore)', lang: 'en-SG' },
  { name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' },
];

/**
 * A silent stand-in for the browser's speech engine: it records each sentence (and the voice it
 * was given) and "finishes" it a moment later, as the real engine would. `hold` keeps the current
 * sentence from finishing, so a test can pause mid-sentence. Its voice list behaves like Edge's:
 * the local voices first, the online "Natural" ones added later with a `voiceschanged` event.
 */
async function fakeSpeech(page: Page, voices: VoiceSetup = { first: EDGE_LOCAL }) {
  await page.addInitScript((setup: VoiceSetup) => {
    const said: Said[] = [];
    const state = { hold: false, paused: false, current: null as FakeUtterance | null };
    Object.assign(window, { said, speechState: state });
    const synth = window.speechSynthesis;
    let list = setup.first.map((voice) => ({ localService: true, ...voice, default: false }));
    if (setup.late) {
      setTimeout(() => {
        list = [
          ...list,
          ...setup.late!.map((v) => ({ localService: false, ...v, default: false })),
        ];
        synth.dispatchEvent(new Event('voiceschanged'));
      }, 400);
    }
    synth.getVoices = () => list as unknown as SpeechSynthesisVoice[];

    // The real utterance only takes real voice objects, so the fake takes its place.
    class FakeUtterance {
      text: string;
      voice: { name: string } | null = null;
      lang = '';
      rate = 1;
      pitch = 1;
      onend: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    }
    Object.assign(window, { SpeechSynthesisUtterance: FakeUtterance });

    const finish = () => {
      const utterance = state.current;
      if (!utterance || state.hold || state.paused) return;
      state.current = null;
      utterance.onend?.(new Event('end'));
    };
    Object.defineProperty(synth, 'speaking', { get: () => state.current !== null });
    Object.defineProperty(synth, 'paused', { get: () => state.paused });
    synth.speak = (utterance) => {
      const spoken = utterance as unknown as FakeUtterance;
      said.push({
        text: spoken.text,
        rate: spoken.rate,
        pitch: spoken.pitch,
        voice: spoken.voice?.name ?? null,
      });
      state.current = spoken;
      setTimeout(finish, 30);
    };
    synth.pause = () => {
      state.paused = true;
    };
    synth.resume = () => {
      state.paused = false;
      setTimeout(finish, 30);
    };
    synth.cancel = () => {
      state.current = null;
      state.paused = false;
    };
  }, voices);
}

const said = (page: Page) => page.evaluate(() => (window as unknown as { said: Said[] }).said);

test('the senior asks for their day and hears it a sentence at a time', async ({ page }) => {
  await fakeSpeech(page);
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();

  const card = page.getByTestId('read-my-day');
  await card.getByRole('button', { name: 'Read my day' }).click();
  const script = card.getByTestId('my-day-script');
  await expect(script).toHaveAttribute('data-mode', 'fallback_disabled');
  await expect(script).toContainText(/^Good (morning|afternoon|evening), Mdm Lim\./);
  await expect(script).toContainText('Put together by Care+ from your calendar.');
  await expect(script).not.toContainText('assistant');

  // Every sentence is read, in order, slower than everyday speech, then the button is back.
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 15_000 });
  const sentences = await said(page);
  expect(sentences.length).toBeGreaterThan(1);
  expect(sentences[0].text).toMatch(/^Good (morning|afternoon|evening), Mdm Lim\.$/);
  for (const sentence of sentences) {
    expect(sentence.rate).toBeLessThan(1);
    expect(sentence.text).not.toMatch(/\d (am|pm)\b/); // said as "a.m." / "p.m."
  }
});

test('the reading can be paused, resumed and stopped', async ({ page }) => {
  await fakeSpeech(page);
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  // Hold the first sentence so the reading is still going when Pause is pressed.
  await page.evaluate(() => {
    (window as unknown as { speechState: { hold: boolean } }).speechState.hold = true;
  });

  const card = page.getByTestId('read-my-day');
  await card.getByRole('button', { name: 'Read my day' }).click();
  const pause = card.getByTestId('read-my-day-pause');
  await expect(pause).toHaveText(/Pause/);
  // A short status is announced, not the whole day's script.
  await expect(card.getByTestId('my-day-status')).toHaveText('Reading your day.');
  await expect(card.getByTestId('my-day-script')).not.toHaveAttribute('role');
  await pause.click();
  await expect(pause).toHaveText(/Resume/);
  // The label says what the button will do next (a changing label, not a toggle state).
  await expect(card.getByRole('button', { name: 'Resume' })).toBeVisible();
  await expect(pause).not.toHaveAttribute('aria-pressed');
  await expect(card.getByRole('button', { name: 'Stop reading' })).not.toHaveAttribute(
    'aria-pressed',
  );
  await expect(card.getByTestId('my-day-status')).toHaveText('Reading paused.');

  await page.evaluate(() => {
    (window as unknown as { speechState: { hold: boolean } }).speechState.hold = false;
  });
  await pause.click();
  await expect(pause).toHaveText(/Pause/);
  await expect.poll(async () => (await said(page)).length).toBeGreaterThan(1);

  await card.getByRole('button', { name: 'Stop reading' }).click();
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible();
  await expect(pause).toHaveCount(0);
});

// Online browser voices (Edge's "Online (Natural)" ones, Chrome's "Google …" ones) are spoken by
// Microsoft's or Google's servers, so the senior's day would leave the device: they are never used.

test('in Edge it never reads with an online voice, even Luna: only with the device’s own', async ({
  page,
}) => {
  await fakeSpeech(page, { first: EDGE_LOCAL, late: EDGE_ONLINE });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();

  const card = page.getByTestId('read-my-day');
  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Zira · English (United States)',
  );
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 15_000 });
  const voices = new Set((await said(page)).map((sentence) => sentence.voice));
  // One voice for the whole reading, and it is on the device.
  expect([...voices]).toEqual(['Microsoft Zira - English (United States)']);
  // The online voices are not offered either.
  await card.getByText('Choose a voice').click();
  await expect(
    card.getByTestId('my-day-voice-choice').locator('option', { hasText: 'Online' }),
  ).toHaveCount(0);
  await expect(
    card.getByTestId('my-day-voice-choice').locator('option', { hasText: 'Luna' }),
  ).toHaveCount(0);
});

test('without natural voices it falls back to the best one there is, and says which', async ({
  page,
}) => {
  await fakeSpeech(page, { first: EDGE_LOCAL });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();

  const card = page.getByTestId('read-my-day');
  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Zira · English (United States)',
  );
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 15_000 });
  const voices = new Set((await said(page)).map((sentence) => sentence.voice));
  expect([...voices]).toEqual(['Microsoft Zira - English (United States)']);
});

test('in Chrome, its Google voices (spoken online) are passed over for the device’s own', async ({
  page,
}) => {
  await fakeSpeech(page, {
    first: [
      { name: 'Microsoft Zira - English (United States)', lang: 'en-US' },
      { name: 'Google US English', lang: 'en-US', localService: false },
      { name: 'Google UK English Male', lang: 'en-GB', localService: false },
      { name: 'Google US English 1 (Natural)', lang: 'en-US', localService: false },
    ],
  });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const card = page.getByTestId('read-my-day');
  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Zira · English (United States)',
  );
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 15_000 });
  const voices = new Set((await said(page)).map((sentence) => sentence.voice));
  expect([...voices]).toEqual(['Microsoft Zira - English (United States)']);
});

test('the voice can be chosen by hand from the device’s own voices', async ({ page }) => {
  await fakeSpeech(page, {
    first: [
      { name: 'Microsoft Zira - English (United States)', lang: 'en-US' },
      { name: 'Microsoft Mark - English (United States)', lang: 'en-US' },
      { name: 'Google US English 1 (Natural)', lang: 'en-US', localService: false },
    ],
  });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const card = page.getByTestId('read-my-day');
  // The device has a voice of its own, so there is nothing to warn about.
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Zira · English (United States)',
  );
  await expect(card.getByTestId('my-day-voice-hint')).toHaveCount(0);
  await card.getByText('Choose a voice').click();
  const choice = card.getByTestId('my-day-voice-choice');
  await expect(choice.locator('option', { hasText: 'Google' })).toHaveCount(0);
  await choice.selectOption('Microsoft Mark - English (United States)');
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Mark · English (United States)',
  );

  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 15_000 });
  const voices = new Set((await said(page)).map((sentence) => sentence.voice));
  expect([...voices]).toEqual(['Microsoft Mark - English (United States)']);

  // Remembered in this browser.
  await page.reload();
  await expect(page.getByTestId('my-day-voice')).toHaveText(
    'Voice: Mark · English (United States)',
  );
});

test('with only online voices, nothing is read aloud and the card says why', async ({ page }) => {
  await fakeSpeech(page, { first: [], late: EDGE_ONLINE });
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const card = page.getByTestId('read-my-day');
  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByTestId('my-day-voice-hint')).toHaveText(
    'This device has no reading voice of its own, so Care+ cannot read your day aloud here.',
    { timeout: 15_000 },
  );
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: No reading voice on this device',
  );
  // The words are still on screen to read, and the browser said nothing.
  await expect(card.getByTestId('my-day-script')).toContainText('Mdm Lim');
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible();
  expect(await said(page)).toHaveLength(0);
});

// ── The Kokoro voice on the Care+ server ─────────────────────────────────────────────────────

/** A short, silent WAV, standing in for one sentence spoken by Kokoro. */
function silentWav(milliseconds: number): Buffer {
  const rate = 8000;
  const samples = Math.round((rate * milliseconds) / 1000);
  const data = Buffer.alloc(samples * 2);
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

async function kokoroRoutes(page: Page, speech: 'works' | 'fails', voicesAsked: string[] = []) {
  const sentences: string[] = [];
  await page.route('**/my-day/voice', (route) =>
    route.fulfill({
      json: {
        available: true,
        voice: 'af_heart',
        label: 'Heart · Kokoro natural voice',
        voices: [
          { voice: 'af_heart', label: 'Heart · Kokoro natural voice' },
          { voice: 'af_bella', label: 'Bella · Kokoro natural voice' },
          { voice: 'bf_emma', label: 'Emma (British) · Kokoro natural voice' },
        ],
      },
    }),
  );
  await page.route('**/my-day/speech', async (route) => {
    const body = route.request().postDataJSON() as { text: string; voice?: string };
    sentences.push(body.text);
    voicesAsked.push(body.voice ?? 'default');
    if (speech === 'fails') {
      await route.fulfill({ status: 503, json: { detail: 'Kokoro model files are missing.' } });
      return;
    }
    await route.fulfill({ body: silentWav(400), contentType: 'audio/wav' });
  });
  return sentences;
}

test('with Kokoro on the server, every sentence is spoken in the Heart voice', async ({ page }) => {
  await fakeSpeech(page);
  const sentences = await kokoroRoutes(page, 'works');
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();

  const card = page.getByTestId('read-my-day');
  await expect(card.getByTestId('my-day-voice')).toHaveText('Voice: Heart · Kokoro natural voice');
  // The no-voice hint is about the browser's voices, so it does not apply to Kokoro.
  await expect(card.getByTestId('my-day-voice-hint')).toHaveCount(0);

  await card.getByRole('button', { name: 'Read my day' }).click();
  const pause = card.getByTestId('read-my-day-pause');
  await expect(pause).toHaveText(/Pause/);
  // A short status is announced, not the whole day's script.
  await expect(card.getByTestId('my-day-status')).toHaveText('Reading your day.');
  await expect(card.getByTestId('my-day-script')).not.toHaveAttribute('role');
  await pause.click();
  await expect(pause).toHaveText(/Resume/);
  await pause.click();
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 20_000 });

  const script = (await card.getByTestId('my-day-script').locator('.script').innerText()).trim();
  expect(sentences.length).toBeGreaterThan(1);
  expect(sentences[0]).toMatch(/^Good (morning|afternoon|evening), Mdm Lim\.$/);
  // Every word of the script was sent, in order ("10 am" is sent as "10 a.m." for clarity).
  const words = (text: string) => text.replace(/([ap])\.m\./g, '$1m').replace(/\./g, '');
  expect(words(sentences.join(' '))).toBe(words(script));
  // The browser's own speech never said a word.
  expect(await said(page)).toHaveLength(0);
});

test('when Kokoro cannot speak, the browser voice reads instead', async ({ page }) => {
  await fakeSpeech(page);
  await kokoroRoutes(page, 'fails');
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();

  const card = page.getByTestId('read-my-day');
  await expect(card.getByTestId('my-day-voice')).toHaveText('Voice: Heart · Kokoro natural voice');
  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Zira · English (United States)',
  );
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 20_000 });
  const sentences = await said(page);
  expect(sentences.length).toBeGreaterThan(1);
  expect(sentences[0].text).toMatch(/^Good (morning|afternoon|evening), Mdm Lim\.$/);
});

test('Stop ends a Kokoro reading at once', async ({ page }) => {
  await fakeSpeech(page);
  const sentences = await kokoroRoutes(page, 'works');
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const card = page.getByTestId('read-my-day');
  await expect(card.getByTestId('my-day-voice')).toHaveText('Voice: Heart · Kokoro natural voice');
  await card.getByRole('button', { name: 'Read my day' }).click();
  await card.getByRole('button', { name: 'Stop reading' }).click();
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible();
  const after = sentences.length;
  await page.waitForTimeout(1500);
  expect(sentences.length).toBeLessThanOrEqual(after + 1); // at most the one already being fetched
});

test('a Kokoro voice can be chosen by name, and every sentence asks for it', async ({ page }) => {
  await fakeSpeech(page);
  const voicesAsked: string[] = [];
  await kokoroRoutes(page, 'works', voicesAsked);
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const card = page.getByTestId('read-my-day');
  await expect(card.getByTestId('my-day-voice')).toHaveText('Voice: Heart · Kokoro natural voice');

  await card.getByText('Choose a voice').click();
  const choice = card.getByTestId('my-day-voice-choice');
  // Kokoro's voices first, by friendly name; the browser's own voices are still there below.
  await expect(choice.locator('optgroup').first()).toHaveAttribute(
    'label',
    'Natural voices (Care+)',
  );
  await expect(choice.locator('option', { hasText: 'Zira' })).toHaveCount(1);
  await choice.selectOption({ label: 'Emma (British) · Kokoro natural voice' });
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Emma (British) · Kokoro natural voice',
  );

  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 20_000 });
  expect(voicesAsked.length).toBeGreaterThan(1);
  expect(new Set(voicesAsked)).toEqual(new Set(['bf_emma']));
  expect(await said(page)).toHaveLength(0);

  // Remembered in this browser.
  await page.reload();
  await expect(page.getByTestId('my-day-voice')).toHaveText(
    'Voice: Emma (British) · Kokoro natural voice',
  );
});

test('choosing a browser voice reads with the browser even while Kokoro is there', async ({
  page,
}) => {
  await fakeSpeech(page);
  const voicesAsked: string[] = [];
  await kokoroRoutes(page, 'works', voicesAsked);
  await page.goto('/login/senior');
  await page.getByTestId('continue-senior').click();
  const card = page.getByTestId('read-my-day');
  await expect(card.getByTestId('my-day-voice')).toHaveText('Voice: Heart · Kokoro natural voice');
  await card.getByText('Choose a voice').click();
  await card
    .getByTestId('my-day-voice-choice')
    .selectOption('Microsoft Zira - English (United States)');
  await expect(card.getByTestId('my-day-voice')).toHaveText(
    'Voice: Zira · English (United States)',
  );
  await card.getByRole('button', { name: 'Read my day' }).click();
  await expect(card.getByRole('button', { name: 'Read my day' })).toBeVisible({ timeout: 20_000 });
  expect(voicesAsked).toHaveLength(0);
  const voices = new Set((await said(page)).map((sentence) => sentence.voice));
  expect([...voices]).toEqual(['Microsoft Zira - English (United States)']);
});
