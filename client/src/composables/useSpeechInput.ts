import { onBeforeUnmount, ref } from 'vue';

/**
 * Voice typing for the assistant, with the browser's own speech recognition (the Web Speech API).
 * The words land in the message box as they are heard; nothing is sent until Send is pressed.
 *
 * Where the voice goes: in Chrome, Edge and Safari the browser sends the recording to its maker
 * (Google or Apple) to turn it into text. So the microphone only listens after a tap, and the
 * first time it says so and asks first (`VOICE_NOTICE_KEY` remembers the answer in this browser).
 */

export const VOICE_NOTICE_KEY = 'careplus.assistant.voice.v1';

/** The parts of the Web Speech API used here (not in every TypeScript DOM library). */
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionResultEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
interface RecognitionResultEvent {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function noticeAccepted(): boolean {
  try {
    return window.localStorage.getItem(VOICE_NOTICE_KEY) === 'yes';
  } catch {
    return false;
  }
}

export function acceptNotice(): void {
  try {
    window.localStorage.setItem(VOICE_NOTICE_KEY, 'yes');
  } catch {
    // Storage blocked: asked again next time.
  }
}

/** Plain words for what went wrong. */
export function voiceErrorWords(code: string): string {
  if (code === 'not-allowed' || code === 'service-not-allowed') {
    return 'The microphone is blocked. Allow it in the browser’s settings to use voice typing.';
  }
  if (code === 'no-speech') return "I didn't hear anything. Tap the microphone and try again.";
  if (code === 'audio-capture') return "I can't find a microphone on this device.";
  if (code === 'network') return 'Voice typing needs an internet connection.';
  return 'Voice typing stopped. You can try again, or type instead.';
}

export function useSpeechInput(lang = 'en-SG') {
  const Ctor = recognitionCtor();
  const supported = Ctor !== null;
  const listening = ref(false);
  const error = ref<string | null>(null);
  let recognition: Recognition | null = null;

  /**
   * Listens once, calling `onWords(heard)` with everything heard so far each time it changes
   * (the not-yet-final words included, so they appear as they are spoken).
   */
  function start(onWords: (heard: string) => void) {
    if (!Ctor || listening.value) return;
    error.value = null;
    const r = new Ctor();
    r.lang = lang;
    r.interimResults = true;
    r.continuous = false;
    r.maxAlternatives = 1;
    let finals = '';
    r.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finals += result[0].transcript;
        else interim += result[0].transcript;
      }
      onWords(`${finals}${interim}`.replace(/\s+/g, ' ').trim());
    };
    r.onerror = (event) => {
      if (event.error !== 'aborted') error.value = voiceErrorWords(event.error);
    };
    r.onend = () => {
      listening.value = false;
      recognition = null;
    };
    recognition = r;
    listening.value = true;
    try {
      r.start();
    } catch {
      listening.value = false;
      recognition = null;
      error.value = voiceErrorWords('unknown');
    }
  }

  function stop() {
    recognition?.stop();
  }

  /** Stops at once and drops anything still on its way (used when the message is sent). */
  function cancel() {
    if (!recognition) return;
    recognition.onresult = null;
    recognition.abort();
  }

  onBeforeUnmount(() => recognition?.abort());

  return { supported, listening, error, start, stop, cancel };
}
