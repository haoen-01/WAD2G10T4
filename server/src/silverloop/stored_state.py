"""Reading simulation snapshots that were stored under an older contract.

`advance()` persists its whole `AdvanceResponse` in `SimulationEventRow.response_json`, and the
idempotent `event_id` replay re-validates it later. The snapshot is frozen at the contract of the
code that wrote it. When a required field is later added to that contract
(`PersonState.decided_by_gate` was), an older row -- typically an offline SQLite demo file that
outlived a code update -- no longer validates.

The replay must return the full `AdvanceResponse`. A missing gate cannot be reconstructed honestly
-- the decision alone does not name its rung (the contact cap and the accepted-outreach cooldown
both return `SUPPRESS`) -- so it raises `StoredStateIncompatible`, which the API reports as a
classified `stored_state_incompatible` error. Resetting the demo person starts a fresh run whose
snapshots match the current contract.

Nothing here resets or migrates stored data: that would be a silent destructive write, and on a
shared database it would destroy real history. The recovery is the explicit, audited demo reset.

A third failure mode is not a schema mismatch at all: the stored `response_json` text itself can
fail to decode as JSON (a hand-corrupted row, or a storage-layer truncation). SQLAlchemy's JSON
type decodes the column as part of fetching the row, before any pydantic model sees it, so
`json.JSONDecodeError` -- a `ValueError` subclass -- surfaces at the query call site in
`sql_repository.py`, not inside `load_stored_advance`. That call site catches it and reports it
the same way: `StoredStateIncompatible`, via `undecodable_stored_json` below.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from silverloop.models import (
    AdvanceResponse,
)

_LOGGER = logging.getLogger("silverloop.stored_state")

STORED_STATE_INCOMPATIBLE_MESSAGE = (
    "Stored demo state was saved by an older version of Care+ and can no longer be read. "
    "Reset the local synthetic demo for this person to continue."
)


class StoredStateIncompatible(Exception):  # noqa: N818 - named for what it reports
    """A stored snapshot no longer matches the current response contract.

    Deliberately not a `ValueError`: routes catch `ValueError` locally and return `str(exc)` as a
    422, which is how raw pydantic text reached the browser in the first place.
    """

    def __init__(self, source: str, missing_fields: list[str]) -> None:
        self.source = source
        self.missing_fields = missing_fields
        super().__init__(STORED_STATE_INCOMPATIBLE_MESSAGE)


def _field_paths(exc: ValidationError) -> list[str]:
    return sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})


def _incompatible(source: str, exc: ValidationError) -> StoredStateIncompatible:
    fields = _field_paths(exc)
    # Field paths only: never the stored values, which can carry a person's rationale text.
    _LOGGER.warning("stored_state_incompatible source=%s fields=%s", source, ",".join(fields))
    return StoredStateIncompatible(source, fields)


def undecodable_stored_json(source: str, exc: json.JSONDecodeError) -> StoredStateIncompatible:
    """A stored `response_json` value that is not valid JSON at all.

    Call this at the query call site that raised `json.JSONDecodeError` (see the module
    docstring): never the raw decode error text or the stored column value, only that the source
    query failed to read it.
    """
    _LOGGER.warning("stored_state_incompatible source=%s reason=undecodable_json", source)
    return StoredStateIncompatible(source, [])


def load_stored_advance(payload: dict[str, Any], *, source: str) -> AdvanceResponse:
    """The full stored `AdvanceResponse`, or `StoredStateIncompatible` if it no longer validates."""
    try:
        return AdvanceResponse.model_validate(payload)
    except ValidationError as exc:
        raise _incompatible(source, exc) from exc
