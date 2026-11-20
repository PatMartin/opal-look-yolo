from __future__ import annotations

import time

from fastapi import APIRouter, Request, status

from opal_look_yolo.portable_settings import pending_restart_fields
from opal_look_yolo.schemas.common import HealthReport, OpalError
from opal_look_yolo.timeutil import now_iso

router = APIRouter(tags=["health"])

API_VERSION = "v1"
SERVICE_NAME = "opal-look-yolo-svc"

_ERROR_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": OpalError},
    status.HTTP_403_FORBIDDEN: {"model": OpalError},
}
_HEALTH_RESPONSES = {
    **_ERROR_RESPONSES,
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": OpalError},
}


@router.get(
    "/health/",
    operation_id="opal_health_get",
    response_model=HealthReport,
    responses=_HEALTH_RESPONSES,
)
async def show_health(request: Request) -> HealthReport:
    """Kernel OpalHealthReport: the single service information surface.

    Returns HTTP 200 whenever the report can be produced, including when
    `ready` is false; 503 is reserved for a report that cannot be
    assembled at all.
    """
    store = request.app.state.store
    store_ok = store.ping()
    try:
        engine_available = bool(request.app.state.engine_probe())
    except Exception:
        engine_available = False
    ready = store_ok and engine_available
    if not store_ok:
        report_status = "error"
    elif not engine_available:
        report_status = "degraded"
    else:
        report_status = "ok"
    active = store.profiles.get_active()
    settings = request.app.state.settings
    started = getattr(request.app.state, "started_monotonic", None)
    uptime = (time.monotonic() - started) if started is not None else 0.0
    pending_fields = pending_restart_fields(
        store, request.app.state.running_settings
    )
    return HealthReport(
        name=SERVICE_NAME,
        version=settings.service_version,
        api_version=API_VERSION,
        status=report_status,
        live=True,
        ready=ready,
        details={"engine_available": engine_available},
        active_profile_id=str(active["profile_id"]) if active is not None else None,
        checked_at=now_iso(),
        uptime_seconds=max(0.0, uptime),
        pending_restart=bool(pending_fields),
        pending_restart_fields=pending_fields,
    )
