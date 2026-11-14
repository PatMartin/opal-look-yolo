from __future__ import annotations

from fastapi import APIRouter, Request, status

from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.hardware import Hardware

router = APIRouter(prefix="/hardware", tags=["hardware"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": OpalError},
    status.HTTP_404_NOT_FOUND: {"model": OpalError},
}


@router.get("/", response_model=list[Hardware], responses=_RESPONSES)
async def list_hardware(request: Request) -> list[Hardware]:
    return request.app.state.hardware_service.list_devices()


@router.get("/{device_id}", response_model=Hardware, responses=_RESPONSES)
async def show_hardware(device_id: str, request: Request) -> Hardware:
    return request.app.state.hardware_service.get_device(device_id)
