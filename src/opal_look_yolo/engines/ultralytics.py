from __future__ import annotations

import importlib.metadata
import importlib.util
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from opal_look_yolo.schemas.engines import Capabilities, Engine

YOLO_OPTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "imgsz": {"type": "integer", "minimum": 32},
        "iou": {"type": "number", "minimum": 0, "maximum": 1},
        "max_det": {"type": "integer", "minimum": 1},
        "classes": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
        },
        "half": {"type": "boolean"},
        "agnostic_nms": {"type": "boolean"},
        "augment": {"type": "boolean"},
        "verbose": {"type": "boolean"},
    },
}


class UltralyticsYoloEngine:
    engine_id = "yolo"
    name = "Ultralytics YOLO"
    tasks = ["detect"]
    formats = ["jpg", "jpeg", "png"]

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("ultralytics") is not None

    @property
    def version(self) -> str | None:
        try:
            return importlib.metadata.version("ultralytics")
        except importlib.metadata.PackageNotFoundError:
            return None

    @property
    def options_schema(self) -> dict[str, Any]:
        return deepcopy(YOLO_OPTIONS_SCHEMA)

    def describe(self) -> Engine:
        return Engine(
            engine_id="yolo",
            name=self.name,
            available=self.available,
            enabled=True,
            tasks=list(self.tasks),
            options_schema=self.options_schema,
            version=self.version,
        )

    def discover(self) -> Engine:
        return self.describe()

    def capabilities(self, supported_devices: Sequence[str] | None = None) -> Capabilities:
        return Capabilities(
            engine_id="yolo",
            tasks=list(self.tasks),
            options_schema=self.options_schema,
            formats=list(self.formats),
            supported_devices=list(supported_devices or ["cpu"]),
        )
