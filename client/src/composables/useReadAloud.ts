import { onBeforeUnmount, onMounted, ref } from 'vue';

import {
  SENTENCE_PAUSE_MS,
  SPEECH_PITCH,
  SPEECH_RATE,
  VOICE_CHOICE_KEY,
  chooseVoice,
  englishVoices,
  isPreferredVoice,
  lunaHint,
  speechChunks,
  voiceLabel,
} from '@/lib/speech';

export type ReadAloudState = 'idle' | 'speaking' | 'paused';
/** Who is speaking: the Kokoro voice on the Care+ server, or the browser's own speech. */
export type ReadAloudEngine = 'kokoro' | 'browser';

/** The Care+ server's natural voice (Kokoro), when the caller can reach it. */
export interface ServerVoice {
  status: () => Promise<{ available: boolean; label: string | null }>;
  audio: (sentence: string) => Promise<Blob>;
}

/**
 * How long, from the moment the card appears, a reading may wait for the preferred browser voice
 * (Luna). Edge lists its local voices (David, Mark, Zira) at once and adds its online "Natural"
 * ones a moment later; settling for the first good-enough voice would lock in a lesser one before
 * Luna arrives. After this, the best voice listed so far is used (Chrome never offers Luna).
 */
const PREFERRED_VOICE_WAIT_MS = 3000;
/** Kokoro's sentences already end in a natural breath; a shorter gap keeps the pace calm, not slow. */
const KOKORO_PAUSE_MS = 220;
/** A fraction of a second of silence: played straight from the press, so later sentences may play. */
const SILENCE =
  'data:audio/wav;base64,UklGRsQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

function readChoice(): string | null {
  try {
    return window.localStorage.getItem(VOICE_CHOICE_KEY);
  } catch {
    return null; // storage blocked: always the automatic choice
  }
}

/**
 * Resolves with the voice list once it holds the preferred voice, or once `waitMs` has passed, or
 * at once if it already does. Every `voiceschanged` re-reads the list, so a late voice is never
 * missed.
 */
function voicesWithPreferred(waitMs: number): Promise<SpeechSynthesisVoice[]> {
  const synth = window.speechSynthesis;
  const hasPreferred = () => synth.getVoices().some(isPreferredVoice);
  if (hasPreferred() || waitMs <= 0) return Promise.resolve(synth.getVoices());
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer);
      synth.removeEventListener('voiceschanged', changed);
      resolve(synth.getVoices());
    };
    const changed = () => {
      if (hasPreferred()) done();
    };
    const timer = window.setTimeout(done, waitMs);
    synth.addEventListener('voiceschanged', changed);
  });
}

/**
 * Reads a script aloud a sentence at a time, and lets the listener pause, resume or stop.
 *
 * With `server`, it first uses the Care+ server's natural Kokoro voice (no cloud service: Kokoro
 * runs on the Care+ server's own CPU). Without it, or whenever Kokoro cannot speak, it reads with
 * the browser's own speech in the warmest voice the browser has (see `lib/speech.ts`). The
 * browser's local voices stay on the device; Edge's "Online (Natural)" voices are spoken by
 * Microsoft's service, so with one of those the sentences go to Microsoft to be spoken.
 */
