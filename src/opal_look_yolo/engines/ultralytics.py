from __future__ import annotations

import importlib.metadata
import importlib.util
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import status

from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import EnginePrediction
from opal_look_yolo.schemas.engines import Capabilities, Engine
from opal_look_yolo.schemas.predict import Detection

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

ModelFactory = Callable[[str], Any]


@dataclass
class UltralyticsModelHandle:
    path: Path
    device: str | None
    model: Any


class UltralyticsYoloEngine:
    engine_id = "yolo"
    name = "Ultralytics YOLO"
    tasks = ["detect"]
    formats = ["jpg", "jpeg", "png"]

    def __init__(self, model_factory: ModelFactory | None = None) -> None:
        self._model_factory = model_factory

    @property
    def available(self) -> bool:
        return (
            self._model_factory is not None
            or importlib.util.find_spec("ultralytics") is not None
        )

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

    def load_model(
        self,
        path: Path,
        device: str | None = None,
    ) -> UltralyticsModelHandle:
        factory = self._model_factory or self._import_model_factory()
        try:
            model = factory(str(path))
            if device is not None and callable(getattr(model, "to", None)):
                moved = model.to(device)
                if moved is not None:
                    model = moved
        except OpalException:
            raise
        except Exception as exc:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "YOLO model load failed",
            ) from exc
        return UltralyticsModelHandle(path=path, device=device, model=model)

    def unload_model(self, handle: UltralyticsModelHandle) -> None:
        model = getattr(handle, "model", handle)
        close = getattr(model, "close", None)
        if callable(close):
            close()
        if hasattr(handle, "model"):
            handle.model = None

    def predict(
        self,
        handle: UltralyticsModelHandle,
        *,
        image: Any,
        confidence: float,
        device: str | None,
        engine_options: dict[str, Any] | None,
        include_native: bool,
    ) -> EnginePrediction:
        model = getattr(handle, "model", None)
        if model is None:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "YOLO model is not loaded",
            )

        options = dict(engine_options or {})
        kwargs = {
            "source": image,
            "conf": confidence,
            "verbose": False,
            **options,
        }
        selected_device = device or handle.device
        if selected_device:
            kwargs["device"] = selected_device

        predictor = getattr(model, "predict", None)
        if not callable(predictor):
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "YOLO model does not support prediction",
            )
        results = predictor(**kwargs)
        result = results[0] if results else None
        detections = self._detections(result, model)
        native = self._native(result, detections) if include_native else None
        return EnginePrediction(detections=detections, native=native)

    def _detections(self, result: Any, model: Any) -> list[Detection]:
        if result is None or getattr(result, "boxes", None) is None:
            return []
        boxes = result.boxes
        coordinates = self._to_list(getattr(boxes, "xyxy", []))
        class_ids = self._to_list(getattr(boxes, "cls", []))
        confidences = self._to_list(getattr(boxes, "conf", []))
        names = getattr(result, "names", None) or getattr(model, "names", None) or {}

        detections: list[Detection] = []
        for box, class_value, confidence in zip(coordinates, class_ids, confidences, strict=False):
            class_id = int(float(class_value))
            detections.append(
                Detection(
                    class_id=class_id,
                    class_name=self._class_name(names, class_id),
                    confidence=max(0.0, min(1.0, float(confidence))),
                    box=[float(value) for value in box[:4]],
                )
            )
        return detections

    def _native(self, result: Any, detections: list[Detection]) -> dict[str, Any]:
        if result is None:
            return {"detections": 0}
        native = {
            "detections": len(detections),
            "names": getattr(result, "names", None),
            "orig_shape": getattr(result, "orig_shape", None),
            "speed": getattr(result, "speed", None),
        }
        return {key: self._sanitize(value) for key, value in native.items() if value is not None}

    def _class_name(self, names: Any, class_id: int) -> str:
        if isinstance(names, Mapping):
            value = names.get(class_id, names.get(str(class_id)))
            return str(value) if value is not None else str(class_id)
        if isinstance(names, Sequence) and not isinstance(names, str):
            return str(names[class_id]) if class_id < len(names) else str(class_id)
        return str(class_id)

    def _to_list(self, value: Any) -> list[Any]:
        for method in ("detach", "cpu"):
            if callable(getattr(value, method, None)):
                value = getattr(value, method)()
        if callable(getattr(value, "tolist", None)):
            value = value.tolist()
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return [value]

    def _sanitize(self, value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, Path):
            return str(value)
        if callable(getattr(value, "tolist", None)):
            return self._sanitize(value.tolist())
        if callable(getattr(value, "item", None)):
            return self._sanitize(value.item())
        if isinstance(value, Mapping):
            return {str(key): self._sanitize(item) for key, item in value.items()}
        if isinstance(value, Sequence | set):
            return [self._sanitize(item) for item in value]
        return str(value)

    def _import_model_factory(self) -> ModelFactory:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "Ultralytics YOLO engine is not installed",
            ) from exc
        return YOLO
