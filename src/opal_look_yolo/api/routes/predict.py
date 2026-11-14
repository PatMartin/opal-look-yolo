from __future__ import annotations

from fastapi import APIRouter, Request, status

from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.predict import PredictRequest, PredictResult

router = APIRouter(tags=["predict"])

_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {"model": OpalError},
    status.HTTP_401_UNAUTHORIZED: {"model": OpalError},
    status.HTTP_404_NOT_FOUND: {"model": OpalError},
    status.HTTP_413_CONTENT_TOO_LARGE: {"model": OpalError},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": OpalError},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": OpalError},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": OpalError},
}


@router.post("/predict", response_model=PredictResult, responses=_RESPONSES,
    response_model_exclude_none=True,
)
async def predict(request: Request, payload: PredictRequest) -> PredictResult:
    return await request.app.state.prediction_service.predict(payload)
