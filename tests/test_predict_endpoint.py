from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import status
from PIL import Image

from opal_look_yolo.config import Settings
from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import EnginePrediction, LocalModelRepository
from opal_look_yolo.schemas.hardware import Hardware
from opal_look_yolo.schemas.predict import Detection

AUTH = {"Authorization": "Bearer test-token"}


class CpuProvider:
    def list_devices(self):
        return [Hardware(device_id="cpu", type="cpu", available=True)]


class FakeRuntime:
    def __init__(self, fail: bool = False, started: Event | None = None, release=None):
        self.fail = fail
        self.started = started
        self.release = release
        self.predictions = []

    def load_model(self, record, device=None):
        return {"model_id": record.model_id, "device": device}

    def unload_model(self, record, handle):
        return None

    def predict(self, handle, image, confidence, device, engine_options, include_native):
        if self.started:
            self.started.set()
            self.release.wait(timeout=5)
        if self.fail:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "Prediction failed",
            )
        self.predictions.append(
            {
                "handle": handle,
                "size": image.size,
                "confidence": confidence,
                "device": device,
                "engine_options": engine_options,
            }
        )
        return EnginePrediction(
            detections=[
                Detection(
                    class_id=2,
                    class_name="person",
                    confidence=0.91,
                    box=[1.0, 2.0, 7.0, 9.0],
                )
            ],
            native={"boxes": 1} if include_native else None,
        )


def repository(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    (root / "detector.pt").write_bytes(b"weights")
    return LocalModelRepository([root])


def image_path(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (10, 8), color="blue").save(path, format="PNG")
    return path


def payload(source, **overrides):
    data = {
        "engine": "yolo",
        "model_id": "detector",
        "source": str(source),
        "confidence": 0.4,
        "device": "cpu",
        "engine_options": {"imgsz": 640},
    }
    data.update(overrides)
    return data


def predict_client(make_client, tmp_path, runtime=None, settings=None):
    return make_client(
        service_settings=settings,
        model_repository=repository(tmp_path),
        model_runtime=runtime or FakeRuntime(),
        hardware_provider=CpuProvider(),
    )


def test_predict_returns_normalized_detections(make_client, tmp_path):
    runtime = FakeRuntime()
    client = predict_client(make_client, tmp_path, runtime)
    request = payload(image_path(tmp_path), include_native=True)

    response = client.post("/api/v1/predict", headers=AUTH, json=request)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["engine"] == "yolo"
    assert body["model_id"] == "detector"
    assert body["image"] == {"width": 10, "height": 8}
    assert body["detections"] == [
        {
            "class_id": 2,
            "class_name": "person",
            "confidence": 0.91,
            "box": [1.0, 2.0, 7.0, 9.0],
        }
    ]
    assert body["native"] == {"boxes": 1}
    assert body["execution_id"]
    assert runtime.predictions[0]["device"] == "cpu"


def test_predict_omits_native_when_not_requested(make_client, tmp_path):
    client = predict_client(make_client, tmp_path)

    response = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(image_path(tmp_path)),
    )

    assert response.status_code == status.HTTP_200_OK
    assert "native" not in response.json()


def test_predict_rejects_invalid_request_and_engine(make_client, tmp_path):
    client = predict_client(make_client, tmp_path)
    source = image_path(tmp_path)

    extra = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(source, unexpected=True),
    )
    wrong_engine = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(source, engine="other"),
    )

    assert extra.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert wrong_engine.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_predict_rejects_unknown_option_device_and_remote_source(make_client, tmp_path):
    client = predict_client(make_client, tmp_path)
    source = image_path(tmp_path)

    bad_option = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(source, engine_options={"unknown": True}),
    )
    bad_device = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(source, device="cuda:9"),
    )
    remote = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload("https://example.invalid/image.png"),
    )

    assert bad_option.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert bad_device.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert remote.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_predict_unknown_model_invalid_image_and_malformed_json(make_client, tmp_path):
    client = predict_client(make_client, tmp_path)
    source = image_path(tmp_path)
    invalid = tmp_path / "invalid.png"
    invalid.write_bytes(b"invalid")

    missing_model = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(source, model_id="missing"),
    )
    bad_image = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(invalid),
    )
    malformed = client.post(
        "/api/v1/predict",
        headers={**AUTH, "Content-Type": "application/json"},
        content="{",
    )

    assert missing_model.status_code == status.HTTP_404_NOT_FOUND
    assert bad_image.status_code == status.HTTP_400_BAD_REQUEST
    assert malformed.status_code == status.HTTP_400_BAD_REQUEST
    assert malformed.json()["error"]["code"] == "bad_request"


def test_predict_oversized_image_returns_payload_too_large(make_client, tmp_path):
    settings = Settings(
        auth_disabled=False,
        auth_token="test-token",
        max_image_bytes=4,
    )
    client = predict_client(make_client, tmp_path, settings=settings)

    response = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(image_path(tmp_path)),
    )

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert response.json()["error"]["code"] == "payload_too_large"


def test_predict_capacity_exhaustion_returns_429(make_client, tmp_path):
    started = Event()
    release = Event()
    runtime = FakeRuntime(started=started, release=release)
    settings = Settings(
        auth_disabled=False,
        auth_token="test-token",
        max_concurrent_predictions=1,
    )
    client = predict_client(make_client, tmp_path, runtime, settings)
    request = payload(image_path(tmp_path))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, "/api/v1/predict", headers=AUTH, json=request)
        assert started.wait(timeout=5)
        second = client.post("/api/v1/predict", headers=AUTH, json=request)
        release.set()
        first_response = first.result(timeout=5)

    assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert second.json()["error"]["code"] == "capacity_exceeded"
    assert first_response.status_code == status.HTTP_200_OK


def test_predict_engine_failure_returns_503(make_client, tmp_path):
    client = predict_client(make_client, tmp_path, FakeRuntime(fail=True))

    response = client.post(
        "/api/v1/predict",
        headers=AUTH,
        json=payload(image_path(tmp_path)),
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["error"]["code"] == "service_unavailable"
