from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from opal_look_yolo.middleware.correlation import (
    CorrelationIds,
    current_ids,
    envelope,
)

logger = logging.getLogger(__name__)

_STATUS_CODES: Mapping[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_412_PRECONDITION_FAILED: "precondition_failed",
    status.HTTP_413_CONTENT_TOO_LARGE: "payload_too_large",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_failed",
    status.HTTP_428_PRECONDITION_REQUIRED: "precondition_required",
    status.HTTP_429_TOO_MANY_REQUESTS: "capacity_exceeded",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}

# Transient statuses: the client may retry the same request later.
_RETRYABLE_STATUSES = frozenset({429, 503})


class OpalException(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        retryable: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable
        self.headers = headers


def opal_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=envelope(current_ids(), code=code, message=message, details=details),
    )


def _default_code(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "request_failed")


def _ids_for(request: Request) -> CorrelationIds:
    ids = getattr(request.state, "opal_correlation", None)
    return ids if ids is not None else current_ids()


def _retryable_for(status_code: int) -> bool | None:
    return True if status_code in _RETRYABLE_STATUSES else None


async def opal_exception_handler(request: Request, exc: OpalException) -> JSONResponse:
    retryable = exc.retryable if exc.retryable is not None else _retryable_for(exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(
            _ids_for(request),
            code=exc.code,
            message=exc.message,
            details=exc.details,
            retryable=retryable,
        ),
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    details = None if isinstance(exc.detail, str) else {"detail": exc.detail}
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(
            _ids_for(request),
            code=_default_code(exc.status_code),
            message=message,
            details=details,
            retryable=_retryable_for(exc.status_code),
        ),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    malformed = any(error.get("type") == "json_invalid" for error in errors)
    status_code = (
        status.HTTP_400_BAD_REQUEST if malformed else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope(
            _ids_for(request),
            code=_default_code(status_code),
            message="Malformed request body" if malformed else "Request validation failed",
            details={"errors": errors},
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled request failure", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=envelope(
            _ids_for(request),
            code="internal_error",
            message="Unexpected internal failure",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OpalException, opal_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
