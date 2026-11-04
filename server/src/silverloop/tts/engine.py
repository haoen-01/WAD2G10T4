"""Kokoro-82M on ONNX Runtime: the "Read my day" voice, on this server's CPU.

* **Optional.** `kokoro-onnx` is in the API's opt-in `tts` group (`uv sync --group tts`), and
  the model files are downloaded separately (`python -m silverloop.tts download`). Without
  either, `speak` raises `SpeechUnavailable` and the route answers 503; the browser then reads
  with its own voice.
* **Loaded once.** The model is built on first use (about 2 s), under a lock, and kept for the
  life of the process; `warm_up` can do that at start-up so the first reading does not wait.
* **One at a time, never queued for long.** Synthesis is serialised: ONNX Runtime already uses
  every core for one sentence, and two at once would only slow both. A request waits at most
  `tts_busy_wait_seconds` for its turn and then raises `SpeechBusy` (the route answers 503 and the
  browser reads on with its own voice), so a burst of sentences cannot tie up the server's worker
  threads. Checking whether Kokoro is available never waits on a sentence being spoken.
* **Cached, privately.** Each finished sentence is kept in memory, keyed by a SHA-256 of the
  model, voice, speed and words -- never the words themselves -- in a small LRU. Nothing is written
  to disk and nothing is logged, so a narration that has not changed is not made twice.
* **Local.** No network call is ever made here; nothing about the senior leaves the machine.
"""

from __future__ import annotations

import hashlib
import io
import logging
import threading
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any

from silverloop.config import Settings
from silverloop.tts.spoken import spoken_text

logger = logging.getLogger("silverloop.tts")

# server, so the default `models/kokoro` works from any working directory.
API_ROOT = Path(__file__).resolve().parents[3]
VOICES_FILE = "voices-v1.0.bin"
# About 25 MB of sentences: a day's narrations for many readers, and bounded.
CACHE_ENTRIES = 128
MAX_TEXT_CHARS = 500


class SpeechUnavailable(Exception):
    """Kokoro cannot speak here (not installed, no model files, or it failed). Says why."""


class SpeechBusy(SpeechUnavailable):
    """Kokoro is speaking another sentence and this one waited its limit for a turn."""


# The `code` of the speech route's busy 503: the browser asks for that sentence again in a moment
# rather than switching to its own voice (`client/src/lib/read-aloud.ts`, `SPEECH_BUSY_CODE`).
SPEECH_BUSY_CODE = "speech_busy"


def model_dir(settings: Settings) -> Path:
    path = Path(settings.tts_model_dir)
    return path if path.is_absolute() else API_ROOT / path


