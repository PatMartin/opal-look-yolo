from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Engine(BaseModel):
    engine_id: Literal["yolo"]
    name: str | None = None
    available: bool
    enabled: bool | None = None
    tasks: list[str]
    options_schema: dict[str, Any] | None = None
    version: str | None = None


class Capabilities(BaseModel):
    engine_id: Literal["yolo"]
    tasks: list[str]
    options_schema: dict[str, Any] = Field(default_factory=dict)
    formats: list[str] = Field(default_factory=list)
    supported_devices: list[str] = Field(default_factory=list)
