from __future__ import annotations

from fastapi import status
from PIL import Image

from opal_look_yolo.engines import EngineRegistry, UltralyticsYoloEngine
from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import EngineModelRuntime, LocalModelRepository
from opal_look_yolo.schemas.hardware import Hardware

AUTH = {"Authorization": "Bearer test-token"}


class CpuProvider:
    def list_devices(self):
        return [Hardware(device_id="cpu", type="cpu", available=True)]


class Values:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class Boxes:
    def __init__(self):
        self.xyxy = Values([[1.0, 2.0, 9.0, 8.0], [3.0, 4.0, 7.0, 6.0]])
        self.cls = Values([0.0, 1.0])
        self.conf = Values([0.95, 0.55])


class Result:
    def __init__(self):
        self.boxes = Boxes()
        self.names = {0: "person", 1: "car"}
        self.orig_shape = (8, 10)
        self.speed = {"inference": 4.2}


class FakeYolo:
    def __init__(self, path):
        self.path = path
        self.names = {0: "person", 1: "car"}
        self.calls = []
        self.devices = []

    def to(self, device):
        self.devices.append(device)
        return self

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [Result()]

    def close(self):
        return None


def make_image(path):
    Image.new("RGB", (10, 8), color="red").save(path, format="PNG")
    return path


def repository(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    (root / "detector.pt").write_bytes(b"weights")
    return LocalModelRepository([root])


def test_ultralytics_predict_normalizes_results(tmp_path):
    model = FakeYolo("weights.pt")
    engine = UltralyticsYoloEngine(model_factory=lambda path: model)
    handle = engine.load_model(tmp_path / "weights.pt", device="cpu")
    image = Image.new("RGB", (10, 8), color="red")

    result = engine.predict(
        handle,
        image=image,
        confidence=0.5,
        device=None,
        engine_options={"imgsz": 640, "iou": 0.4},
        include_native=True,
    )

    assert [detection.model_dump() for detection in result.detections] == [
        {
            "class_id": 0,
            "class_name": "person",
            "confidence": 0.95,
            "box": [1.0, 2.0, 9.0, 8.0],
        },
        {
            "class_id": 1,
            "class_name": "car",
            "confidence": 0.55,
            "box": [3.0, 4.0, 7.0, 6.0],
        },
    ]
    assert model.calls[0]["source"] is image
    assert model.calls[0]["conf"] == 0.5
    assert model.calls[0]["device"] == "cpu"
    assert model.calls[0]["imgsz"] == 640
    assert model.calls[0]["iou"] == 0.4
    assert result.native["detections"] == 2
    assert result.native["names"] == {"0": "person", "1": "car"}


def test_api_predict_uses_ultralytics_adapter(make_client, tmp_path):
    model = FakeYolo("weights.pt")
    engine = UltralyticsYoloEngine(model_factory=lambda path: model)
    client = make_client(
        engine_registry=EngineRegistry([engine]),
        model_repository=repository(tmp_path),
        model_runtime=EngineModelRuntime(engine),
        hardware_provider=CpuProvider(),
    )
    source = make_image(tmp_path / "source.png")

    response = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json={
            "engine": "yolo",
            "model_id": "detector",
            "source": str(source),
            "confidence": 0.3,
            "device": "cpu",
            "engine_options": {"max_det": 5},
            "include_native": True,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["detections"][0]["class_name"] == "person"
    assert body["image"] == {"width": 10, "height": 8}
    assert body["native"]["detections"] == 2
    assert model.calls[0]["device"] == "cpu"
    assert model.calls[0]["max_det"] == 5


def test_engine_model_runtime_maps_prediction_failure_to_503(tmp_path):
    class FailingYolo(FakeYolo):
        def predict(self, **kwargs):
            raise RuntimeError("backend failed")

    engine = UltralyticsYoloEngine(model_factory=lambda path: FailingYolo(path))
    runtime = EngineModelRuntime(engine)
    record = LocalModelRepository([repository(tmp_path).roots[0]]).get_record("detector")
    handle = runtime.load_model(record)
    image = Image.new("RGB", (2, 2))

    try:
        runtime.predict(
            handle,
            image=image,
            confidence=0.25,
            device=None,
            engine_options={},
            include_native=False,
        )
    except OpalException as exc:
        assert exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        raise AssertionError("expected service unavailable")
