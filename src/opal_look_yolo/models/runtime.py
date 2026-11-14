from __future__ import annotations

from typing import Any, Protocol

from fastapi import status

from opal_look_yolo.engines.protocol import EngineAdapter
from opal_look_yolo.engines.registry import EngineRegistry
from opal_look_yolo.errors import OpalException
from opal_look_yolo.models.repository import ModelRecord


class ModelRuntime(Protocol):
    def load_model(self, record: ModelRecord, device: str | None = None) -> Any: ...

    def unload_model(self, record: ModelRecord, handle: Any) -> None: ...


class EngineModelRuntime:
    def __init__(self, engine: EngineAdapter) -> None:
        self.engine = engine

    @classmethod
    def from_registry(cls, registry: EngineRegistry) -> EngineModelRuntime:
        return cls(registry.adapter("yolo"))

    def load_model(self, record: ModelRecord, device: str | None = None) -> Any:
        self._ensure_available()
        loader = getattr(self.engine, "load_model", None)
        if not callable(loader):
            raise self._unsupported("load")
        try:
            return loader(record.path, device=device)
        except OpalException:
            raise
        except Exception as exc:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "Model load failed",
            ) from exc

    def unload_model(self, record: ModelRecord, handle: Any) -> None:
        unloader = getattr(self.engine, "unload_model", None)
        if not callable(unloader):
            raise self._unsupported("unload")
        try:
            unloader(handle)
        except OpalException:
            raise
        except Exception as exc:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "Model unload failed",
            ) from exc

    def _ensure_available(self) -> None:
        if not self.engine.describe().available:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "YOLO engine is not available",
            )

    def _unsupported(self, operation: str) -> OpalException:
        return OpalException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "service_unavailable",
            f"YOLO engine does not support model {operation}",
        )
