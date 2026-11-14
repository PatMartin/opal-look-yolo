from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from opal_look_yolo.schemas.common import ImageInfo
from opal_look_yolo.schemas.predict import PredictResult


class FrameEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    stream_id: str
    frame_id: str
    sequence: int = Field(ge=0)
    captured_at: str
    image: ImageInfo
    transaction_id: str | None = None
    request_id: str | None = None
    causation_id: str | None = None

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: str) -> str:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("captured_at must be an ISO-8601 date-time") from exc
        return value


class FrameResult(PredictResult):
    frame: FrameEnvelope
