from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from opal_look_yolo.errors import OpalException

_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


async def require_bearer_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> None:
    settings = request.app.state.settings
    if settings.auth_disabled:
        return

    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise OpalException(
            status.HTTP_401_UNAUTHORIZED,
            "unauthorized",
            "Missing or invalid authentication credentials",
        )

    if not secrets.compare_digest(credentials.credentials, settings.auth_token or ""):
        raise OpalException(
            status.HTTP_401_UNAUTHORIZED,
            "unauthorized",
            "Missing or invalid authentication credentials",
        )
