from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import status
from jsonschema import ValidationError, validators
from PIL import Image

from opal_look_yolo.engines import EngineRegistry
from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import EnginePrediction
from opal_look_yolo.schemas.common import ImageInfo
from opal_look_yolo.schemas.predict import PredictRequest, PredictResult
from opal_look_yolo.services.models import ModelService
from opal_look_yolo.services.sources import ImageSourceResolver


class PredictionRuntime(Protocol):
    def predict(
        self,
        handle: Any,
        image: Image.Image,
        confidence: float,
        device: str | None,
        engine_options: dict[str, Any] | None,
        include_native: bool,
    ) -> EnginePrediction: ...


class BoundedInferenceCapacity:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self._active = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        async with self._lock:
            if self._active >= self.maximum:
                raise OpalException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "capacity_exceeded",
                    "Bounded inference capacity exhausted",
                    {"max_concurrent_predictions": self.maximum},
                )
            self._active += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active -= 1


class PredictionService:
    def __init__(
        self,
        models: ModelService,
        runtime: PredictionRuntime,
        engines: EngineRegistry,
        resolver: ImageSourceResolver,
        max_concurrent: int,
    ) -> None:
        self.models = models
        self.runtime = runtime
        self.engines = engines
        self.resolver = resolver
        self.capacity = BoundedInferenceCapacity(max_concurrent)

    async def predict(self, request: PredictRequest) -> PredictResult:
        resolved = self.resolver.resolve(request.source)
        return await self.predict_image(
            resolved.image,
            model_id=request.model_id,
            confidence=request.confidence,
            device=request.device,
            engine_options=request.engine_options,
            include_native=request.include_native,
        )

    async def predict_image(
        self,
        image: Image.Image,
        *,
        model_id: str,
        confidence: float,
        device: str | None,
        engine_options: dict[str, Any] | None,
        include_native: bool,
    ) -> PredictResult:
        self._validate_options(engine_options or {})
        async with self.capacity.acquire():
            with self.models.use_model(model_id, device) as loaded:
                result = await asyncio.to_thread(
                    self.runtime.predict,
                    loaded.handle,
                    image,
                    confidence,
                    device,
                    engine_options,
                    include_native,
                )

        width, height = image.size
        return PredictResult(
            engine="yolo",
            model_id=model_id,
            image=ImageInfo(width=width, height=height),
            detections=result.detections,
            native=result.native if include_native else None,
            execution_id=uuid.uuid4().hex,
        )

    def _validate_options(self, options: dict[str, Any]) -> None:
        schema = self.engines.capabilities("yolo").options_schema
        try:
            validator = validators.validator_for(schema)(schema)
            validator.validate(options)
        except ValidationError as exc:
            raise OpalException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "validation_failed",
                "Invalid YOLO engine option",
                {
                    "option": ".".join(str(part) for part in exc.absolute_path),
                    "reason": exc.message,
                },
            ) from exc
