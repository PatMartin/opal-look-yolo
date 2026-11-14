from __future__ import annotations

from fastapi import APIRouter, Request, status

from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.engines import Capabilities, Engine

router = APIRouter(prefix="/engine", tags=["engines"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": OpalError},
    status.HTTP_404_NOT_FOUND: {"model": OpalError},
}


@router.get("/", response_model=list[Engine], responses=_RESPONSES)
async def list_engines(request: Request) -> list[Engine]:
    return request.app.state.engine_registry.list()


@router.post("/discover", response_model=list[Engine], responses=_RESPONSES)
async def discover_engines(request: Request) -> list[Engine]:
    return request.app.state.engine_registry.discover()


@router.get("/{engine_id}", response_model=Engine, responses=_RESPONSES)
async def show_engine(engine_id: str, request: Request) -> Engine:
    return request.app.state.engine_registry.describe(engine_id)


@router.get(
    "/{engine_id}/capabilities",
    response_model=Capabilities,
    responses=_RESPONSES,
)
async def engine_capabilities(engine_id: str, request: Request) -> Capabilities:
    devices = [
        device.device_id
        for device in request.app.state.hardware_service.list_devices()
        if device.available
    ]
    return request.app.state.engine_registry.capabilities(engine_id, devices)
