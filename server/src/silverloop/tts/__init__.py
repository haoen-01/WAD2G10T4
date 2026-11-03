"""The "Read my day" voice: Kokoro-82M, run locally on the CPU (see `engine.py`)."""

from silverloop.tts.engine import (
    SpeechUnavailable,
    speak,
    unavailable_reason,
    voice_label,
    warm_up,
)
from silverloop.tts.spoken import spoken_text

__all__ = [
    "SpeechUnavailable",
    "speak",
    "spoken_text",
    "unavailable_reason",
    "voice_label",
    "warm_up",
]
