from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_id: str = Field(min_length=1)
    engine_id: Literal["yolo"]
    tasks: list[str]
    loaded: bool
    available: bool | None = None
    weights_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    metadata: dict[str, Any] | None = None


class LoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str | None = None
