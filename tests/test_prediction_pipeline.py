from __future__ import annotations

import asyncio

import pytest
from fastapi import status
from PIL import Image

from opal_look_yolo.engines import EngineRegistry, UltralyticsYoloEngine
from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import EnginePrediction, LocalModelRepository
from opal_look_yolo.schemas.hardware import Hardware
from opal_look_yolo.schemas.predict import Detection, PredictRequest
from opal_look_yolo.services.hardware import HardwareService
from opal_look_yolo.services.models import ModelService
from opal_look_yolo.services.prediction import (
    BoundedInferenceCapacity,
    PredictionService,
)
from opal_look_yolo.services.sources import ImageSourceResolver


class CpuProvider:
    def list_devices(self):
        return [Hardware(device_id="cpu", type="cpu", available=True)]


class FakeRuntime:
    def __init__(self) -> None:
        self.loads = []
        self.predictions = []

    def load_model(self, record, device=None):
        handle = {"model_id": record.model_id}
        self.loads.append(handle)
        return handle

    def unload_model(self, record, handle):
        return None

    def predict(
        self,
        handle,
        image,
        confidence,
        device,
        engine_options,
        include_native,
    ):
        self.predictions.append(
            {
                "handle": handle,
                "size": image.size,
                "confidence": confidence,
                "device": device,
                "engine_options": engine_options,
                "include_native": include_native,
            }
        )
        return EnginePrediction(
            detections=[
                Detection(
                    class_id=0,
                    class_name="object",
                    confidence=0.9,
                    box=[1.0, 2.0, 10.0, 20.0],
                )
            ],
            native={"backend": "fake"} if include_native else None,
        )


def make_service(tmp_path, max_image_bytes=10 * 1024 * 1024):
    model_root = tmp_path / "models"
    model_root.mkdir(exist_ok=True)
    (model_root / "detector.pt").write_bytes(b"weights")
    runtime = FakeRuntime()
    models = ModelService(
        LocalModelRepository([model_root]),
        runtime,
        HardwareService(CpuProvider()),
    )
    service = PredictionService(
        models,
        runtime,
        EngineRegistry([UltralyticsYoloEngine()]),
        ImageSourceResolver(max_image_bytes),
        max_concurrent=1,
    )
    return service, runtime


def make_image(path):
    Image.new("RGB", (8, 6), color=(255, 0, 0)).save(path, format="PNG")


def test_prediction_service_loads_model_and_normalizes_result(tmp_path):
    service, runtime = make_service(tmp_path)
    source = tmp_path / "image.png"
    make_image(source)
    request = PredictRequest(
        engine="yolo",
        model_id="detector",
        source=str(source),
        confidence=0.5,
        device="cpu",
        engine_options={"imgsz": 640},
        include_native=True,
    )

    result = asyncio.run(service.predict(request))

    assert result.engine == "yolo"
    assert result.model_id == "detector"
    assert result.image.width == 8
    assert result.image.height == 6
    assert result.detections[0].class_name == "object"
    assert result.native == {"backend": "fake"}
    assert result.execution_id
    assert runtime.loads == [{"model_id": "detector"}]
    assert runtime.predictions[0]["confidence"] == 0.5
    assert runtime.predictions[0]["device"] == "cpu"


def test_source_resolver_accepts_file_uri(tmp_path):
    source = tmp_path / "image.png"
    make_image(source)

    resolved = ImageSourceResolver(1024).resolve(source.as_uri())

    assert resolved.image.size == (8, 6)
    assert resolved.path == source


def test_source_resolver_rejects_remote_and_missing_sources(tmp_path):
    resolver = ImageSourceResolver(1024)

    with pytest.raises(OpalException) as remote:
        resolver.resolve("https://example.invalid/image.png")
    with pytest.raises(OpalException) as missing:
        resolver.resolve(str(tmp_path / "missing.png"))

    assert remote.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert missing.value.status_code == status.HTTP_404_NOT_FOUND


def test_source_resolver_rejects_invalid_and_oversized_images(tmp_path):
    invalid = tmp_path / "invalid.png"
    invalid.write_bytes(b"not an image")
    oversized_resolver = ImageSourceResolver(4)

    with pytest.raises(OpalException) as bad:
        ImageSourceResolver(1024).resolve(str(invalid))
    with pytest.raises(OpalException) as large:
        oversized_resolver.resolve(str(invalid))

    assert bad.value.status_code == status.HTTP_400_BAD_REQUEST
    assert large.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE


def test_engine_options_are_checked_against_capability_schema(tmp_path):
    service, _ = make_service(tmp_path)

    service._validate_options({"imgsz": 640, "iou": 0.5})
    with pytest.raises(OpalException) as exc:
        service._validate_options({"unknown": True})

    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_bounded_capacity_rejects_when_exhausted():
    capacity = BoundedInferenceCapacity(1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def scenario():
        async def hold():
            async with capacity.acquire():
                entered.set()
                await release.wait()

        task = asyncio.create_task(hold())
        await entered.wait()
        with pytest.raises(OpalException) as exc:
            async with capacity.acquire():
                pass
        release.set()
        await task
        return exc.value

    failure = asyncio.run(scenario())
    assert failure.status_code == status.HTTP_429_TOO_MANY_REQUESTS
