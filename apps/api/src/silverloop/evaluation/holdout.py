"""Is the holdout set frozen, and against what?

A holdout that is a directory rather than a process is a holdout in name only: nothing stops a
scenario being edited after the fact, and nothing records which bytes the published numbers were
computed from. This module is the whole of the process:

1. `scenarios/holdout/FROZEN_DIGEST` records the sha256 of the holdout YAML bytes at the moment
   the set was frozen (the same `_scenario_digest` the harness already computes and prints).
2. Every run compares the live digest to that file and prints `holdout_frozen: true|false`.
3. A test fails when they disagree.

Changing a holdout scenario is therefore not forbidden -- it is *visible*. If the set genuinely
has to change, the answer is a new directory (`scenarios/holdout-v2/`) with its own frozen digest,
not a quiet edit under the old numbers. The one edit this repo has made to the set
(`4d3ddbd`, `h01` step 4) moved the score AGAINST Care+, which is the opposite of tuning to
the holdout; the point of freezing is that the next one is equally legible.
"""

from __future__ import annotations

from pathlib import Path

FROZEN_DIGEST_FILENAME = "FROZEN_DIGEST"


def frozen_digest_path(directory: Path) -> Path:
    return Path(directory) / FROZEN_DIGEST_FILENAME


def read_frozen_digest(directory: Path) -> str | None:
    """The digest the set was frozen at, or `None` when the set has never been frozen.

    `None` is an honest answer, not an error: a directory with no `FROZEN_DIGEST` has simply not
    been through the process, and the report says `unknown` rather than claiming either way.
    """
    path = frozen_digest_path(directory)
    if not path.exists():
        return None
    digest = path.read_text(encoding="utf-8").strip()
    return digest or None


def holdout_frozen(directory: Path, digest: str) -> bool | None:
    """`True` when the live digest matches the frozen one, `False` when it does not, `None` when
    the set was never frozen."""
    frozen = read_frozen_digest(directory)
    if frozen is None:
        return None
    return frozen == digest


def frozen_label(frozen: bool | None) -> str:
    if frozen is None:
        return "unknown (no FROZEN_DIGEST in the holdout directory)"
    return "true" if frozen else "FALSE -- the holdout bytes have changed since it was frozen"


__all__ = [
    "FROZEN_DIGEST_FILENAME",
    "frozen_digest_path",
    "frozen_label",
    "holdout_frozen",
    "read_frozen_digest",
]
