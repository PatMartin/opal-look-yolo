"""X-Opal-* correlation header handling and the OpalError envelope.

Inbound tokens are opaque 1..128-char printable ASCII with no whitespace;
invalid client-supplied values yield 422. Missing transaction/request IDs
are generated; session/causation IDs propagate only when supplied. All
known IDs are echoed on every response, including errors.

Unhandled exceptions are converted here to the OpalError envelope so the
500 response still carries the correct request/transaction IDs and
X-Opal-* headers (the framework's error middleware sits outside this
layer and would lose them).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message

logger = logging.getLogger(__name__)

SESSION_HEADER = "X-Opal-Session-Id"
TRANSACTION_HEADER = "X-Opal-Transaction-Id"
REQUEST_HEADER = "X-Opal-Request-Id"
CAUSATION_HEADER = "X-Opal-Causation-Id"

CORRELATION_HEADERS = (
    SESSION_HEADER,
    TRANSACTION_HEADER,
    REQUEST_HEADER,
    CAUSATION_HEADER,
)

_TOKEN = re.compile(r"^[\x21-\x7e]{1,128}$")


@dataclass(frozen=True)
class CorrelationIds:
    session_id: str | None
    transaction_id: str
    request_id: str
    causation_id: str | None


_current: ContextVar[CorrelationIds | None] = ContextVar("opal_yolo_correlation", default=None)


def _new_id() -> str:
    return uuid.uuid4().hex


def current_ids() -> CorrelationIds:
    """IDs for the in-flight request, or fresh ones outside a request."""
    ids = _current.get()
    if ids is None:
        return CorrelationIds(None, _new_id(), _new_id(), None)
    return ids


def envelope(
    ids: CorrelationIds,
    *,
    code: str,
    message: str,
    details: Any = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    """Build the kernel OpalError body: error.{code,message,request_id,
    transaction_id,session_id,causation_id,retryable?,details?}."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": ids.request_id,
        "transaction_id": ids.transaction_id,
        "session_id": ids.session_id,
        "causation_id": ids.causation_id,
    }
    if retryable is not None:
        error["retryable"] = bool(retryable)
    if details is not None:
        if isinstance(details, dict):
            error["details"] = details
        else:
            error["details"] = {
                "errors": details if isinstance(details, list) else [details]
            }
    return {"error": error}


def _invalid_header_response(header_names: list[str]) -> JSONResponse:
    ids = CorrelationIds(None, _new_id(), _new_id(), None)
    return JSONResponse(
        status_code=422,
        content=envelope(
            ids,
            code="invalid_correlation_header",
            message="Invalid X-Opal-* header value: expected 1-128 printable "
            "ASCII characters without whitespace.",
            details={"headers": header_names},
        ),
        headers={
            TRANSACTION_HEADER: ids.transaction_id,
            REQUEST_HEADER: ids.request_id,
        },
    )


def _unhandled_error_response(ids: CorrelationIds) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=envelope(
            ids,
            code="internal_error",
            message="Unexpected internal failure",
        ),
    )


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Message]) -> Response:
        supplied = {name: request.headers.get(name) for name in CORRELATION_HEADERS}
        invalid = [
            name
            for name, value in supplied.items()
            if value is not None and not _TOKEN.match(value)
        ]
        if invalid:
            return _invalid_header_response(invalid)

        ids = CorrelationIds(
            session_id=supplied[SESSION_HEADER],
            transaction_id=supplied[TRANSACTION_HEADER] or _new_id(),
            request_id=supplied[REQUEST_HEADER] or _new_id(),
            causation_id=supplied[CAUSATION_HEADER],
        )
        request.state.opal_correlation = ids
        token = _current.set(ids)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled middleware request failure")
            response = _unhandled_error_response(ids)
        finally:
            _current.reset(token)

        response.headers[TRANSACTION_HEADER] = ids.transaction_id
        response.headers[REQUEST_HEADER] = ids.request_id
        if ids.session_id is not None:
            response.headers[SESSION_HEADER] = ids.session_id
        if ids.causation_id is not None:
            response.headers[CAUSATION_HEADER] = ids.causation_id
        return response
