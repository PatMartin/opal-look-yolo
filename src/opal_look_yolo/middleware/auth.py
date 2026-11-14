from __future__ import annotations

import secrets

from fastapi import Request, status

from opal_look_yolo.errors import OpalException


async def require_bearer_auth(request: Request) -> None:
    settings = request.app.state.settings
    if settings.auth_disabled:
        return

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise OpalException(
            status.HTTP_401_UNAUTHORIZED,
            "unauthorized",
            "Missing or invalid authentication credentials",
        )

    if not secrets.compare_digest(token, settings.auth_token or ""):
        raise OpalException(
            status.HTTP_401_UNAUTHORIZED,
            "unauthorized",
            "Missing or invalid authentication credentials",
        )
