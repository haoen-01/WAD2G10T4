"""Set up the Kokoro voice for "Read my day".

    uv sync                                     # Kokoro's packages are in the default `tts` group
    uv run python -m silverloop.tts download    # the model and voices, about 350 MB, once
    uv run python -m silverloop.tts check       # can Kokoro speak here? (writes a test WAV)

Files come from the kokoro-onnx project's v1.0 release and are checked against the SHA-256 below
before they are kept; a file that does not match is deleted. They go to `TTS_MODEL_DIR`
(`server/models/kokoro` by default), which git ignores.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import httpx

from silverloop.config import Settings
from silverloop.tts.engine import VOICES_FILE, model_dir, speak, unavailable_reason

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
# Recorded from the v1.0 release files when this was set up.
FILES: dict[str, str] = {
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    VOICES_FILE: "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
SAMPLE = "Good morning, Mdm Lim. Your eye check-up is at 10:30 am, and John is going with you."


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(settings: Settings) -> int:
    directory = model_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    wanted = [settings.tts_model_file, VOICES_FILE]
    for name in wanted:
        expected = FILES.get(name)
        target = directory / name
        if expected is None:
            print(f"{name}: not a known release file; place it in {directory} yourself.")
            return 1
        if target.is_file() and _sha256(target) == expected:
            print(f"{name}: already here and verified.")
            continue
        partial = target.with_suffix(target.suffix + ".part")
        print(f"{name}: downloading…", flush=True)
        with httpx.stream("GET", f"{RELEASE}/{name}", follow_redirects=True, timeout=60) as reply:
            reply.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in reply.iter_bytes(1 << 20):
                    handle.write(chunk)
        if _sha256(partial) != expected:
            partial.unlink()
            print(f"{name}: checksum did not match; deleted. Try again.")
            return 1
        partial.replace(target)
        print(f"{name}: downloaded and verified ({target.stat().st_size // 1_000_000} MB).")
    return 0


def check(settings: Settings) -> int:
    if reason := unavailable_reason(settings):
        print(f"Kokoro cannot speak here: {reason}")
        return 1
    started = time.perf_counter()
    audio = speak(SAMPLE, settings)
    took = time.perf_counter() - started
    out = model_dir(settings) / "check.wav"
    out.write_bytes(audio)
    print(f"Kokoro spoke the sample with {settings.tts_voice} in {took:.1f}s: {out}")
    return 0


def main(argv: list[str]) -> int:
    settings = Settings()
    if argv[:1] == ["download"]:
        return download(settings)
    if argv[:1] == ["check"]:
        return check(settings)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
