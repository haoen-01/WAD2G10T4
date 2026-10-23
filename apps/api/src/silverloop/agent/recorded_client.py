"""A provider client that replays committed recordings instead of calling a model.

Why this exists
---------------
Every agent behaviour in this repository is offline-unmeasurable today: CI runs with
`LLM_ENABLED=false`, so every planner counter is structurally zero and the benchmark measures
the deterministic ranker only. A hand-written fake per test proves one scripted path; it cannot
produce a benchmark arm, a latency number or a token count.

`RecordedClient` is the missing transport. It exposes exactly the surface both planner loops and
the intent parser use -- `client.messages.create(**kwargs)` -- and answers from a committed JSON
recording keyed by the request itself. Nothing downstream knows the difference: the planner's
allow-list, guardrail, iteration cap and every degradation path are unchanged, which is the whole
point (a recorded arm that bypassed the loop would measure nothing).

The key
-------
`sha256` of the canonical JSON of `{model, system, tools, messages}` -- the four fields that
determine what a model was asked. Keying on the request means a prompt edit, a tool-schema edit
or a different deterministic order invalidates the recording *loudly*: the lookup misses,
`RecordingMiss` is raised, and the planner degrades to `fallback_error` with the reason
`"RecordingMiss"` through the path it already had. That is the correct failure -- a stale
recording must never be replayed against a prompt it was not made for.

Record mode
-----------
`mode="record"` wraps a real (or scripted) client, serialises what it returned and stores it. It
refuses to run under CI, and no test uses it: recordings are generated deliberately, by a human
running a generator, and reviewed in the diff like any other fixture.

Record mode returns the *reconstituted* response rather than the inner client's own object. That
is deliberate and load-bearing: a multi-turn loop appends the assistant turn back into
`messages`, so the next request's key depends on the shape of the previous response. Returning
the reconstituted object makes record and replay produce byte-identical keys by construction.

Honesty
-------
This module records what it is given. It makes no claim about *what* produced the recording --
see the `synthetic` flag and `banner` on every recording file, and
`silverloop.evaluation.ranking_llm` for the recordings this repository actually ships, which were
produced by a deterministic scripted stand-in and not by a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

SCHEMA_VERSION = 1

RecordingMode = Literal["replay", "record"]

# The four request fields that determine what the model was asked. `max_tokens`, `thinking`,
# `output_config` and `tool_choice` are deliberately excluded: they shape how an answer is
# produced, not which answer a recording stands for, and including them would invalidate every
# recording on an unrelated effort-setting change.
KEY_FIELDS: tuple[str, ...] = ("model", "system", "tools", "messages")

# Environment variables that mean "this is CI". A recording must never be produced by an
# automated run: it would be a network call nobody reviewed, from a machine holding credentials.
CI_ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "CI",
    "GITHUB_ACTIONS",
    "CONTINUOUS_INTEGRATION",
    "BUILDKITE",
)

_FALSEY = frozenset({"", "0", "false", "no", "off"})

_USAGE_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


class RecordingMiss(LookupError):
    """No recorded response for this request.

    Raised out of `messages.create`, so it lands in the same `except Exception` both planner
    loops already use for a provider failure. The recorded reason is `type(error).__name__`,
    i.e. `"RecordingMiss"` -- a miss is reported as a fallback with a name, never as a 500 and
    never as a silently different answer.
    """

    def __init__(self, key: str, *, source: str | None = None) -> None:
        where = f" in {source}" if source else ""
        super().__init__(f"No recorded response{where} for request {key[:16]}.")
        self.key = key
        self.source = source


class RecordingRefused(RuntimeError):
    """Record mode was requested somewhere it is not permitted (CI), or without an inner client."""


# ── Request keying ────────────────────────────────────────────────────────────────────────────


def _canonical(value: Any) -> Any:
    """A JSON-safe, order-stable projection of anything that can appear in a request.

    Requests contain plain dicts on the first turn and provider response objects from the second
    turn onward (the loop appends `response.content` verbatim), so this has to handle objects as
    well as data. Attribute dictionaries are used for objects; anything genuinely opaque falls
    back to `repr`, which is stable for the `SimpleNamespace` blocks this module produces.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted(json.dumps(_canonical(item), sort_keys=True) for item in value)
    if isinstance(value, Sequence):
        return [_canonical(item) for item in value]
    if isinstance(value, Iterable):
        return [_canonical(item) for item in value]
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return _canonical(dumper(mode="json"))
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in attributes.items()
            if not str(key).startswith("_")
        }
    return repr(value)


