from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class OpalError(BaseModel):
    error: ErrorBody


class HealthReport(BaseModel):
    name: str
    version: str
    api_version: str
    status: Literal["ok", "degraded", "error"]
    live: bool
    ready: bool
    details: dict[str, Any]
    active_profile_id: str | None = None
    checked_at: str
    uptime_seconds: float = Field(ge=0)
    pending_restart: bool = False
    pending_restart_fields: list[str] = Field(default_factory=list)


class ImageInfo(BaseModel):
    width: int = Field(ge=1)
    height: int = Field(ge=1)
