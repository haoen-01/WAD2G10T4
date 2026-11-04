/**
 * The parts of "Read my day" (see `composables/useReadAloud.ts`) that decide, rather than play:
 * when the Kokoro voice on the Care+ server is only busy (ask again in a moment) and when it truly
 * cannot speak (read with the browser's own voice), and whether this device can read aloud at
 * all. Pure, so `node --test` can check it.
 */

/**
 * The `code` of the speech route's 503 when Kokoro is busy with another sentence (the server's
 * `SPEECH_BUSY_CODE` in `silverloop/tts/engine.py`). Any other 503 means it cannot speak.
 */
export const SPEECH_BUSY_CODE = 'speech_busy';

/** How many more times one sentence is asked for after a busy answer, before giving up on it. */
export const BUSY_RETRIES = 2;
/** The wait before asking again; the server has already waited its own few seconds for a turn. */
export const BUSY_RETRY_MS = 500;

/** Kokoro is busy with another sentence: this one may be asked for again in a moment. */
export class SpeechBusyError extends Error {
  readonly busy = true;

  constructor(message = 'The Kokoro voice is busy. Try again in a moment.') {
    super(message);
    this.name = 'SpeechBusyError';
  }
}

export function isSpeechBusy(error: unknown): boolean {
  return (
    error instanceof SpeechBusyError ||
    (typeof error === 'object' && error !== null && (error as { busy?: unknown }).busy === true)
  );
}

/** Whether a 503 body from the speech route says "busy" (`{ code: "speech_busy", detail }`). */
export function isBusyBody(text: string): boolean {
  try {
    const body: unknown = JSON.parse(text);
    return (
      typeof body === 'object' &&
      body !== null &&
      (body as { code?: unknown }).code === SPEECH_BUSY_CODE
    );
  } catch {
    return false;
  }
}

const pause = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));

/**
 * The audio for each sentence of one reading, asked for once. The next sentence is asked for while
 * one plays (`prefetch`); when its turn comes (`forTurn`), a busy answer is not kept: the sentence
 * is asked for again, up to `retries` more times, `delayMs` apart, while `stillWanted()` holds.
 * Any other failure (or still busy after the retries) rejects with that error.
 */
export function sentenceFetcher<T>(
  fetchOne: (at: number) => Promise<T>,
  options: {
    stillWanted: () => boolean;
    retries?: number;
    delayMs?: number;
    wait?: (ms: number) => Promise<void>;
  },
) {
  const retries = options.retries ?? BUSY_RETRIES;
  const delayMs = options.delayMs ?? BUSY_RETRY_MS;
  const wait = options.wait ?? pause;
  const asked: (Promise<T> | undefined)[] = [];

  function ask(at: number): Promise<T> {
    let made = asked[at];
    if (!made) {
      made = fetchOne(at);
      asked[at] = made;
      const mine = made;
      // A busy answer is forgotten, so the sentence's turn asks for it afresh.
      mine.catch((error: unknown) => {
        if (isSpeechBusy(error) && asked[at] === mine) asked[at] = undefined;
      });
    }
    return made;
  }

  /** Asks for a sentence ahead of its turn; a failure here is dealt with when its turn comes. */
  function prefetch(at: number): void {
    void ask(at).catch(() => undefined);
  }

  async function forTurn(at: number): Promise<T> {
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await ask(at);
      } catch (error) {
        if (!isSpeechBusy(error) || attempt >= retries || !options.stillWanted()) throw error;
        asked[at] = undefined;
        await wait(delayMs);
        if (!options.stillWanted()) throw error;
      }
    }
  }

  return { prefetch, forTurn };
}

/**
 * True when this device cannot read aloud at all: the Kokoro voice is known not to be there (no
 * server, or it said it cannot speak) and the browser has finished listing its voices with none
 * of its own. False while either is still unknown, so the card never says so too early.
 */
export function noReadingVoice(known: {
  kokoroKnown: boolean;
  kokoroReady: boolean;
  deviceKnown: boolean;
  deviceHasVoice: boolean;
}): boolean {
  return known.kokoroKnown && !known.kokoroReady && known.deviceKnown && !known.deviceHasVoice;
}
