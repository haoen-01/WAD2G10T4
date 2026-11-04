# The "Read my day" voice (Kokoro)

"Read my day" on the senior's Today tab is read aloud by **Kokoro-82M**, an open-weight
text-to-speech model, using the warm American English female voice **`af_heart`**. It runs on the
API server's own CPU through ONNX Runtime. There is no cloud service, no key and no usage limit,
and nothing about the senior leaves the machine.

If Kokoro is not set up, or fails, the card reads with the browser's own speech instead, using
**only voices the device speaks itself** (`SpeechSynthesisVoice.localService === true`): the
warmest on-device English voice there is (for example Samantha on a Mac or iPhone, Zira on
Windows). A browser's online voices are never used, chosen automatically or offered in "Choose a
voice": Edge's "Online (Natural)" voices (Luna, Aria) and Chrome's "Google …" voices are spoken by
Microsoft's or Google's servers, so using one would send the senior's day (their name, the
appointment titles, who is going) to them. If the device has no voice of its own, the card says it
cannot read the day aloud here rather than falling back to an online voice. The card's small
**"Voice: …"** line always shows which one is speaking.

## Set it up (once, after pulling)

Kokoro is opt-in: its packages are in the API's `tts` dependency group, which a plain `uv sync`
(and CI) does not install. From the repository root:

```bash
uv --directory server sync --group tts                       # installs kokoro-onnx, onnxruntime, phonemizer
uv --directory server run python -m silverloop.tts download  # the model and voices, about 350 MB, checksum-verified
uv --directory server run python -m silverloop.tts check     # speaks a sample and writes models/kokoro/check.wav
```

A later plain `uv sync` removes the `tts` packages again; keep passing `--group tts` (or use
`uv sync --inexact`) on a machine that should keep the voice.

Then restart `pnpm dev`. The card should show **"Voice: Heart · Kokoro natural voice"**.

- The model files go to `server/models/kokoro/`, which git ignores. Never commit them.
- No system packages are needed. espeak-ng (used for pronunciation) comes inside the
  `espeakng-loader` wheel, which has wheels for Windows, macOS and Linux.
- If you work in OneDrive and `uv sync --group tts` fails with "Access is denied" on a `…dist-info` folder,
  something (OneDrive, or the editor's Python extension) is holding it. Close the editor's Python
  terminal or pause OneDrive, then run it again.

## How it works

| Part                                                                                                                                                        | Where                                    |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Model, loaded once per server, warmed in the background at start-up                                                                                         | `server/src/silverloop/tts/engine.py`    |
| How times, dates and titles are said ("10:30 am" becomes "ten thirty in the morning", "Mdm" becomes "Madam")                                                | `server/src/silverloop/tts/spoken.py`    |
| Setup commands (`download`, `check`)                                                                                                                        | `server/src/silverloop/tts/__main__.py`  |
| `GET /v1/people/{id}/my-day/voice` (is Kokoro here?) and `POST /v1/people/{id}/my-day/speech` (one sentence, returned as WAV; 503 when Kokoro cannot speak) | `server/src/silverloop/family_routes.py` |
| Playback: one sentence at a time, the next made while this one plays; Pause, Resume and Stop; falls back to browser speech                                  | `client/src/composables/useReadAloud.ts` |
| Which browser voice: on-device voices only, the warmest first; none means "cannot read aloud here"                                                          | `client/src/lib/speech.ts`               |

- **Who can use it:** the same readers as `my-day` (the senior, and their family group).
- **Caching:** each spoken sentence is cached in memory, keyed by a SHA-256 of the model, voice,
  speed and words, never the words themselves. At most 128 sentences are kept. Nothing is written
  to disk and nothing is logged, so an unchanged narration is not made twice.
- **Fair use:** one sentence is spoken at a time. A sentence waits at most
  `TTS_BUSY_WAIT_SECONDS` (3 s) for its turn, then the route answers 503 (busy) and the browser
  reads on with its own on-device voice. One person may have `TTS_RATE_PER_10_MIN` (240) sentences
  spoken in 10 minutes; past that the route answers 429. Asking whether Kokoro is available never
  waits on a sentence being spoken.
- **Speed** (16-core laptop CPU): the model loads in about 2 s. The first sentence is ready in
  about 1.3 s, and the rest are made faster than they are spoken.

## Settings (`.env`, all optional)

```bash
TTS_ENABLED=true            # false: always use the browser's voice
TTS_VOICE=af_heart          # also tried: af_bella (similar, slightly brighter), bf_emma (British; flatter, faster)
TTS_SPEED=0.92              # a little slower than Kokoro's default
TTS_MODEL_DIR=models/kokoro # relative to server
TTS_MODEL_FILE=kokoro-v1.0.onnx  # or kokoro-v1.0.int8.onnx (92 MB; not faster on our CPU tests)
TTS_RATE_PER_10_MIN=240     # sentences one person may have spoken in 10 minutes (then 429)
TTS_BUSY_WAIT_SECONDS=3     # how long a sentence waits for another to finish (then 503, busy)
```

The e2e run sets `TTS_ENABLED=false`. `read-my-day.spec.ts` stands in for the two routes itself,
so CI never needs the model. CI installs only the default groups, so the API tests run without
Kokoro: the speech route answers 503 there, and the tests that need the model files skip.
