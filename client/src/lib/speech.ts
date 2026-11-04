/**
 * How "Read my day" sounds (see `composables/useReadAloud.ts`). Pure, so `node --test` can check
 * it: which of the browser's own voices to use, and how the script is broken into calm, clearly
 * spoken sentences.
 *
 * Only on-device voices are ever used (`localService === true`). A browser's online voices (Edge's
 * "Online (Natural)" ones, Chrome's "Google …" ones) are spoken by Microsoft's or Google's servers,
 * which would send the senior's day (their name, appointments, who is going) to them. They are
 * never chosen, never listed, and when a device has no voice of its own, nothing is read aloud.
 */

/** The parts of a `SpeechSynthesisVoice` the choice depends on. */
export interface VoiceLike {
  name: string;
  lang: string;
  localService?: boolean;
}

/** Whether the device itself speaks with this voice, so the words never leave it. */
export function isOnDeviceVoice(voice: VoiceLike): boolean {
  return voice.localService === true;
}

/** Said on the card when the device has no voice of its own to read with. */
export const NO_DEVICE_VOICE_HINT =
  'This device has no reading voice of its own, so Care+ cannot read your day aloud here.';

/** Slightly slower than everyday speech, still conversational. */
export const SPEECH_RATE = 0.88;
/** A touch above neutral reads as warmer without sounding put on. */
export const SPEECH_PITCH = 1.05;
/** A breath between sentences, so each appointment and reminder lands on its own. */
export const SENTENCE_PAUSE_MS = 380;

// Voices that are male; never chosen for this calm, female narrator.
const MALE =
  /\b(david|mark|george|james|guy|ryan|wayne|william|thomas|daniel|alex|fred|aaron|arthur|oliver|eric|christopher|brian|roger|steffan|andrew|liam|connor|mitchell|prabhat|ravi|rishi|gordon|lee|tom|male)\b/i;
// Female voices that sound natural, by the names the main browsers and systems give them.
const WARM_FEMALE =
  /\b(luna|aria|jenny|libby|sonia|maisie|natasha|clara|emily|emma|ava|michelle|neerja|asilia|samantha|karen|moira|tessa|serena|kate|fiona|veena|catherine|martha|nicky|female)\b/i;
// Older desktop voices that are female but noticeably robotic: a last resort only.
const PLAIN_FEMALE = /\b(zira|hazel|susan|heera|linda|hedda)\b/i;
// Words the systems use for their high-quality voices.
const NATURAL = /\b(natural|neural|premium|enhanced|siri)\b/i;

/**
 * How well a voice suits a warm, gentle reading of the senior's day. Negative: never pick it
 * automatically. An online voice is never used at all (see the top of this file).
 */
export function voiceScore(voice: VoiceLike): number {
  if (!isOnDeviceVoice(voice)) return -2000;
  const lang = voice.lang.replace('_', '-').toLowerCase();
  if (!lang.startsWith('en')) return -1000;
  if (MALE.test(voice.name)) return -500;
  let score = 0;
  if (lang === 'en-sg') score += 40;
  else if (['en-gb', 'en-au', 'en-ie', 'en-nz'].includes(lang)) score += 22;
  else if (lang === 'en-us') score += 18;
  else score += 10;
  if (NATURAL.test(voice.name)) score += 35;
  if (WARM_FEMALE.test(voice.name)) score += 30;
  else if (PLAIN_FEMALE.test(voice.name)) score += 8;
  // Chrome's "Google US English" is a female voice, though its name does not say so.
  else if (/^google us english$/i.test(voice.name.trim())) score += 25;
  return score;
}

/**
 * A voice's name as a person would read it under the card: "Microsoft Luna Online (Natural) -
 * English (Singapore)" becomes "Luna · Natural · English (Singapore)".
 */
