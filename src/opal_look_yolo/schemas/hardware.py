from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Hardware(BaseModel):
    device_id: str = Field(min_length=1)
    type: Literal["cpu", "gpu", "accelerator"]
    available: bool
    memory_mb: int | None = Field(default=None, ge=0)
    name: str | None = None
