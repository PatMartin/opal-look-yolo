from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

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


class OpalException(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def opal_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})


def _default_code(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "request_failed")


async def opal_exception_handler(_: Request, exc: OpalException) -> JSONResponse:
    return opal_error_response(exc.status_code, exc.code, exc.message, exc.details)


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    details = None if isinstance(exc.detail, str) else {"detail": exc.detail}
    return opal_error_response(exc.status_code, _default_code(exc.status_code), message, details)


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    malformed = any(error.get("type") == "json_invalid" for error in errors)
    status_code = (
        status.HTTP_400_BAD_REQUEST if malformed else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return opal_error_response(
        status_code,
        _default_code(status_code),
        "Malformed request body" if malformed else "Request validation failed",
        {"errors": errors},
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled request failure", exc_info=exc)
    return opal_error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Unexpected internal failure",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OpalException, opal_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
