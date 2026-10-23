from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# The id of the HTTP request currently being served, for log lines written far from the
# middleware that minted it. A `ContextVar` rather than a parameter threaded through the
# repository: the planner is six frames below the route handler and correlating its own log lines
# is the only thing it needs the id for. `anyio` copies the context into the thread that runs a
# sync endpoint, so this survives FastAPI's threadpool. `None` outside a request (CLI entry
# points, the scenario runner, tests) is the honest answer, not a defect.
request_id_var: ContextVar[str | None] = ContextVar("silverloop_request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "structured_fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, separators=(",", ":"), default=str)


def _structured_logger(name: str) -> logging.Logger:
    """A named logger that emits `JsonFormatter` records exactly once.

    Idempotent: repeated calls return the same configured logger rather than stacking handlers,
    and `propagate` stays off so a host application's root handler cannot re-emit the same line
    in a second format.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def request_logger() -> logging.Logger:
    return _structured_logger("silverloop.request")


def agent_logger() -> logging.Logger:
    """The log stream for the planner loops.

    Exists so a provider failure has somewhere to go other than the audit trail. `evidence_json`
    is append-only and rendered to coordinators, so it records the exception's class only; the
    text -- which can carry request ids, ARNs, account ids or part of a credential -- belongs on
    an operator-controlled log with its own retention and access rules.
    """
    return _structured_logger("silverloop.agent")
