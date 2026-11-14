from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from opal_look_yolo.errors import OpalException
from opal_look_yolo.schemas.common import OpalError
from opal_look_yolo.schemas.frame import FrameEnvelope, FrameResult
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


@router.post(
    "/predict",
    response_model=PredictResult,
    responses=_RESPONSES,
    response_model_exclude_none=True,
)
async def predict(request: Request, payload: PredictRequest) -> PredictResult:
    return await request.app.state.prediction_service.predict(payload)


@router.post(
    "/predict/frame",
    response_model=FrameResult,
    responses=_RESPONSES,
    response_model_exclude_none=True,
)
async def predict_frame(
    request: Request,
    image: Annotated[UploadFile, File()],
    frame: Annotated[str, Form()],
    model_id: Annotated[str, Form(min_length=1)],
    confidence: Annotated[float, Form(ge=0, le=1)] = 0.25,
    device: Annotated[str | None, Form()] = None,
    include_native: Annotated[bool, Form()] = False,
    engine_options: Annotated[str | None, Form()] = None,
) -> FrameResult:
    envelope = _parse_frame_envelope(frame)
    options = _parse_json_object(engine_options, "engine_options")
    _validate_content_type(image)

    service = request.app.state.prediction_service
    data = await image.read(request.app.state.settings.max_image_bytes + 1)
    decoded = service.resolver.decode(data)
    expected = envelope.image
    if decoded.size != (expected.width, expected.height):
        raise OpalException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_failed",
            "Frame image metadata does not match uploaded image dimensions",
            {
                "expected": {"width": expected.width, "height": expected.height},
                "actual": {"width": decoded.width, "height": decoded.height},
            },
        )

    result = await service.predict_image(
        decoded,
        model_id=model_id,
        confidence=confidence,
        device=device,
        engine_options=options,
        include_native=include_native,
    )
    return FrameResult(**result.model_dump(), frame=envelope)


def _parse_frame_envelope(raw: str) -> FrameEnvelope:
    data = _parse_json_object(raw, "frame")
    try:
        return FrameEnvelope.model_validate(data)
    except ValidationError as exc:
        raise OpalException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_failed",
            "Frame envelope validation failed",
            {"errors": jsonable_encoder(exc.errors())},
        ) from exc


def _parse_json_object(raw: str | None, field: str) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpalException(
            status.HTTP_400_BAD_REQUEST,
            "bad_request",
            f"{field} must be a JSON object",
        ) from exc
    if not isinstance(value, dict):
        raise OpalException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_failed",
            f"{field} must be a JSON object",
        )
    return value


def _validate_content_type(image: UploadFile) -> None:
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise OpalException(
            status.HTTP_400_BAD_REQUEST,
            "bad_request",
            "Frame image must be JPEG or PNG",
            {"content_type": image.content_type},
        )
