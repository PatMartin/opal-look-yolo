from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class OpalError(BaseModel):
    error: ErrorBody


class ServiceInfo(BaseModel):
    name: Literal["opal-yolo"]
    version: str
    engine_id: Literal["yolo"]


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    engine_available: bool
    detail: str | None = None


class ImageInfo(BaseModel):
    width: int = Field(ge=1)
    height: int = Field(ge=1)
