from __future__ import annotations

from fastapi import APIRouter, Request, status

from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.engines import Capabilities, Engine

router = APIRouter(prefix="/engine", tags=["engines"])

_RESPONSES = {status.HTTP_401_UNAUTHORIZED: {"model": OpalError}}
_READ_RESPONSES = {
    **_RESPONSES,
    status.HTTP_404_NOT_FOUND: {"model": OpalError},
}


@router.get(
    "/",
    operation_id="yolo_engines_list",
    response_model=list[Engine],
    responses=_RESPONSES,
    response_model_exclude_none=True,
)
async def list_engines(request: Request) -> list[Engine]:
    return request.app.state.engine_registry.list()


@router.post(
    "/discover",
    operation_id="yolo_engines_discover",
    response_model=list[Engine],
    responses=_RESPONSES,
    response_model_exclude_none=True,
)
async def discover_engines(request: Request) -> list[Engine]:
    return request.app.state.engine_registry.discover()


@router.get(
    "/{engine_id}",
    operation_id="yolo_engines_show",
    response_model=Engine,
    responses=_READ_RESPONSES,
    response_model_exclude_none=True,
)
async def show_engine(engine_id: str, request: Request) -> Engine:
    return request.app.state.engine_registry.describe(engine_id)


@router.get(
    "/{engine_id}/capabilities",
    operation_id="yolo_engines_capabilities",
    response_model=Capabilities,
    responses=_READ_RESPONSES,
    response_model_exclude_none=True,
)
async def engine_capabilities(engine_id: str, request: Request) -> Capabilities:
    devices = [
        device.device_id
        for device in request.app.state.hardware_service.list_devices()
        if device.available
    ]
    return request.app.state.engine_registry.capabilities(engine_id, devices)