def request_key(request: Mapping[str, Any]) -> str:
    """`sha256` over the canonical JSON of the four `KEY_FIELDS`."""
    document = {name: _canonical(request.get(name)) for name in KEY_FIELDS}
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ── Stored shape ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecordedResponse:
    """One stored provider turn.

    `content` holds only the block kinds the loops in this repository read -- `tool_use` and
    `text`. Any other kind (a thinking block, say) is stored as its bare type, because nothing
    here reads it and storing more would put unreviewed provider output in a committed file.
    """

    key: str
    model: str
    content: list[dict[str, Any]]
    stop_reason: str | None
    usage: dict[str, int]
    latency_ms: int
    note: str = ""

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("input_tokens", 0)) + int(self.usage.get("output_tokens", 0))

    def as_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "model": self.model,
            "note": self.note,
            "stop_reason": self.stop_reason,
            "usage": dict(sorted(self.usage.items())),
            "latency_ms": self.latency_ms,
            "content": self.content,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> RecordedResponse:
        content = document.get("content")
        usage = document.get("usage")
        return cls(
            key=str(document["key"]),
            model=str(document.get("model", "")),
            content=[dict(block) for block in content] if isinstance(content, list) else [],
            stop_reason=(
                None if document.get("stop_reason") is None else str(document["stop_reason"])
            ),
            usage=(
                {str(name): int(count) for name, count in usage.items()}
                if isinstance(usage, Mapping)
                else {}
            ),
            latency_ms=int(document.get("latency_ms", 0) or 0),
            note=str(document.get("note", "")),
        )

    def reconstitute(self) -> SimpleNamespace:
        """Rebuild the response object the loops expect: `.content`, `.stop_reason`, `.usage`,
        plus `.latency_ms` carried through from the recording so a replayed run can report the
        latency of the call that was actually made rather than the microseconds a dict lookup
        took."""
        blocks = [SimpleNamespace(**block) for block in self.content]
        usage = SimpleNamespace(**{name: int(self.usage.get(name, 0)) for name in _USAGE_FIELDS})
        return SimpleNamespace(
            content=blocks,
            stop_reason=self.stop_reason,
            usage=usage,
            latency_ms=self.latency_ms,
        )


def serialise_response(
    response: Any, *, key: str, model: str, latency_ms: int, note: str = ""
) -> RecordedResponse:
    """Project a live provider response into the stored shape. Defensive throughout: a response
    that is not the shape the SDK promises is recorded as an empty turn rather than raising, so a
    recording session surfaces the oddity in the diff instead of crashing halfway through."""
    blocks: list[dict[str, Any]] = []
    content = getattr(response, "content", None)
    if isinstance(content, list | tuple):
        for block in content:
            block_type = getattr(block, "type", None)
            if block_type == "tool_use":
                raw_input = getattr(block, "input", None)
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(getattr(block, "id", "")),
                        "name": str(getattr(block, "name", "")),
                        "input": _canonical(raw_input if isinstance(raw_input, Mapping) else {}),
                    }
                )
            elif block_type == "text":
                blocks.append({"type": "text", "text": str(getattr(block, "text", ""))})
            else:
                blocks.append({"type": str(block_type)})

    raw_usage = getattr(response, "usage", None)
    usage = {name: int(getattr(raw_usage, name, 0) or 0) for name in _USAGE_FIELDS}
    stop_reason = getattr(response, "stop_reason", None)
    return RecordedResponse(
        key=key,
        model=model,
        content=blocks,
        stop_reason=None if stop_reason is None else str(stop_reason),
        usage=usage,
        latency_ms=int(latency_ms),
        note=note,
    )


@dataclass
class Recording:
    """One recording file: a labelled, ordered set of `RecordedResponse` entries.

    `synthetic` and `banner` are mandatory provenance, not decoration. A recording file states
    what produced it; a reader must never have to infer whether a committed fixture came from a
    model or from a script.
    """

    loop: str
    banner: str
    generator: str
    synthetic: bool = True
    entries: list[RecordedResponse] = field(default_factory=list)

    def as_document(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "synthetic": self.synthetic,
            "banner": self.banner,
            "loop": self.loop,
            "generator": self.generator,
            "entries": [entry.as_document() for entry in self.entries],
        }

    def dumps(self) -> str:
        return json.dumps(self.as_document(), indent=2, sort_keys=False) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Recording:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise ValueError(f"{path} is not a recording document.")
        version = int(document.get("schema_version", 0))
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"{path} has schema_version {version}; this build reads {SCHEMA_VERSION}."
            )
        raw_entries = document.get("entries")
        entries = (
            [RecordedResponse.from_document(entry) for entry in raw_entries]
            if isinstance(raw_entries, list)
            else []
        )
        return cls(
            loop=str(document.get("loop", "")),
            banner=str(document.get("banner", "")),
            generator=str(document.get("generator", "")),
            synthetic=bool(document.get("synthetic", True)),
            entries=entries,
        )


def load_recordings(path: Path) -> tuple[dict[str, RecordedResponse], list[Path]]:
    """Load one recording file, or every `*.json` in a directory, into a key -> response map.

    A missing path is not an error here: it returns an empty map, and the caller decides what to
    say about it. That is what lets the benchmark arm print an explicit "not recorded" row
    instead of a silent zero.
    """
    files: list[Path] = []
    if path.is_dir():
        files = sorted(p for p in path.glob("*.json"))
    elif path.is_file():
        files = [path]

    responses: dict[str, RecordedResponse] = {}
    for file in files:
        recording = Recording.load(file)
        for entry in recording.entries:
            existing = responses.get(entry.key)
            if existing is not None and existing != entry:
                raise ValueError(
                    f"{file} redefines recorded request {entry.key[:16]} with a different "
                    "response; recordings must agree."
                )
            responses[entry.key] = entry
    return responses, files


