"""Classified JSON bodies for server-side failures, so no framework text ever reaches a client.

Every error this module handles is the server's fault, not the caller's:

- `StoredStateIncompatible`: a stored snapshot predates the current contract (see
  `stored_state.py`). `code: "stored_state_incompatible"`, which the web offers a demo reset for.
- a pydantic `ValidationError` raised while the server builds or re-reads a model. It subclasses
  `ValueError`, so it must not reach a `ValueError -> 422` mapping. Starlette picks the handler for
  the most specific class, so this handler wins over the app-wide `ValueError` handler; routes that
  catch `ValueError` locally re-raise `ValidationError` first (`main.py`) so it reaches this
  handler too. Request-body validation is FastAPI's `RequestValidationError`, a different class,
  and still produces its own 422. The one deliberate exception is
  `GET .../review-threshold/replay`, which builds its candidate from query parameters and turns
  that model's rejection into a 422 with a fixed plain-language message, never the pydantic text.
- FastAPI's `ResponseValidationError`: a route returned something its response model rejects.

Each body is a `models.ServerErrorBody` -- `{"code", "message", "detail"}` -- declared as the 500
response of every route (`SERVER_ERROR_RESPONSES`, applied app-wide in `main.create_app`), so the
code is part of the generated client's contract. `detail` repeats `message` because every existing
client reads `detail` (the FastAPI convention the rest of the API follows). The message is fixed
plain language; field paths go to the server log only, never stored values.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from silverloop.models import ServerErrorBody, ServerErrorCode
from silverloop.stored_state import StoredStateIncompatible

# Declared on every route, so the classified body is part of the OpenAPI contract.
SERVER_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    500: {"model": ServerErrorBody, "description": "Classified server error"},
}

INTERNAL_ERROR_MESSAGE = (
    "Care+ hit a server error and could not finish this request. Try again, and report it if "
    "it keeps happening."
)

_LOGGER = logging.getLogger("silverloop.errors")


def server_error_body(code: ServerErrorCode, message: str) -> dict[str, Any]:
    return ServerErrorBody(code=code, message=message, detail=message).model_dump(mode="json")


def _route(request: Request) -> str:
    template = getattr(request.scope.get("route"), "path", None)
    return template if isinstance(template, str) else "<unmatched>"


def _field_paths(errors: Iterable[Mapping[str, Any]]) -> str:
    return ",".join(
        sorted({".".join(str(part) for part in error.get("loc", ())) for error in errors})
    )


def register_server_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(StoredStateIncompatible)
    async def _handle_stored_state_incompatible(
        request: Request, exc: StoredStateIncompatible
    ) -> Response:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=server_error_body(ServerErrorCode.STORED_STATE_INCOMPATIBLE, str(exc)),
        )

    @application.exception_handler(ValidationError)
    async def _handle_server_validation_error(request: Request, exc: ValidationError) -> Response:
        _LOGGER.error(
            "server_validation_error route=%s model=%s fields=%s",
            _route(request),
            exc.title,
            _field_paths(exc.errors()),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=server_error_body(ServerErrorCode.INTERNAL_ERROR, INTERNAL_ERROR_MESSAGE),
        )

    @application.exception_handler(ResponseValidationError)
    async def _handle_response_validation_error(
        request: Request, exc: ResponseValidationError
    ) -> Response:
        _LOGGER.error(
            "response_validation_error route=%s fields=%s",
            _route(request),
            _field_paths(exc.errors()),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=server_error_body(ServerErrorCode.INTERNAL_ERROR, INTERNAL_ERROR_MESSAGE),
        )
