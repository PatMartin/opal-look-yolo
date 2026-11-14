from __future__ import annotations

import json
from io import BytesIO

from fastapi import status
from PIL import Image

from opal_look_yolo.config import Settings
from opal_look_yolo.models import EnginePrediction, LocalModelRepository
from opal_look_yolo.schemas.hardware import Hardware
from opal_look_yolo.schemas.predict import Detection

AUTH = {"Authorization": "Bearer test-token"}


class CpuProvider:
    def list_devices(self):
        return [Hardware(device_id="cpu", type="cpu", available=True)]


class FakeRuntime:
    def __init__(self):
        self.predictions = []

    def load_model(self, record, device=None):
        return {"model_id": record.model_id}

    def unload_model(self, record, handle):
        return None

    def predict(self, handle, image, confidence, device, engine_options, include_native):
        self.predictions.append(
            {
                "size": image.size,
                "confidence": confidence,
                "device": device,
                "engine_options": engine_options,
            }
        )
        return EnginePrediction(
            detections=[
                Detection(
                    class_id=1,
                    class_name="car",
                    confidence=0.8,
                    box=[0.0, 1.0, 4.0, 5.0],
                )
            ],
            native={"runtime": "fake"} if include_native else None,
        )


def repository(tmp_path):
    root = tmp_path / "models"
    root.mkdir(exist_ok=True)
    (root / "detector.pt").write_bytes(b"weights")
    return LocalModelRepository([root])


def png_bytes(width=10, height=8):
    output = BytesIO()
    Image.new("RGB", (width, height), color="green").save(output, format="PNG")
    return output.getvalue()


def envelope(width=10, height=8, **overrides):
    data = {
        "stream_id": "stream-1",
        "frame_id": "frame-1",
        "sequence": 42,
        "captured_at": "2026-11-14T12:34:56Z",
        "image": {"width": width, "height": height},
        "custom": {"origin": "test"},
    }
    data.update(overrides)
    return data


def multipart(image_data=None, frame=None, **fields):
    body = {
        "image": (
            "frame.png",
            image_data if image_data is not None else png_bytes(),
            fields.pop("image_content_type", "image/png"),
        ),
        "frame": (
            None,
            json.dumps(frame if frame is not None else envelope()),
            "application/json",
        ),
        "model_id": (None, "detector"),
    }
    for key, value in fields.items():
        if value is not None:
            body[key] = (None, str(value).lower() if isinstance(value, bool) else str(value))
    return body


def frame_client(make_client, tmp_path, settings=None):
    return make_client(
        service_settings=settings,
        model_repository=repository(tmp_path),
        model_runtime=FakeRuntime(),
        hardware_provider=CpuProvider(),
    )


def test_predict_frame_returns_detections_and_echoes_envelope(make_client, tmp_path):
    client = frame_client(make_client, tmp_path)

    response = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(
            confidence=0.6,
            device="cpu",
            include_native=True,
            engine_options=json.dumps({"imgsz": 640}),
        ),
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["engine"] == "yolo"
    assert body["model_id"] == "detector"
    assert body["image"] == {"width": 10, "height": 8}
    assert body["detections"][0]["class_name"] == "car"
    assert body["native"] == {"runtime": "fake"}
    assert body["frame"] == envelope()
    assert body["execution_id"]


def test_predict_frame_rejects_malformed_and_non_object_envelope(make_client, tmp_path):
    client = frame_client(make_client, tmp_path)

    malformed = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files={
            "image": ("frame.png", png_bytes(), "image/png"),
            "frame": (None, "{", "application/json"),
            "model_id": (None, "detector"),
        },
    )
    non_object = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files={
            "image": ("frame.png", png_bytes(), "image/png"),
            "frame": (None, "[]", "application/json"),
            "model_id": (None, "detector"),
        },
    )

    assert malformed.status_code == status.HTTP_400_BAD_REQUEST
    assert non_object.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_predict_frame_validates_envelope_and_image_dimensions(make_client, tmp_path):
    client = frame_client(make_client, tmp_path)
    missing_sequence = envelope()
    missing_sequence.pop("sequence")

    missing = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(frame=missing_sequence),
    )
    mismatch = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(frame=envelope(width=20, height=20)),
    )

    assert missing.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert mismatch.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_predict_frame_rejects_wrong_content_type_and_invalid_image(make_client, tmp_path):
    client = frame_client(make_client, tmp_path)

    wrong_type = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(image_content_type="image/gif"),
    )
    invalid = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(image_data=b"not an image"),
    )

    assert wrong_type.status_code == status.HTTP_400_BAD_REQUEST
    assert invalid.status_code == status.HTTP_400_BAD_REQUEST


def test_predict_frame_validates_engine_options(make_client, tmp_path):
    client = frame_client(make_client, tmp_path)

    malformed = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(engine_options="{"),
    )
    non_object = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(engine_options="[]"),
    )
    unknown = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(engine_options=json.dumps({"unknown": True})),
    )

    assert malformed.status_code == status.HTTP_400_BAD_REQUEST
    assert non_object.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert unknown.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_predict_frame_unknown_model_and_oversized_image(make_client, tmp_path):
    client = frame_client(make_client, tmp_path)
    missing = multipart()
    missing["model_id"] = (None, "missing")

    missing_response = client.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=missing,
    )
    assert missing_response.status_code == status.HTTP_404_NOT_FOUND

    settings = Settings(auth_disabled=False, auth_token="test-token", max_image_bytes=4)
    limited = frame_client(make_client, tmp_path, settings=settings)
    oversized = limited.post(
        "/api/v1/predict/frame",
        headers=AUTH,
        files=multipart(),
    )
    assert oversized.status_code == status.HTTP_413_CONTENT_TOO_LARGE
