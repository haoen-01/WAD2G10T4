"""The "Read my day" voice: how words are said, the Kokoro engine, and its route."""

from __future__ import annotations

import importlib.util
import io
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.tts import engine as tts_engine
from silverloop.tts.engine import SpeechUnavailable, _Engine, model_dir
from silverloop.tts.spoken import spoken_text, time_words
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _onboard,
    client,  # noqa: F401 - pytest fixture
    repo,  # noqa: F401 - pytest fixture
)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"_env_file": None, "database_url": "sqlite+pysqlite:///:memory:"}
    base.update(overrides)
    return Settings(**base)


# ── How words are said ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("Your eye check-up is at 10:30 am.", "Your eye check-up is at ten thirty in the morning."),
        ("Light stretching at 5 pm.", "Light stretching at five in the afternoon."),
        ("Tomorrow starts at 10am.", "Tomorrow starts at ten in the morning."),
        ("Light stretching at 17:00.", "Light stretching at five in the afternoon."),
        ("Lunch at 12 pm.", "Lunch at twelve noon."),
        ("Dinner at 7:05 p.m.", "Dinner at seven oh five in the evening."),
        ("Tea at 9.45 a.m.", "Tea at nine forty-five in the morning."),
        ("Good morning, Mdm Lim.", "Good morning, Madam Lim."),
        ("Mr Tan and Dr. Ong", "Mister Tan and Doctor Ong"),
        ("Physio on 2026-11-05.", "Physio on Thursday the fifth of November."),
        ("Eye check-up on Wed 04 Nov.", "Eye check-up on Wednesday the fourth of November."),
        ("Due 21st Dec", "Due the twenty-first of December"),
        ("You have 2 reminders still to do.", "You have 2 reminders still to do."),
    ],
)
def test_times_dates_and_titles_are_said_the_way_people_say_them(written: str, said: str) -> None:
    assert spoken_text(written) == said


def test_time_words_cover_the_whole_day() -> None:
    assert time_words(0, 0) == "midnight"
    assert time_words(8, 0) == "eight in the morning"
    assert time_words(13, 15) == "one fifteen in the afternoon"
    assert time_words(18, 30) == "six thirty in the evening"


# ── The engine ────────────────────────────────────────────────────────────────────────────────


class _FakeKokoro:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create(self, text: str, **_: Any) -> tuple[np.ndarray, int]:
        self.calls.append(text)
        return np.zeros(2400, dtype=np.float32), 24000


# Kokoro is the opt-in `tts` dependency group: CI (`uv sync --frozen`) runs without it.
_KOKORO_INSTALLED = importlib.util.find_spec("kokoro_onnx") is not None


def test_without_the_model_files_it_says_how_to_get_them(tmp_path: Path) -> None:
    # Without the package the first thing to get is the `tts` group; with it, the model files.
    needed = r"sync --group tts" if not _KOKORO_INSTALLED else r"silverloop\.tts download"
    with pytest.raises(SpeechUnavailable, match=needed):
        _Engine().speak("Hello.", _settings(tts_model_dir=str(tmp_path)))
    with pytest.raises(SpeechUnavailable, match="TTS_ENABLED"):
        _Engine().speak("Hello.", _settings(tts_enabled=False))


@pytest.mark.skipif(_KOKORO_INSTALLED, reason="Kokoro is installed here (the `tts` group).")
def test_without_kokoro_the_voice_is_unavailable_and_the_route_answers_503(
    client: TestClient,  # noqa: F811
) -> None:
    assert "--group tts" in (tts_engine.unavailable_reason(_settings()) or "")
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    voice = client.get(f"/v1/people/{person_id}/my-day/voice", headers=_headers("senior-1"))
    assert voice.json()["available"] is False
    assert _speech(client, person_id, "senior-1").status_code == 503


def test_the_model_loads_once_and_a_repeated_sentence_is_not_made_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeKokoro()
    loads: list[int] = []
    engine = _Engine()

    def load(_settings: Settings) -> _FakeKokoro:
        loads.append(1)
        return fake

    monkeypatch.setattr(engine, "_load", load)
    settings = _settings()
    first = engine.speak("Your eye check-up is at 10:30 am.", settings)
    again = engine.speak("Your eye check-up is at 10:30 am.", settings)
    engine.speak("Light stretching at 5 pm.", settings)
    assert first == again
    # Kokoro is given the spoken words, not the written ones.
    assert fake.calls == [
        "Your eye check-up is at ten thirty in the morning.",
        "Light stretching at five in the afternoon.",
    ]
    assert len(loads) == 2  # looked up per sentence made, never per cached one
    # The cache keeps hashes of what was said, never the words.
    assert all(len(key) == 64 and "check-up" not in key for key in engine._cache)
    with wave.open(io.BytesIO(first)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24000)


