from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from opal_look_yolo.schemas.common import ImageInfo


class Detection(BaseModel):
    class_id: int = Field(ge=0)
    class_name: str
    confidence: float = Field(ge=0, le=1)
    box: list[float] = Field(min_length=4, max_length=4)


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["yolo"]
    model_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    confidence: float = Field(default=0.25, ge=0, le=1)
    device: str | None = None
    engine_options: dict[str, Any] | None = None
    include_native: bool = False


class PredictResult(BaseModel):
    engine: Literal["yolo"]
    model_id: str
    image: ImageInfo
    detections: list[Detection]
    native: dict[str, Any] | None = None
    execution_id: str | None = None
