import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import { isSpeechBusy, noReadingVoice, sentenceFetcher } from '@/lib/read-aloud';
import {
  SENTENCE_PAUSE_MS,
  SPEECH_PITCH,
  SPEECH_RATE,
  NO_DEVICE_VOICE_HINT,
  VOICE_CHOICE_KEY,
  chooseVoice,
  choosesBrowser,
  englishVoices,
  isOnDeviceVoice,
  kokoroChoice,
  kokoroVoiceOf,
  speechChunks,
  voiceHint,
  voiceLabel,
} from '@/lib/speech';

export type ReadAloudState = 'idle' | 'speaking' | 'paused';
/** Who is speaking: the Kokoro voice on the Care+ server, or the browser's own speech. */
export type ReadAloudEngine = 'kokoro' | 'browser';

/** The Care+ server's natural voices (Kokoro), when the caller can reach them. */
export interface ServerVoice {
  status: () => Promise<{
    available: boolean;
    label: string | null;
    voice?: string | null;
    voices?: { voice: string; label: string }[];
  }>;
  /** One sentence in `voice` (null: the server's default voice). */
  audio: (sentence: string, voice: string | null) => Promise<Blob>;
}

/**
 * How long, from the moment the card appears, a reading may wait for the browser to list the
 * device's own voices (Chrome lists none until its first `voiceschanged`). After this, if there is
 * still no on-device voice, the card says it cannot read aloud here.
 */
const DEVICE_VOICE_WAIT_MS = 3000;
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
 * Resolves with the voice list once it holds an on-device voice, or once `waitMs` has passed, or
 * at once if it already does. Every `voiceschanged` re-reads the list, so a late voice is never
 * missed.
 */
