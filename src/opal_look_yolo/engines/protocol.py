from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from opal_look_yolo.schemas.engines import Capabilities, Engine


class EngineAdapter(Protocol):
    def describe(self) -> Engine: ...

    def discover(self) -> Engine: ...

    def capabilities(self, supported_devices: Sequence[str] | None = None) -> Capabilities: ...
