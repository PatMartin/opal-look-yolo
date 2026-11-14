from __future__ import annotations

from fastapi import status

from opal_look_yolo.engines import EngineRegistry, UltralyticsYoloEngine
from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import EngineModelRuntime, LocalModelRepository
from opal_look_yolo.schemas.hardware import Hardware

AUTH = {"Authorization": "Bearer test-token"}


class CpuProvider:
    def list_devices(self):
        return [
            Hardware(device_id="cpu", type="cpu", available=True),
            Hardware(device_id="cuda:0", type="gpu", available=True),
        ]


class FakeYolo:
    def __init__(self, path):
        self.path = path
        self.devices = []
        self.closed = False

    def to(self, device):
        self.devices.append(device)
        return self

    def close(self):
        self.closed = True


def repository(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    (root / "detector.pt").write_bytes(b"weights")
    return LocalModelRepository([root])


def test_ultralytics_load_model_uses_factory_and_device(tmp_path):
    created = []
    engine = UltralyticsYoloEngine(
        model_factory=lambda path: created.append(FakeYolo(path)) or created[-1]
    )
    model_path = tmp_path / "detector.pt"
    model_path.write_bytes(b"weights")

    handle = engine.load_model(model_path, device="cuda:0")

    assert handle.path == model_path
    assert handle.device == "cuda:0"
    assert handle.model is created[0]
    assert created[0].path == str(model_path)
    assert created[0].devices == ["cuda:0"]


def test_ultralytics_unload_releases_model(tmp_path):
    model = FakeYolo("weights.pt")
    engine = UltralyticsYoloEngine(model_factory=lambda path: model)
    handle = engine.load_model(tmp_path / "weights.pt")

    engine.unload_model(handle)

    assert model.closed is True
    assert handle.model is None


def test_ultralytics_load_without_engine_returns_503(tmp_path):
    engine = UltralyticsYoloEngine()

    try:
        engine.load_model(tmp_path / "missing.pt")
    except OpalException as exc:
        assert exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        raise AssertionError("expected service unavailable")


def test_api_load_and_unload_use_ultralytics_adapter(make_client, tmp_path):
    created = []
    engine = UltralyticsYoloEngine(
        model_factory=lambda path: created.append(FakeYolo(path)) or created[-1]
    )
    client = make_client(
        engine_registry=EngineRegistry([engine]),
        model_repository=repository(tmp_path),
        model_runtime=EngineModelRuntime(engine),
        hardware_provider=CpuProvider(),
    )

    loaded = client.post(
        "/api/v1/model/detector/load",
        headers=AUTH,
        json={"device": "cpu"},
    )
    unloaded = client.post("/api/v1/model/detector/unload", headers=AUTH)

    assert loaded.status_code == status.HTTP_200_OK
    assert loaded.json()["loaded"] is True
    assert created[0].devices == ["cpu"]
    assert unloaded.status_code == status.HTTP_200_OK
    assert unloaded.json()["loaded"] is False
    assert created[0].closed is True