export function useReadAloud(server?: ServerVoice) {
  const hasBrowserSpeech = typeof window !== 'undefined' && 'speechSynthesis' in window;
  const canSpeak = hasBrowserSpeech || (typeof window !== 'undefined' && !!server);
  const state = ref<ReadAloudState>('idle');
  const engine = ref<ReadAloudEngine>('browser');
  /** The voice that is reading (or will read), in words for the card; its full name for tests. */
  const voiceName = ref<string | null>(null);
  const voiceText = ref<string | null>(null);
  /** "Choose a voice": the browser's English voices, best first, and why Luna is missing if it is. */
  const voices = ref<{ name: string; label: string }[]>([]);
  const hint = ref<string | null>(null);
  /** The listener's own pick of browser voice, remembered here; null means "the best available". */
  const chosenName = ref<string | null>(hasBrowserSpeech ? readChoice() : null);

  // Browser speech: chosen afresh for each reading (the browser may have added better voices since
  // the last), then kept for every sentence of that reading.
  let voice: SpeechSynthesisVoice | null = null;
  let chunks: string[] = [];
  let index = 0;
  let gap: number | undefined;
  // Each reading has its own number: cancelling one fires its `end` events late in some browsers,
  // and those must never move a newer reading on.
  let reading = 0;
  // Kokoro: one audio element for the whole reading, unlocked by the press itself.
  let audio: HTMLAudioElement | null = null;
  let sentenceAudio: Promise<Blob>[] = [];
  let playing = false;
  let url: string | null = null;

  function showBrowserVoice(chosen: SpeechSynthesisVoice | null) {
    voiceName.value = chosen?.name ?? null;
    voiceText.value = voiceLabel(chosen);
  }

  // Ask for the voices as soon as the card is on screen, and keep the list and the shown choice up
  // to date as the browser adds voices, so the first press rarely has to wait.
  const refreshShownVoice = () => {
    if (!hasBrowserSpeech || engine.value !== 'browser') return;
    const all = window.speechSynthesis.getVoices();
    voices.value = englishVoices(all).map((item) => ({ name: item.name, label: voiceLabel(item) }));
    hint.value = lunaHint(all, navigator.userAgent);
    if (state.value === 'idle') showBrowserVoice(chooseVoice(all, chosenName.value));
  };

  /** The listener picks a browser voice (null: back to the best). Used from the next reading. */
  function setVoiceChoice(name: string | null) {
    chosenName.value = name;
    try {
      if (name) window.localStorage.setItem(VOICE_CHOICE_KEY, name);
      else window.localStorage.removeItem(VOICE_CHOICE_KEY);
    } catch {
      // storage blocked: the choice lasts until the page is closed
    }
    refreshShownVoice();
  }

  function useBrowser() {
    engine.value = 'browser';
    refreshShownVoice();
  }

  // The wait for the preferred browser voice counts from here: a few seconds after the card
  // appears, the browser has listed all it will, and a press speaks at once.
  let listeningSince = Date.now();
  onMounted(() => {
    listeningSince = Date.now();
    if (hasBrowserSpeech) {
      refreshShownVoice();
      window.speechSynthesis.addEventListener('voiceschanged', refreshShownVoice);
    }
    if (server) {
      server
        .status()
        .then((status) => {
          if (!status.available) return;
          engine.value = 'kokoro';
          voiceName.value = 'kokoro';
          voiceText.value = status.label;
          hint.value = null;
        })
        .catch(() => undefined); // the browser's own voice it is
    }
  });
  onBeforeUnmount(() => {
    if (hasBrowserSpeech)
      window.speechSynthesis.removeEventListener('voiceschanged', refreshShownVoice);
  });

  function clearGap() {
    if (gap !== undefined) window.clearTimeout(gap);
    gap = undefined;
  }

  function releaseUrl() {
    if (url) URL.revokeObjectURL(url);
    url = null;
  }

  // ── Browser speech ──────────────────────────────────────────────────────────

  function sayNext(run: number) {
    if (run !== reading || state.value === 'idle') return;
    if (state.value === 'paused') return; // `resume` picks up from `index`
    if (index >= chunks.length) {
      state.value = 'idle';
      return;
    }
    const utterance = new SpeechSynthesisUtterance(chunks[index]);
    // The same voice for every sentence; never left to the browser between them.
    if (voice) {
      utterance.voice = voice;
      utterance.lang = voice.lang;
    }
    utterance.rate = SPEECH_RATE;
    utterance.pitch = SPEECH_PITCH;
    utterance.onend = () => {
      if (run !== reading) return;
      index += 1;
      clearGap();
      gap = window.setTimeout(() => sayNext(run), SENTENCE_PAUSE_MS);
    };
    utterance.onerror = (event) => {
      if (run !== reading) return;
      // `interrupted`/`canceled` are our own stop or pause; anything else ends the reading.
      if (event.error !== 'interrupted' && event.error !== 'canceled') stop();
    };
    window.speechSynthesis.speak(utterance);
  }

  async function speakWithBrowser(run: number) {
    if (!hasBrowserSpeech) {
      state.value = 'idle';
      return;
    }
    // A voice the listener chose needs no wait; the automatic choice waits a moment for Luna.
    const own =
      chosenName.value !== null &&
      window.speechSynthesis.getVoices().some((item) => item.name === chosenName.value);
    const waitMs = own ? 0 : Math.max(0, PREFERRED_VOICE_WAIT_MS - (Date.now() - listeningSince));
    voice = chooseVoice(await voicesWithPreferred(waitMs), chosenName.value);
    if (run !== reading) return; // stopped while the voices were loading
    showBrowserVoice(voice);
    sayNext(run);
  }

  // ── Kokoro ───────────────────────────────────────────────────────────────────

  function fetchSentence(at: number): Promise<Blob> {
    sentenceAudio[at] ??= server!.audio(chunks[at]);
    return sentenceAudio[at];
  }

  /** Kokoro could not go on: the rest of this reading, and every later one, uses the browser. */
  function fallBack(run: number) {
    if (run !== reading) return;
    playing = false;
    releaseUrl();
    useBrowser();
    void speakWithBrowser(run);
  }

  /**
   * A sentence could not be fetched or played. Pausing or stopping just as a sentence starts makes
   * the browser reject its `play()` with an AbortError: that is the listener's own doing, not a
   * failure, and the reading carries on from where it is. Anything else falls back to the browser.
   */
  function failed(run: number, error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    fallBack(run);
  }

  function playSentence(run: number) {
    if (run !== reading || state.value !== 'speaking') return; // paused: `resume` goes on
    if (index >= chunks.length) {
      state.value = 'idle';
      return;
    }
    const at = index;
    // This sentence first (the server makes one at a time), then the next one while this plays.
    const current = fetchSentence(at);
    if (at + 1 < chunks.length) void fetchSentence(at + 1).catch(() => undefined);
    current
      .then((blob) => {
        if (run !== reading || !audio) return;
        releaseUrl();
        url = URL.createObjectURL(blob);
        audio.src = url;
        audio.onended = () => {
          if (run !== reading) return;
          playing = false;
          index = at + 1;
          clearGap();
          gap = window.setTimeout(() => playSentence(run), KOKORO_PAUSE_MS);
        };
        playing = true;
        if (state.value === 'paused') return; // paused while it was being made: hold it ready
        return audio.play();
      })
      .catch((error: unknown) => failed(run, error));
  }

  /**
   * Call straight from the press, before anything is awaited: some browsers (Safari above all)
   * only let audio start in direct answer to a tap, and the day takes a few seconds to arrive.
   */
  function prime() {
    if (engine.value !== 'kokoro') return;
    audio ??= new Audio();
    audio.src = SILENCE;
    void audio.play().catch(() => undefined);
  }

  // ── Both ─────────────────────────────────────────────────────────────────────

  async function speak(script: string) {
    if (!canSpeak) return;
    stop();
    const run = ++reading;
    chunks = speechChunks(script);
    index = 0;
    state.value = 'speaking';
    if (engine.value === 'kokoro' && server) {
      audio ??= new Audio();
      sentenceAudio = [];
      playSentence(run);
      return;
    }
    await speakWithBrowser(run);
  }

  function pause() {
    if (!canSpeak || state.value !== 'speaking') return;
    state.value = 'paused';
    if (engine.value === 'kokoro') {
      audio?.pause();
      return;
    }
    // Mid-sentence: hold it where it is. Between sentences: the next one simply waits.
    window.speechSynthesis.pause();
  }

  function resume() {
    if (!canSpeak || state.value !== 'paused') return;
    state.value = 'speaking';
    if (engine.value === 'kokoro') {
      // Mid-sentence (or one made while paused): play on. Between sentences: the next one.
      if (playing && audio) void audio.play().catch((error: unknown) => failed(reading, error));
      else {
        clearGap();
        playSentence(reading);
      }
      return;
    }
    if (window.speechSynthesis.paused || window.speechSynthesis.speaking) {
      window.speechSynthesis.resume();
    }
    // Paused between sentences (nothing was being said): go on with the next one.
    if (!window.speechSynthesis.speaking) {
      clearGap();
      sayNext(reading);
    }
  }

  function stop() {
    reading += 1;
    clearGap();
    state.value = 'idle';
    playing = false;
    if (audio) {
      audio.onended = null;
      audio.pause();
    }
    releaseUrl();
    if (!hasBrowserSpeech) return;
    // Chrome will not cancel while paused; resume first so nothing is left hanging.
    if (window.speechSynthesis.paused) window.speechSynthesis.resume();
    window.speechSynthesis.cancel();
  }

  onBeforeUnmount(stop);

  return {
    canSpeak,
    state,
    engine,
    voiceName,
    voiceText,
    voices,
    hint,
    chosenName,
    setVoiceChoice,
    prime,
    speak,
    pause,
    resume,
    stop,
  };
}
