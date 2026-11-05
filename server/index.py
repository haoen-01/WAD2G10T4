"""Vercel's Python entrypoint for the Care+ API.

The package lives in `src/silverloop` and imports itself as `silverloop.*`. Locally `uv`
installs it; on Vercel the project may not be installed, so put `src/` on the import path first.
Vercel loads this module and serves `app` (`[tool.vercel] entrypoint = "index:app"`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from silverloop.main import app  # noqa: E402

__all__ = ["app"]
