"""Kokoro-82M on ONNX Runtime: the "Read my day" voice, on this server's CPU.

* **Optional.** `kokoro-onnx` is in the API's default `tts` group (`uv sync`), and the model files
  are downloaded separately (`python -m silverloop.tts download`). Without either, `speak` raises
  `SpeechUnavailable` and the route answers 503; the browser then reads with its own voice.
* **Loaded once.** The model is built on first use (about 2 s), under a lock, and kept for the
  life of the process; `warm_up` can do that at start-up so the first reading does not wait.
* **One at a time.** Synthesis is serialised: ONNX Runtime already uses every core for one
  sentence, and two at once would only slow both.
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


def model_dir(settings: Settings) -> Path:
    path = Path(settings.tts_model_dir)
    return path if path.is_absolute() else API_ROOT / path


class _Engine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kokoro: Any = None
        self._loaded_from: tuple[str, str] | None = None
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    def _load(self, settings: Settings) -> Any:
        directory = model_dir(settings)
        model, voices = directory / settings.tts_model_file, directory / VOICES_FILE
        key = (str(model), str(voices))
        if self._kokoro is not None and self._loaded_from == key:
            return self._kokoro
        try:
            from kokoro_onnx import Kokoro
        except ImportError as error:
            raise SpeechUnavailable(
                "kokoro-onnx is not installed. Run `uv sync` in server/."
            ) from error
        if not model.is_file() or not voices.is_file():
            raise SpeechUnavailable(
                "Kokoro model files are missing. Run `uv run python -m silverloop.tts download` "
                "in server/."
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
            with self._lock:
                self._load(settings)
        except SpeechUnavailable as error:
            return str(error)
        return None

    def speak(self, text: str, settings: Settings) -> bytes:
        """`text` spoken by Kokoro, as a 16-bit mono WAV. Raises `SpeechUnavailable`."""
        if not settings.tts_enabled:
            raise SpeechUnavailable("TTS_ENABLED is false.")
        said = spoken_text(text)[:MAX_TEXT_CHARS]
        key = hashlib.sha256(
            "\x1f".join(
                [settings.tts_model_file, settings.tts_voice, f"{settings.tts_speed:.3f}", said]
            ).encode()
        ).hexdigest()
        with self._lock:
            if (cached := self._cache.get(key)) is not None:
                self._cache.move_to_end(key)
                return cached
            kokoro = self._load(settings)
            language = "en-gb" if settings.tts_voice.startswith("b") else "en-us"
            try:
                samples, rate = kokoro.create(
                    said, voice=settings.tts_voice, speed=settings.tts_speed, lang=language
                )
            except Exception as error:  # noqa: BLE001 - a failed sentence degrades to the browser
                raise SpeechUnavailable(
                    f"Kokoro could not speak: {type(error).__name__}."
                ) from error
            audio = _wav(samples, rate)
            self._cache[key] = audio
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
            return audio


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


def speak(text: str, settings: Settings) -> bytes:
    return _ENGINE.speak(text, settings)


def unavailable_reason(settings: Settings) -> str | None:
    return _ENGINE.available(settings)


_VOICE_NAMES = {"af_heart": "Heart", "af_bella": "Bella", "bf_emma": "Emma"}


def voice_label(voice: str) -> str:
    """The voice as the card names it: "Heart · Kokoro natural voice"."""
    name = _VOICE_NAMES.get(voice, voice.split("_")[-1].capitalize())
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