def test_the_cache_stays_small(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _Engine()
    monkeypatch.setattr(engine, "_load", lambda _settings: _FakeKokoro())
    for number in range(tts_engine.CACHE_ENTRIES + 10):
        engine.speak(f"Sentence number {number}.", _settings())
    assert len(engine._cache) == tts_engine.CACHE_ENTRIES


_MODELS = model_dir(Settings(_env_file=None))


@pytest.mark.skipif(
    not _KOKORO_INSTALLED or not (_MODELS / "kokoro-v1.0.onnx").is_file(),
    reason="Kokoro (the `tts` group) or its model files are not installed here.",
)
def test_kokoro_really_speaks_with_the_heart_voice() -> None:
    audio = _Engine().speak("Good morning, Mdm Lim. Your eye check-up is at 10:30 am.", _settings())
    with wave.open(io.BytesIO(audio)) as spoken:
        seconds = spoken.getnframes() / spoken.getframerate()
    assert 2.0 < seconds < 12.0


# ── The route ─────────────────────────────────────────────────────────────────────────────────


def _speech(client: TestClient, person_id: str, sub: str, text: str = "Hello."):  # noqa: F811
    return client.post(
        f"/v1/people/{person_id}/my-day/speech", json={"text": text}, headers=_headers(sub)
    )


def test_the_route_returns_audio_for_the_seniors_readers(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "silverloop.family_routes.speak",
        lambda text, settings, voice=None: b"RIFF-fake-" + text.encode(),
    )
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    response = _speech(client, person_id, "senior-1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"].startswith("private")
    assert _speech(client, person_id, "family-a").status_code == 200
    _onboard(client, "family-z", "family", "Stranger")
    assert _speech(client, person_id, "family-z").status_code == 404
    assert _speech(client, person_id, "senior-1", "x" * 501).status_code == 422


def test_the_route_answers_503_when_kokoro_cannot_speak(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(text: str, settings: Settings, voice: str | None = None) -> bytes:
        raise SpeechUnavailable("Kokoro model files are missing.")

    monkeypatch.setattr("silverloop.family_routes.speak", unavailable)
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    response = _speech(client, person_id, "senior-1")
    assert response.status_code == 503
    assert "model files" in response.json()["detail"]


def test_settings_default_to_the_heart_voice() -> None:
    settings = Settings(_env_file=None)
    assert (settings.tts_voice, settings.tts_speed) == ("af_heart", 0.92)
    assert SimpleNamespace(dir=model_dir(settings)).dir.name == "kokoro"


def test_the_voice_route_says_whether_kokoro_can_speak(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    url = f"/v1/people/{person_id}/my-day/voice"
    monkeypatch.setattr("silverloop.family_routes.unavailable_reason", lambda settings: None)
    body = client.get(url, headers=_headers("senior-1")).json()
    assert (body["available"], body["voice"], body["label"]) == (
        True,
        "af_heart",
        "Heart · Kokoro natural voice",
    )
    # Every voice on offer, by its friendly name, the default first.
    assert body["voices"][0] == {"voice": "af_heart", "label": "Heart · Kokoro natural voice"}
    assert {"voice": "bf_emma", "label": "Emma (British) · Kokoro natural voice"} in body["voices"]
    monkeypatch.setattr(
        "silverloop.family_routes.unavailable_reason", lambda settings: "model files are missing"
    )
    body = client.get(url, headers=_headers("senior-1")).json()
    assert body == {"available": False, "voice": None, "label": None, "voices": []}
    _onboard(client, "family-z", "family", "Stranger")
    assert client.get(url, headers=_headers("family-z")).status_code == 404


def test_a_chosen_voice_is_spoken_and_cached_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class _Voiced(_FakeKokoro):
        def create(self, text: str, **options: Any) -> tuple[np.ndarray, int]:
            calls.append((options["voice"], options["lang"]))
            return super().create(text)

    engine = _Engine()
    monkeypatch.setattr(engine, "_load", lambda _settings: _Voiced())
    engine.speak("Hello.", _settings())
    engine.speak("Hello.", _settings(), "bf_emma")
    engine.speak("Hello.", _settings(), "bf_emma")  # cached
    assert calls == [("af_heart", "en-us"), ("bf_emma", "en-gb")]


def test_the_route_speaks_a_listed_voice_and_refuses_any_other(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voices: list[str | None] = []

    def fake(text: str, settings: Settings, voice: str | None = None) -> bytes:
        voices.append(voice)
        return b"RIFF-fake"

    monkeypatch.setattr("silverloop.family_routes.speak", fake)
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    url = f"/v1/people/{person_id}/my-day/speech"
    headers = _headers("senior-1")
    assert (
        client.post(url, json={"text": "Hi.", "voice": "af_bella"}, headers=headers).status_code
        == 200
    )
    assert client.post(url, json={"text": "Hi."}, headers=headers).status_code == 200
    refused = client.post(url, json={"text": "Hi.", "voice": "../../etc"}, headers=headers)
    assert refused.status_code == 422
    assert voices == ["af_bella", None]


@pytest.mark.skipif(
    not _KOKORO_INSTALLED or not (_MODELS / "kokoro-v1.0.onnx").is_file(),
    reason="Kokoro (the `tts` group) or its model files are not installed here.",
)
def test_every_offered_voice_is_in_the_voices_file() -> None:
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(str(_MODELS / "kokoro-v1.0.onnx"), str(_MODELS / tts_engine.VOICES_FILE))
    assert set(tts_engine.VOICES) <= set(kokoro.get_voices())


# ── Fair use: one person cannot keep the voice busy ───────────────────────────────────────────


def test_too_many_sentences_from_one_person_answer_429(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "silverloop.family_routes.speak", lambda text, settings, voice=None: b"RIFF-fake"
    )
    app = client.app
    app.state.settings = app.state.settings.model_copy(update={"tts_rate_per_10_min": 2})  # type: ignore[attr-defined]
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    assert _speech(client, person_id, "senior-1").status_code == 200
    assert _speech(client, person_id, "senior-1").status_code == 200
    refused = _speech(client, person_id, "senior-1")
    assert refused.status_code == 429
    # The limit is per person: the family's own sentences are still spoken.
    assert _speech(client, person_id, "family-a").status_code == 200


def test_a_sentence_that_waits_too_long_for_its_turn_is_refused_as_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    monkeypatch.setattr(engine, "_load", lambda _settings: _FakeKokoro())
    settings = _settings(tts_busy_wait_seconds=0.05)
    engine._lock.acquire()  # another sentence is being spoken
    try:
        with pytest.raises(tts_engine.SpeechBusy, match="busy"):
            engine.speak("Hello.", settings)
        # Whether Kokoro can speak is answered at once, never queued behind that sentence.
        monkeypatch.setattr(engine, "_load_locked", lambda _settings: _FakeKokoro())
        assert engine.available(settings) is None
    finally:
        engine._lock.release()
    assert engine.speak("Hello.", settings).startswith(b"RIFF")


def test_the_route_answers_503_when_the_voice_is_busy(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def busy(text: str, settings: Settings, voice: str | None = None) -> bytes:
        raise tts_engine.SpeechBusy("The Kokoro voice is busy. Try again in a moment.")

    monkeypatch.setattr("silverloop.family_routes.speak", busy)
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    response = _speech(client, person_id, "senior-1")
    assert response.status_code == 503
    assert "busy" in response.json()["detail"]
    # Marked as busy, so the browser asks again rather than dropping the Kokoro voice.
    assert response.json()["code"] == tts_engine.SPEECH_BUSY_CODE == "speech_busy"
    assert response.headers["retry-after"] == "1"


def test_a_voice_that_cannot_speak_is_not_marked_busy(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(text: str, settings: Settings, voice: str | None = None) -> bytes:
        raise tts_engine.SpeechUnavailable("Kokoro could not speak: RuntimeError.")

    monkeypatch.setattr("silverloop.family_routes.speak", broken)
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    response = _speech(client, person_id, "senior-1")
    assert response.status_code == 503
    assert "code" not in response.json()
    assert "retry-after" not in response.headers


def test_a_senior_cannot_hear_or_check_another_seniors_voice(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "silverloop.family_routes.speak", lambda text, settings, voice=None: b"RIFF-fake"
    )
    monkeypatch.setattr("silverloop.family_routes.unavailable_reason", lambda settings: None)
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    _onboard(client, "senior-2", "senior", "Mr Lee")
    assert _speech(client, person_id, "senior-2").status_code == 404
    voice = client.get(f"/v1/people/{person_id}/my-day/voice", headers=_headers("senior-2"))
    assert voice.status_code == 404
