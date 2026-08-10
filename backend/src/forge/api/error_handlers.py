"""Domain error -> HTTP response translation.

Purpose:       The single place `ForgeError` subtypes become HTTP responses.
Responsibility: Exception handling only — registered once against the FastAPI app
                in core/app_factory.py. Application/domain code raises `ForgeError`
                subtypes and never constructs an HTTP response itself (see
                domain/errors.py).
Depends on:    fastapi, domain/errors.py, api/schemas.py.
Depended on by: core/app_factory.py.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from forge.api.schemas import ErrorResponse
from forge.domain.errors import (
    ForgeError,
    GraphUnavailableError,
    NotFoundError,
    SourceImportError,
    SourceValidationError,
    UnsupportedRepositoryStateError,
    ValidationError,
    WorkspaceError,
)

logger = logging.getLogger(__name__)

# Checked in order via `isinstance`, most specific first — a plain dict keyed by
# `type(exc)` would miss every subtype (e.g. `UnsafeArchiveError` extends
# `SourceValidationError` but is never raised directly by name here), silently
# falling through to 500 for what should be a 400. Order matters: put a subtype
# before its parent only if it needs a different status than the parent's entry.
_STATUS_BY_ERROR: list[tuple[type[ForgeError], int]] = [
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (SourceValidationError, status.HTTP_400_BAD_REQUEST),
    (ValidationError, status.HTTP_400_BAD_REQUEST),
    (SourceImportError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (UnsupportedRepositoryStateError, status.HTTP_409_CONFLICT),
    (GraphUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (WorkspaceError, status.HTTP_500_INTERNAL_SERVER_ERROR),
]


def _status_for(exc: ForgeError) -> int:
    for error_type, status_code in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return status_code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def register_error_handlers(app: FastAPI) -> None:
    """Register one handler covering `ForgeError` and every subtype."""

    @app.exception_handler(ForgeError)
    async def handle_forge_error(_request: Request, exc: ForgeError) -> JSONResponse:
        status_code = _status_for(exc)
        if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.exception("Unhandled ForgeError", exc_info=exc)
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(
                error=type(exc).__name__,
                message=str(exc),
            ).model_dump(),
        )
