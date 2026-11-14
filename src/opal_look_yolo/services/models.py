from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import status

from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import ModelRecord, ModelRepository, ModelRuntime
from opal_look_yolo.schemas.models import Model
from opal_look_yolo.services.hardware import HardwareService


@dataclass
class LoadedModel:
    record: ModelRecord
    device: str | None
    handle: Any
    active_predictions: int = 0


class ModelService:
    def __init__(
        self,
        repository: ModelRepository,
        runtime: ModelRuntime,
        hardware: HardwareService,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.hardware = hardware
        self._loaded: dict[str, LoadedModel] = {}
        self._lock = threading.RLock()

    def list_models(self) -> list[Model]:
        with self._lock:
            loaded_ids = set(self._loaded)
        return [
            record.to_model(loaded=record.model_id in loaded_ids)
            for record in self.repository.list_records()
        ]

    def get_model(self, model_id: str) -> Model:
        return self._get_record(model_id).to_model(loaded=self.is_loaded(model_id))

    def is_loaded(self, model_id: str) -> bool:
        with self._lock:
            return model_id in self._loaded

    def load_model(self, model_id: str, device: str | None = None) -> Model:
        return self._ensure_loaded(model_id, device).record.to_model(loaded=True)

    def unload_model(self, model_id: str) -> Model:
        record = self._get_record(model_id)
        with self._lock:
            loaded = self._loaded.get(model_id)
            if loaded is None:
                return record.to_model(loaded=False)
            if loaded.active_predictions:
                raise OpalException(
                    status.HTTP_409_CONFLICT,
                    "conflict",
                    "Model is in active use",
                    {"model_id": model_id},
                )

        self._unload(record, loaded.handle)
        with self._lock:
            self._loaded.pop(model_id, None)
        return record.to_model(loaded=False)

    @contextmanager
    def use_model(
        self,
        model_id: str,
        device: str | None = None,
    ) -> Iterator[LoadedModel]:
        loaded = self._ensure_loaded(model_id, device)
        with self._lock:
            loaded.active_predictions += 1
        try:
            yield loaded
        finally:
            with self._lock:
                loaded.active_predictions -= 1

    def _ensure_loaded(self, model_id: str, device: str | None) -> LoadedModel:
        record = self._get_record(model_id)
        self._validate_device(device)
        with self._lock:
            loaded = self._loaded.get(model_id)
            if loaded is not None:
                return loaded

        try:
            handle = self.runtime.load_model(record, device=device)
        except OpalException:
            raise
        except Exception as exc:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "Model load failed",
            ) from exc

        loaded = LoadedModel(record=record, device=device, handle=handle)
        with self._lock:
            return self._loaded.setdefault(model_id, loaded)

    def _unload(self, record: ModelRecord, handle: Any) -> None:
        try:
            self.runtime.unload_model(record, handle)
        except OpalException:
            raise
        except Exception as exc:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "Model unload failed",
            ) from exc

    def _get_record(self, model_id: str) -> ModelRecord:
        record = self.repository.get_record(model_id)
        if record is None:
            raise OpalException(
                status.HTTP_404_NOT_FOUND,
                "not_found",
                "Model not found",
                {"model_id": model_id},
            )
        return record

    def _validate_device(self, device_id: str | None) -> None:
        if device_id is None:
            return
        try:
            device = self.hardware.get_device(device_id)
        except OpalException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            raise OpalException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "validation_failed",
                "Unknown hardware device",
                {
                "device": device_id,
            },
        ) from exc
        if not device.available:
            raise OpalException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "validation_failed",
                "Hardware device is not available",
                {"device": device_id},
            )
