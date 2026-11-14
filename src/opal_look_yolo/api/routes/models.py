from __future__ import annotations

from fastapi import APIRouter, Request, status

from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.models import Model

router = APIRouter(prefix="/model", tags=["models"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": OpalError},
    status.HTTP_404_NOT_FOUND: {"model": OpalError},
}


@router.get("/", response_model=list[Model], responses=_RESPONSES)
async def list_models(request: Request) -> list[Model]:
    return request.app.state.model_service.list_models()


@router.get("/{model_id}", response_model=Model, responses=_RESPONSES)
async def show_model(model_id: str, request: Request) -> Model:
    return request.app.state.model_service.get_model(model_id)
