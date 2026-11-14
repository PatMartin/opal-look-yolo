from __future__ import annotations

from collections.abc import Iterable, Sequence

from fastapi import status

from opal_look_yolo.engines.protocol import EngineAdapter
from opal_look_yolo.errors import OpalException
from opal_look_yolo.schemas.engines import Capabilities, Engine


class EngineRegistry:
    def __init__(self, engines: Iterable[EngineAdapter]) -> None:
        self._engines = {engine.describe().engine_id: engine for engine in engines}

    def list(self) -> list[Engine]:
        return [engine.describe() for engine in self._engines.values()]

    def discover(self) -> list[Engine]:
        return [engine.discover() for engine in self._engines.values()]

    def describe(self, engine_id: str) -> Engine:
        return self._adapter(engine_id).describe()

    def capabilities(
        self,
        engine_id: str,
        supported_devices: Sequence[str] | None = None,
    ) -> Capabilities:
        return self._adapter(engine_id).capabilities(supported_devices)

    def adapter(self, engine_id: str) -> EngineAdapter:
        return self._adapter(engine_id)

    def _adapter(self, engine_id: str) -> EngineAdapter:
        try:
            return self._engines[engine_id]
        except KeyError as exc:
            raise OpalException(
                status.HTTP_404_NOT_FOUND,
                "not_found",
                "Engine not found",
                {"engine_id": engine_id},
            ) from exc