class _Engine:
    def __init__(self) -> None:
        # Speaking one sentence at a time; loading the model; the cache. Taken in that order only.
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._kokoro: Any = None
        self._loaded_from: tuple[str, str] | None = None
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    def _load(self, settings: Settings) -> Any:
        with self._load_lock:
            return self._load_locked(settings)

    def _load_locked(self, settings: Settings) -> Any:
        directory = model_dir(settings)
        model, voices = directory / settings.tts_model_file, directory / VOICES_FILE
        key = (str(model), str(voices))
        if self._kokoro is not None and self._loaded_from == key:
            return self._kokoro
        try:
            from kokoro_onnx import Kokoro
        except ImportError as error:
            raise SpeechUnavailable(
                "kokoro-onnx is not installed. Run `uv --directory server sync --group tts`."
            ) from error
        if not model.is_file() or not voices.is_file():
            raise SpeechUnavailable(
                "Kokoro model files are missing. Run "
                "`uv --directory server run python -m silverloop.tts download`."
            )
        # The phonemizer warns "words count mismatch" on most sentences with punctuation; it is
        # harmless, and would otherwise fill the API log on every reading.
        logging.getLogger("phonemizer").setLevel(logging.ERROR)
        try:
            self._kokoro = Kokoro(str(model), str(voices))
        except Exception as error:  # noqa: BLE001 - a broken model must degrade, not crash
            raise SpeechUnavailable(f"Kokoro could not load: {type(error).__name__}.") from error
        self._loaded_from = key
        logger.info("tts_model_loaded", extra={"structured_fields": {"model": model.name}})
        return self._kokoro

    def available(self, settings: Settings) -> str | None:
        """None when Kokoro can speak, else why not. Loads the model if it can."""
        if not settings.tts_enabled:
            return "TTS_ENABLED is false."
        try:
            # The model's own lock only: never waits behind a sentence being spoken.
            self._load(settings)
        except SpeechUnavailable as error:
            return str(error)
        return None

    def speak(self, text: str, settings: Settings, voice: str | None = None) -> bytes:
        """`text` spoken by Kokoro in `voice` (the configured voice when None), as a 16-bit mono
        WAV. Raises `SpeechUnavailable`."""
        if not settings.tts_enabled:
            raise SpeechUnavailable("TTS_ENABLED is false.")
        voice = voice or settings.tts_voice
        said = spoken_text(text)[:MAX_TEXT_CHARS]
        key = hashlib.sha256(
            "\x1f".join(
                [settings.tts_model_file, voice, f"{settings.tts_speed:.3f}", said]
            ).encode()
        ).hexdigest()
        if (cached := self._cached(key)) is not None:
            return cached
        if not self._lock.acquire(timeout=max(0.0, settings.tts_busy_wait_seconds)):
            raise SpeechBusy("The Kokoro voice is busy. Try again in a moment.")
        try:
            # Another request may have made this very sentence while this one waited.
            if (cached := self._cached(key)) is not None:
                return cached
            kokoro = self._load(settings)
            language = "en-gb" if voice.startswith("b") else "en-us"
            try:
                samples, rate = kokoro.create(
                    said, voice=voice, speed=settings.tts_speed, lang=language
                )
            except Exception as error:  # noqa: BLE001 - a failed sentence degrades to the browser
                raise SpeechUnavailable(
                    f"Kokoro could not speak: {type(error).__name__}."
                ) from error
            audio = _wav(samples, rate)
            with self._cache_lock:
                self._cache[key] = audio
                while len(self._cache) > CACHE_ENTRIES:
                    self._cache.popitem(last=False)
            return audio
        finally:
            self._lock.release()

    def _cached(self, key: str) -> bytes | None:
        with self._cache_lock:
            if (cached := self._cache.get(key)) is not None:
                self._cache.move_to_end(key)
            return cached


def _wav(samples: Any, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(int(rate))
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


_ENGINE = _Engine()


def speak(text: str, settings: Settings, voice: str | None = None) -> bytes:
    return _ENGINE.speak(text, settings, voice)


def unavailable_reason(settings: Settings) -> str | None:
    return _ENGINE.available(settings)


# The Kokoro voices "Choose a voice" offers, best first, as the card names them: a few clearly
# different ones, so the choice stays easy. All are in the v1.0 voices file; Heart and Bella are
# Kokoro's best-graded. A request may only name one of these.
VOICES: dict[str, str] = {
    "af_heart": "Heart",
    "af_bella": "Bella",
    "bf_emma": "Emma (British)",
    "am_michael": "Michael (male)",
}


def voice_label(voice: str) -> str:
    """The voice as the card names it: "Heart · Kokoro natural voice"."""
    name = VOICES.get(voice, voice.split("_")[-1].capitalize())
    return f"{name} · Kokoro natural voice"


def warm_up(settings: Settings) -> None:
    """Load the model in the background at start-up, so the first reading does not wait."""
    if not settings.tts_enabled:
        return

    def load() -> None:
        reason = _ENGINE.available(settings)
        if reason:
            logger.info("tts_unavailable", extra={"structured_fields": {"reason": reason}})

    threading.Thread(target=load, name="kokoro-warm-up", daemon=True).start()
