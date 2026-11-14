from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Request, status

from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.models import LoadRequest, Model

router = APIRouter(prefix="/model", tags=["models"])

_RESPONSES = {status.HTTP_401_UNAUTHORIZED: {"model": OpalError}}
_READ_RESPONSES = {
    **_RESPONSES,
    status.HTTP_404_NOT_FOUND: {"model": OpalError},
}
_LOAD_RESPONSES = {
    **_READ_RESPONSES,
    status.HTTP_409_CONFLICT: {"model": OpalError},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": OpalError},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": OpalError},
}
_UNLOAD_RESPONSES = {
    **_READ_RESPONSES,
    status.HTTP_409_CONFLICT: {"model": OpalError},
}


@router.get(
    "/",
    operation_id="yolo_models_list",
    response_model=list[Model],
    responses=_RESPONSES,
    response_model_exclude_none=True,
)
async def list_models(request: Request) -> list[Model]:
    return request.app.state.model_service.list_models()


@router.get(
    "/{model_id}",
    operation_id="yolo_models_show",
    response_model=Model,
    responses=_READ_RESPONSES,
    response_model_exclude_none=True,
)
async def show_model(model_id: str, request: Request) -> Model:
    return request.app.state.model_service.get_model(model_id)


@router.post(
    "/{model_id}/load",
    operation_id="yolo_models_load",
    response_model=Model,
    responses=_LOAD_RESPONSES,
    response_model_exclude_none=True,
)
async def load_model(
    model_id: str,
    request: Request,
    payload: Annotated[LoadRequest | None, Body()] = None,
) -> Model:
    device = payload.device if payload else None
    return request.app.state.model_service.load_model(model_id, device=device)


@router.post(
    "/{model_id}/unload",
    operation_id="yolo_models_unload",
    response_model=Model,
    responses=_UNLOAD_RESPONSES,
    response_model_exclude_none=True,
)
async def unload_model(model_id: str, request: Request) -> Model:
    return request.app.state.model_service.unload_model(model_id)