# ── The client ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReplayedCall:
    """What one replayed request cost, for the arm's latency/token reporting."""

    key: str
    model: str
    latency_ms: int
    total_tokens: int


def refuse_record_mode_in_ci(environ: Mapping[str, str] | None = None) -> None:
    """Raise if any CI marker is set. Called from `RecordedClient.__init__`, so there is no way
    to reach record mode on an automated run at all, not merely no code path that does."""
    env = os.environ if environ is None else environ
    for name in CI_ENVIRONMENT_VARIABLES:
        value = str(env.get(name, ""))
        if value.strip().lower() not in _FALSEY:
            raise RecordingRefused(
                f"Recording is refused because {name}={value!r} marks this as CI. Recordings are "
                "produced deliberately, on a human's machine, and reviewed in the diff."
            )


class _RecordedMessages:
    """The `client.messages` surface. One method, the only one either loop calls."""

    def __init__(self, owner: RecordedClient) -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> Any:
        return self._owner._create(kwargs)


class RecordedClient:
    """A `messages.create`-shaped client backed by a committed recording.

    `mode="replay"` (the default) answers from `path`; a request with no recorded answer raises
    `RecordingMiss`. `mode="record"` requires `inner` -- a real or scripted client with the same
    surface -- stores what it returns and returns the reconstituted form.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        mode: RecordingMode = "replay",
        inner: Any | None = None,
        loop: str = "",
        banner: str = "",
        generator: str = "",
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if mode not in ("replay", "record"):
            raise ValueError(f"Unknown recording mode {mode!r}; expected 'replay' or 'record'.")
        self.path = Path(path)
        self.mode: RecordingMode = mode
        self.messages = _RecordedMessages(self)
        self.replayed: list[ReplayedCall] = []
        self.misses: list[str] = []

        if mode == "record":
            refuse_record_mode_in_ci(environ)
            if inner is None:
                raise RecordingRefused("Record mode needs an inner client to record from.")
            self._inner = inner
            self.recording = Recording(loop=loop, banner=banner, generator=generator)
            self._responses: dict[str, RecordedResponse] = {}
            self.sources: list[Path] = []
        else:
            self._inner = None
            self.recording = Recording(loop=loop, banner=banner, generator=generator)
            self._responses, self.sources = load_recordings(self.path)

    @property
    def recorded_count(self) -> int:
        """How many distinct requests this client can answer. Zero means "nothing recorded"."""
        return len(self._responses)

    def _create(self, kwargs: dict[str, Any]) -> Any:
        key = request_key(kwargs)
        model = str(kwargs.get("model", ""))
        if self.mode == "record":
            recorded = self._record(key, kwargs, model)
        else:
            recorded = self._responses.get(key)
            if recorded is None:
                self.misses.append(key)
                raise RecordingMiss(key, source=str(self.path))
        self.replayed.append(
            ReplayedCall(
                key=key,
                model=recorded.model or model,
                latency_ms=recorded.latency_ms,
                total_tokens=recorded.total_tokens,
            )
        )
        return recorded.reconstitute()

    def _record(self, key: str, kwargs: dict[str, Any], model: str) -> RecordedResponse:
        started = time.perf_counter()
        response = self._inner.messages.create(**kwargs)
        measured_ms = int((time.perf_counter() - started) * 1000)
        # A wrapped client may report its own latency; a real SDK response does not, and the wall
        # clock is the only honest number for it. The scripted stand-in that produces this
        # repository's committed recordings does report one, and labels it synthetic -- recording
        # the microseconds a dict comprehension took would be a worse lie than a declared
        # stand-in value.
        declared = getattr(response, "latency_ms", None)
        latency_ms = int(declared) if isinstance(declared, int) else measured_ms
        recorded = serialise_response(response, key=key, model=model, latency_ms=latency_ms)
        existing = self._responses.get(key)
        if existing is None:
            self._responses[key] = recorded
            self.recording.entries.append(recorded)
        return recorded

    def save(self, path: Path | None = None) -> Path:
        """Write the recording gathered in record mode. Never called from a test."""
        if self.mode != "record":
            raise RecordingRefused("Only a client in record mode has a recording to save.")
        target = Path(path) if path is not None else self.path
        self.recording.write(target)
        return target


__all__ = [
    "CI_ENVIRONMENT_VARIABLES",
    "KEY_FIELDS",
    "SCHEMA_VERSION",
    "RecordedClient",
    "RecordedResponse",
    "Recording",
    "RecordingMiss",
    "RecordingRefused",
    "ReplayedCall",
    "load_recordings",
    "refuse_record_mode_in_ci",
    "request_key",
    "serialise_response",
]
