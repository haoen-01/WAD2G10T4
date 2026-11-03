# The "Read my day" voice (Kokoro)

"Read my day" on the senior's Today tab is read aloud by **Kokoro-82M**, an open-weight
text-to-speech model, using the warm American English female voice **`af_heart`**. It runs on the
API server's own CPU through ONNX Runtime. There is no cloud service, no key and no usage limit,
and nothing about the senior leaves the machine.

If Kokoro is not set up, or fails, the card reads with the browser's own speech instead (the best
natural female voice the browser has, e.g. Luna in Edge). The card's small **"Voice: …"** line
always shows which one is speaking.

## Set it up (once, after pulling)

```bash
cd apps/api
uv sync                                     # installs kokoro-onnx, onnxruntime, phonemizer (in the default `tts` group)
uv run python -m silverloop.tts download    # the model and voices, about 350 MB, checksum-verified
uv run python -m silverloop.tts check       # speaks a sample and writes models/kokoro/check.wav
```

Then restart `pnpm dev`. The card should show **"Voice: Heart · Kokoro natural voice"**.

- The model files go to `apps/api/models/kokoro/`, which git ignores. Never commit them.
- No system packages are needed. espeak-ng (used for pronunciation) comes inside the
  `espeakng-loader` wheel, which has wheels for Windows, macOS and Linux.
- If you work in OneDrive and `uv sync` fails with "Access is denied" on a `…dist-info` folder,
  something (OneDrive, or the editor's Python extension) is holding it. Close the editor's Python
  terminal or pause OneDrive, then run `uv sync` again.

## How it works

| Part                                                                                                                                                        | Where                                      |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Model, loaded once per server, warmed in the background at start-up                                                                                         | `apps/api/src/silverloop/tts/engine.py`    |
| How times, dates and titles are said ("10:30 am" becomes "ten thirty in the morning", "Mdm" becomes "Madam")                                                | `apps/api/src/silverloop/tts/spoken.py`    |
| Setup commands (`download`, `check`)                                                                                                                        | `apps/api/src/silverloop/tts/__main__.py`  |
| `GET /v1/people/{id}/my-day/voice` (is Kokoro here?) and `POST /v1/people/{id}/my-day/speech` (one sentence, returned as WAV; 503 when Kokoro cannot speak) | `apps/api/src/silverloop/family_routes.py` |
| Playback: one sentence at a time, the next made while this one plays; Pause, Resume and Stop; falls back to browser speech                                  | `apps/web/src/composables/useReadAloud.ts` |

- **Who can use it:** the same readers as `my-day` (the senior, and their family group).
- **Caching:** each spoken sentence is cached in memory, keyed by a SHA-256 of the model, voice,
  speed and words, never the words themselves. At most 128 sentences are kept. Nothing is written
  to disk and nothing is logged, so an unchanged narration is not made twice.
- **Speed** (16-core laptop CPU): the model loads in about 2 s. The first sentence is ready in
  about 1.3 s, and the rest are made faster than they are spoken.

## Settings (`.env`, all optional)

```bash
TTS_ENABLED=true            # false: always use the browser's voice
TTS_VOICE=af_heart          # also tried: af_bella (similar, slightly brighter), bf_emma (British; flatter, faster)
TTS_SPEED=0.92              # a little slower than Kokoro's default
TTS_MODEL_DIR=models/kokoro # relative to apps/api
TTS_MODEL_FILE=kokoro-v1.0.onnx  # or kokoro-v1.0.int8.onnx (92 MB; not faster on our CPU tests)
```

The e2e run sets `TTS_ENABLED=false`. `read-my-day.spec.ts` stands in for the two routes itself,
so CI never needs the model.
