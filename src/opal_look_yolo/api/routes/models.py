from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Request, status

from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.models import LoadRequest, Model

router = APIRouter(prefix="/model", tags=["models"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": OpalError},
    status.HTTP_404_NOT_FOUND: {"model": OpalError},
    status.HTTP_409_CONFLICT: {"model": OpalError},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": OpalError},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": OpalError},
}


@router.get("/", response_model=list[Model], responses=_RESPONSES)
async def list_models(request: Request) -> list[Model]:
    return request.app.state.model_service.list_models()


@router.get("/{model_id}", response_model=Model, responses=_RESPONSES)
async def show_model(model_id: str, request: Request) -> Model:
    return request.app.state.model_service.get_model(model_id)


@router.post("/{model_id}/load", response_model=Model, responses=_RESPONSES)
async def load_model(
    model_id: str,
    request: Request,
    payload: Annotated[LoadRequest | None, Body()] = None,
) -> Model:
    device = payload.device if payload else None
    return request.app.state.model_service.load_model(model_id, device=device)


@router.post("/{model_id}/unload", response_model=Model, responses=_RESPONSES)
async def unload_model(model_id: str, request: Request) -> Model:
    return request.app.state.model_service.unload_model(model_id)
