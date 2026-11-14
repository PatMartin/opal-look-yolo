from __future__ import annotations

from fastapi import status

from opal_look_yolo.models import LocalModelRepository
from opal_look_yolo.schemas.hardware import Hardware

AUTH = {"Authorization": "Bearer test-token"}


class FakeHardwareProvider:
    def list_devices(self) -> list[Hardware]:
        return [
            Hardware(device_id="cpu", type="cpu", available=True),
            Hardware(device_id="cuda:0", type="gpu", available=True),
        ]


class FakeRuntime:
    def __init__(self, fail_load: bool = False) -> None:
        self.fail_load = fail_load
        self.loads = []
        self.unloads = []

    def load_model(self, record, device=None):
        if self.fail_load:
            raise RuntimeError("load failed")
        handle = {"model_id": record.model_id, "device": device}
        self.loads.append(handle)
        return handle

    def unload_model(self, record, handle):
        self.unloads.append((record.model_id, handle))


def repository(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    (root / "detector.pt").write_bytes(b"weights")
    return LocalModelRepository([root])


def lifecycle_client(make_client, tmp_path, runtime=None):
    return make_client(
        model_repository=repository(tmp_path),
        model_runtime=runtime or FakeRuntime(),
        hardware_provider=FakeHardwareProvider(),
    )


def test_load_model_marks_model_loaded(make_client, tmp_path):
    runtime = FakeRuntime()
    client = lifecycle_client(make_client, tmp_path, runtime)

    response = client.post("/api/v1/model/detector/load", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["model_id"] == "detector"
    assert response.json()["loaded"] is True
    assert runtime.loads == [{"model_id": "detector", "device": None}]


def test_load_model_validates_requested_device(make_client, tmp_path):
    runtime = FakeRuntime()
    client = lifecycle_client(make_client, tmp_path, runtime)

    response = client.post(
        "/api/v1/model/detector/load",
        headers=AUTH,
        json={"device": "cuda:0"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert runtime.loads[0]["device"] == "cuda:0"


def test_load_model_rejects_unknown_device(make_client, tmp_path):
    runtime = FakeRuntime()
    client = lifecycle_client(make_client, tmp_path, runtime)

    response = client.post(
        "/api/v1/model/detector/load",
        headers=AUTH,
        json={"device": "cuda:9"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["error"]["code"] == "validation_failed"
    assert runtime.loads == []


def test_repeated_load_returns_current_state(make_client, tmp_path):
    runtime = FakeRuntime()
    client = lifecycle_client(make_client, tmp_path, runtime)
    client.post("/api/v1/model/detector/load", headers=AUTH, json={"device": "cpu"})

    response = client.post(
        "/api/v1/model/detector/load",
        headers=AUTH,
        json={"device": "cuda:0"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["loaded"] is True
    assert len(runtime.loads) == 1
    assert runtime.loads[0]["device"] == "cpu"


def test_load_rejects_unknown_model_and_extra_fields(make_client, tmp_path):
    client = lifecycle_client(make_client, tmp_path)

    missing = client.post("/api/v1/model/missing/load", headers=AUTH)
    invalid = client.post(
        "/api/v1/model/detector/load",
        headers=AUTH,
        json={"unexpected": True},
    )

    assert missing.status_code == status.HTTP_404_NOT_FOUND
    assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_runtime_load_failure_returns_service_unavailable(make_client, tmp_path):
    client = lifecycle_client(make_client, tmp_path, FakeRuntime(fail_load=True))

    response = client.post("/api/v1/model/detector/load", headers=AUTH)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["error"]["code"] == "service_unavailable"


def test_unload_model_marks_model_unloaded(make_client, tmp_path):
    runtime = FakeRuntime()
    client = lifecycle_client(make_client, tmp_path, runtime)
    client.post("/api/v1/model/detector/load", headers=AUTH)

    response = client.post("/api/v1/model/detector/unload", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["loaded"] is False
    assert runtime.unloads == [
        ("detector", {"model_id": "detector", "device": None})
    ]


def test_unload_idle_model_is_safe(make_client, tmp_path):
    runtime = FakeRuntime()
    client = lifecycle_client(make_client, tmp_path, runtime)

    response = client.post("/api/v1/model/detector/unload", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["loaded"] is False
    assert runtime.unloads == []


def test_unload_active_model_returns_conflict(make_client, tmp_path):
    client = lifecycle_client(make_client, tmp_path)
    client.post("/api/v1/model/detector/load", headers=AUTH)
    service = client.app.state.model_service

    with service.use_model("detector"):
        response = client.post("/api/v1/model/detector/unload", headers=AUTH)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["error"]["code"] == "conflict"
    assert service.is_loaded("detector") is True