function voicesOnDevice(waitMs: number): Promise<SpeechSynthesisVoice[]> {
  const synth = window.speechSynthesis;
  const hasOwnVoice = () => synth.getVoices().some(isOnDeviceVoice);
  if (hasOwnVoice() || waitMs <= 0) return Promise.resolve(synth.getVoices());
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer);
      synth.removeEventListener('voiceschanged', changed);
      resolve(synth.getVoices());
    };
    const changed = () => {
      if (hasOwnVoice()) done();
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
 * the browser's own speech in the warmest on-device voice there is (see `lib/speech.ts`). Online
 * browser voices (Edge's "Online (Natural)", Chrome's "Google …") are never used, so the script
 * never goes to Microsoft or Google; with no on-device voice, `hint` says it cannot read aloud.
 * A busy Kokoro (another sentence being spoken) is asked again, never dropped for it; `noVoice`
 * says, before any press, that neither voice can read here.
 */
export function useReadAloud(server?: ServerVoice) {
  const hasBrowserSpeech = typeof window !== 'undefined' && 'speechSynthesis' in window;
  // This browser has some way to speak (its own speech, or the server's voice to ask).
  const mayHaveVoice = hasBrowserSpeech || (typeof window !== 'undefined' && !!server);
  const state = ref<ReadAloudState>('idle');
  const engine = ref<ReadAloudEngine>('browser');
  /** The voice that is reading (or will read), in words for the card; its full name for tests. */
  const voiceName = ref<string | null>(null);
  const voiceText = ref<string | null>(null);
  /** "Choose a voice": the device's own English voices, best first (never online ones). */
  const voices = ref<{ name: string; label: string }[]>([]);
  /** "Choose a voice": the server's Kokoro voices, while Kokoro can speak ("kokoro:…" names). */
  const serverVoices = ref<{ name: string; label: string }[]>([]);
  /** Set when the device has no voice of its own, so nothing can be read aloud here. */
  const hint = ref<string | null>(null);
  // What is known so far about each way of reading aloud, for `noVoice`.
  const kokoroKnown = ref(!server);
  const kokoroReady = ref(false);
  const deviceKnown = ref(!hasBrowserSpeech);
  const deviceHasVoice = ref(false);
  /**
   * True once it is known that nothing can read aloud on this device: no Kokoro voice (none
   * offered, or it said it cannot speak) and the browser has listed its voices with none of its
   * own (or has no speech at all). False while either is still being found out. While true, `hint`
   * says why.
   */
  const noVoice = computed(
    () =>
      !mayHaveVoice ||
      noReadingVoice({
        kokoroKnown: kokoroKnown.value,
        kokoroReady: kokoroReady.value,
        deviceKnown: deviceKnown.value,
        deviceHasVoice: deviceHasVoice.value,
      }),
  );
  /** Whether the day can be read aloud here: `!noVoice` (true while that is still being found out). */
  const canSpeak = computed(() => !noVoice.value);
  /**
   * The listener's own pick, remembered here: a browser voice's name or a Kokoro voice
   * ("kokoro:af_bella"). Null means "the best available": Kokoro's default when it is there.
   */
  const chosenName = ref<string | null>(
    typeof window !== 'undefined' && (hasBrowserSpeech || server) ? readChoice() : null,
  );
  // Kokoro, as the server last described it: null until it answers, or once it has failed.
  let serverDefault: { voice: string | null; label: string | null } | null = null;
  // The Kokoro voice this reading asks for (null: the server's default).
  let kokoroVoice: string | null = null;

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
  let sentences: ReturnType<typeof sentenceFetcher<Blob>> | null = null;
  let playing = false;
  let url: string | null = null;

  function showBrowserVoice(chosen: SpeechSynthesisVoice | null) {
    voiceName.value = chosen?.name ?? null;
    voiceText.value = voiceLabel(chosen);
  }

  // Ask for the voices as soon as the card is on screen, and keep the list and the shown choice up
  // to date as the browser adds voices, so the first press rarely has to wait.
  const refreshShownVoice = () => {
    if (!hasBrowserSpeech) {
      if (noVoice.value) hint.value = NO_DEVICE_VOICE_HINT;
      return;
    }
    const all = window.speechSynthesis.getVoices();
    // The list stays current under Kokoro too, so a browser voice can still be chosen.
    voices.value = englishVoices(all).map((item) => ({ name: item.name, label: voiceLabel(item) }));
    if (all.some(isOnDeviceVoice)) {
      deviceHasVoice.value = true;
      deviceKnown.value = true;
    } else {
      deviceHasVoice.value = false;
    }
    if (engine.value !== 'browser') return;
    hint.value = noVoice.value ? NO_DEVICE_VOICE_HINT : voiceHint(all);
    if (state.value === 'idle') showBrowserVoice(chooseVoice(all, chosenName.value));
  };

  /**
   * Who reads next, from the listener's choice: Kokoro (in the chosen voice, else its default)
   * whenever it can speak and no browser voice was chosen; the browser's own speech otherwise.
   */
  function settleEngine() {
    if (serverDefault && !choosesBrowser(chosenName.value)) {
      const wanted = kokoroVoiceOf(chosenName.value);
      const chosen = serverVoices.value.find((item) => item.name === kokoroChoice(wanted ?? ''));
      engine.value = 'kokoro';
      kokoroVoice = chosen ? wanted : serverDefault.voice;
      voiceName.value = 'kokoro';
      voiceText.value = chosen?.label ?? serverDefault.label;
      hint.value = null;
      return;
    }
    engine.value = 'browser';
    refreshShownVoice();
  }

  /** The listener picks a voice (null: back to the best). Used from the next reading. */
  function setVoiceChoice(name: string | null) {
    chosenName.value = name;
    try {
      if (name) window.localStorage.setItem(VOICE_CHOICE_KEY, name);
      else window.localStorage.removeItem(VOICE_CHOICE_KEY);
    } catch {
      // storage blocked: the choice lasts until the page is closed
    }
    if (state.value === 'idle') settleEngine();
  }

  /** Kokoro failed: it is no longer offered, and this reading and every later one use the browser. */
  function useBrowser() {
    serverDefault = null;
    serverVoices.value = [];
    kokoroReady.value = false;
    kokoroKnown.value = true;
    engine.value = 'browser';
    refreshShownVoice();
  }

  // The wait for the device's voices counts from here: a few seconds after the card
  // appears, the browser has listed all it will, and a press speaks at once.
  let listeningSince = Date.now();
  let deviceWait: number | undefined;
  onMounted(() => {
    listeningSince = Date.now();
    if (hasBrowserSpeech) {
      refreshShownVoice();
      window.speechSynthesis.addEventListener('voiceschanged', refreshShownVoice);
      // By now the browser has listed every voice it will: with none of its own, it has none.
      deviceWait = window.setTimeout(() => {
        deviceWait = undefined;
        deviceKnown.value = true;
        refreshShownVoice();
      }, DEVICE_VOICE_WAIT_MS);
    } else {
      refreshShownVoice();
    }
    if (server) {
      server
        .status()
        .then((status) => {
          kokoroKnown.value = true;
          if (!status.available) {
            refreshShownVoice();
            return;
          }
          kokoroReady.value = true;
          serverDefault = { voice: status.voice ?? null, label: status.label };
          serverVoices.value = (status.voices ?? []).map((item) => ({
            name: kokoroChoice(item.voice),
            label: item.label,
          }));
          if (state.value === 'idle') settleEngine();
        })
        .catch(() => {
          // the browser's own voice it is
          kokoroKnown.value = true;
          refreshShownVoice();
        });
    }
  });
  onBeforeUnmount(() => {
    if (deviceWait !== undefined) window.clearTimeout(deviceWait);
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
    const waitMs = Math.max(0, DEVICE_VOICE_WAIT_MS - (Date.now() - listeningSince));
    voice = chooseVoice(await voicesOnDevice(waitMs), chosenName.value);
    if (run !== reading) return; // stopped while the voices were loading
    showBrowserVoice(voice);
    if (!voice) {
      // No on-device voice: never left to the browser's default, which may be an online one.
      hint.value = NO_DEVICE_VOICE_HINT;
      state.value = 'idle';
      return;
    }
    sayNext(run);
  }

  // ── Kokoro ───────────────────────────────────────────────────────────────────

  /**
   * Kokoro could not go on: the rest of this reading uses the browser. Only when it cannot speak
   * is it dropped for every later reading too; when it stayed busy, the next reading tries it again.
   */
  function fallBack(run: number, keepKokoro = false) {
    if (run !== reading) return;
    playing = false;
    releaseUrl();
    if (keepKokoro) {
      engine.value = 'browser';
      refreshShownVoice();
    } else {
      useBrowser();
    }
    void speakWithBrowser(run);
  }

  /**
   * A sentence could not be fetched or played. Pausing or stopping just as a sentence starts makes
   * the browser reject its `play()` with an AbortError: that is the listener's own doing, not a
   * failure, and the reading carries on from where it is. A busy Kokoro has already been asked
   * again (`lib/read-aloud.ts`); still busy, this reading goes on in the browser's voice, Kokoro
   * kept. Anything else means Kokoro cannot speak, and it is dropped.
   */
  function failed(run: number, error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    fallBack(run, isSpeechBusy(error));
  }

  function playSentence(run: number) {
    if (run !== reading || state.value !== 'speaking') return; // paused: `resume` goes on
    if (index >= chunks.length) {
      state.value = 'idle';
      return;
    }
    const at = index;
    // This sentence first (the server makes one at a time), then the next one while this plays.
    // A busy answer to either is asked for again when that sentence's turn comes.
    const current = sentences!.forTurn(at);
    if (at + 1 < chunks.length) sentences!.prefetch(at + 1);
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
    if (!canSpeak.value) return;
    stop();
    settleEngine(); // a voice chosen during the last reading applies from this one
    const run = ++reading;
    chunks = speechChunks(script);
    index = 0;
    state.value = 'speaking';
    if (engine.value === 'kokoro' && server) {
      audio ??= new Audio();
      const said = chunks;
      const voiceNow = kokoroVoice;
      sentences = sentenceFetcher((at) => server.audio(said[at], voiceNow), {
        stillWanted: () => run === reading,
      });
      playSentence(run);
      return;
    }
    await speakWithBrowser(run);
  }

  function pause() {
    if (!canSpeak.value || state.value !== 'speaking') return;
    state.value = 'paused';
    if (engine.value === 'kokoro') {
      audio?.pause();
      return;
    }
    // Mid-sentence: hold it where it is. Between sentences: the next one simply waits.
    window.speechSynthesis.pause();
  }

  function resume() {
    if (!canSpeak.value || state.value !== 'paused') return;
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
    noVoice,
    state,
    engine,
    voiceName,
    voiceText,
    voices,
    serverVoices,
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
