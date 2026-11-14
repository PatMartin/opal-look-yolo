from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message

from opal_look_yolo.errors import opal_error_response

logger = logging.getLogger(__name__)

SESSION_HEADER = "X-Opal-Session-Id"
TRANSACTION_HEADER = "X-Opal-Transaction-Id"
REQUEST_HEADER = "X-Opal-Request-Id"
CAUSATION_HEADER = "X-Opal-Causation-Id"


def _valid_header(value: str | None) -> str | None:
    if value is None:
        return None
    return value if 1 <= len(value) <= 128 else None


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Message]) -> Response:
        request.state.opal_session_id = _valid_header(request.headers.get(SESSION_HEADER))
        request.state.opal_transaction_id = _valid_header(
            request.headers.get(TRANSACTION_HEADER)
        ) or uuid.uuid4().hex
        request.state.opal_request_id = _valid_header(
            request.headers.get(REQUEST_HEADER)
        ) or uuid.uuid4().hex
        request.state.opal_causation_id = _valid_header(request.headers.get(CAUSATION_HEADER))

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception("Unhandled middleware request failure", exc_info=exc)
            response = opal_error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "internal_error",
                "Unexpected internal failure",
            )

        response.headers[TRANSACTION_HEADER] = request.state.opal_transaction_id
        response.headers[REQUEST_HEADER] = request.state.opal_request_id
        if request.state.opal_session_id:
            response.headers[SESSION_HEADER] = request.state.opal_session_id
        if request.state.opal_causation_id:
            response.headers[CAUSATION_HEADER] = request.state.opal_causation_id
        return response