export function voiceLabel(voice: VoiceLike | null): string {
  if (!voice) return 'No reading voice on this device';
  const match =
    /^(?:microsoft|google|apple)?\s*(.*?)\s*(?:online)?\s*(\(natural\))?\s*-\s*(.+)$/i.exec(
      voice.name.trim(),
    );
  if (!match) return voice.name;
  const [, base, natural, language] = match;
  return [base.trim(), natural ? 'Natural' : null, language.trim()].filter(Boolean).join(' · ');
}

/** The best on-device voice for the narration, or null when none suits it. */
export function pickVoice<T extends VoiceLike>(voices: readonly T[]): T | null {
  let best: T | null = null;
  let bestScore = 0;
  for (const voice of voices) {
    const score = voiceScore(voice);
    if (score > bestScore) {
      best = voice;
      bestScore = score;
    }
  }
  return best;
}

/**
 * The script as sentences to read one after another, with times written so every engine says
 * them clearly: "10:30 am" becomes "10:30 a.m." (some read a bare "am" as the word "am").
 */
export function speechChunks(script: string): string[] {
  const spoken = script
    .replace(/\b(\d{1,2}(?::\d{2})?)\s*am\b/gi, '$1 a.m.')
    .replace(/\b(\d{1,2}(?::\d{2})?)\s*pm\b/gi, '$1 p.m.')
    // "5 pm." at a sentence end is now "5 p.m.." -- one full stop is enough.
    .replace(/\b([ap])\.m\.\./g, '$1.m.')
    .replace(/\s+/g, ' ')
    .trim();
  if (!spoken) return [];
  // A sentence ends at . ! or ? followed by a space and a capital letter or digit; the "." in
  // "a.m." is not an end because what follows it is lower case or another sentence's capital.
  return spoken
    .split(/(?<=[.!?])\s+(?=[A-Z0-9])/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

/** Where this browser remembers a voice the listener chose themselves. */
export const VOICE_CHOICE_KEY = 'careplus.voice.v1';

/**
 * A remembered choice is a browser voice's name, or one of the Care+ server's Kokoro voices
 * written as "kokoro:af_bella", so the two can share one list.
 */
const KOKORO_CHOICE = 'kokoro:';

export function kokoroChoice(voice: string): string {
  return `${KOKORO_CHOICE}${voice}`;
}

/** The Kokoro voice a choice names, or null when it names a browser voice (or nothing). */
export function kokoroVoiceOf(choice: string | null): string | null {
  return choice?.startsWith(KOKORO_CHOICE) ? choice.slice(KOKORO_CHOICE.length) : null;
}

/** Whether a choice asks for the browser's own speech rather than Kokoro. */
export function choosesBrowser(choice: string | null): boolean {
  return choice !== null && kokoroVoiceOf(choice) === null;
}

/** The device's own English voices, best first: what "Choose a voice" lists (never online ones). */
export function englishVoices<T extends VoiceLike>(voices: readonly T[]): T[] {
  return voices
    .filter((voice) => isOnDeviceVoice(voice) && voice.lang.toLowerCase().startsWith('en'))
    .sort((a, b) => voiceScore(b) - voiceScore(a));
}

/**
 * The voice to read with: the listener's own choice while the device still has it, else the best,
 * else any English voice the device has. Only ever an on-device voice: null means the device has
 * none, and nothing is read aloud (the browser's default voice may be an online one).
 */
export function chooseVoice<T extends VoiceLike>(
  voices: readonly T[],
  chosenName: string | null,
): T | null {
  const own = englishVoices(voices);
  const chosen = chosenName ? own.find((voice) => voice.name === chosenName) : undefined;
  return chosen ?? pickVoice(own) ?? own[0] ?? null;
}

/**
 * What the card says about the voice, once the browser has listed its voices: null when the device
 * has one to read with, else that it cannot read aloud here.
 */
export function voiceHint(voices: readonly VoiceLike[]): string | null {
  if (!voices.length || chooseVoice(voices, null)) return null;
  return NO_DEVICE_VOICE_HINT;
}
