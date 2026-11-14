from __future__ import annotations

from fastapi import APIRouter, Request, status

from opal_look_yolo.errors import OpalException
from opal_look_yolo.schemas.common import HealthStatus, OpalError, ServiceInfo

router = APIRouter(tags=["info"])

_ERROR_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": OpalError},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": OpalError},
}


@router.get("/info/", response_model=ServiceInfo, responses=_ERROR_RESPONSES,
    response_model_exclude_none=True,
)
async def show_info(request: Request) -> ServiceInfo:
    settings = request.app.state.settings
    return ServiceInfo(
        name="opal-yolo",
        version=settings.service_version,
        engine_id="yolo",
    )


@router.get("/health/", response_model=HealthStatus, responses=_ERROR_RESPONSES,
    response_model_exclude_none=True,
)
async def show_health(request: Request) -> HealthStatus:
    try:
        engine_available = bool(request.app.state.engine_probe())
    except OpalException:
        raise
    except Exception as exc:
        raise OpalException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "service_unavailable",
            "Engine availability check failed",
        ) from exc

    return HealthStatus(
        status="ok" if engine_available else "degraded",
        engine_available=engine_available,
        detail=None if engine_available else "Ultralytics YOLO engine is not available",
    )
