from __future__ import annotations

from fastapi import status

from opal_look_yolo.engines import EngineRegistry, UltralyticsYoloEngine
from opal_look_yolo.schemas.hardware import Hardware
from opal_look_yolo.services.hardware import LocalHardwareProvider

AUTH = {"Authorization": "Bearer test-token"}


class FakeHardwareProvider:
    def list_devices(self) -> list[Hardware]:
        return [
            Hardware(device_id="cpu", type="cpu", available=True, name="CPU"),
            Hardware(
                device_id="cuda:0",
                type="gpu",
                available=True,
                memory_mb=8192,
                name="Fake GPU",
            ),
        ]


def test_hardware_list_returns_devices(make_client):
    client = make_client(hardware_provider=FakeHardwareProvider())

    response = client.get("/api/v1/hardware/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [
        {
            "device_id": "cpu",
            "type": "cpu",
            "available": True,
            "name": "CPU",
        },
        {
            "device_id": "cuda:0",
            "type": "gpu",
            "available": True,
            "memory_mb": 8192,
            "name": "Fake GPU",
        },
    ]


def test_hardware_show_returns_device(make_client):
    client = make_client(hardware_provider=FakeHardwareProvider())

    response = client.get("/api/v1/hardware/cuda:0", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["device_id"] == "cuda:0"
    assert response.json()["type"] == "gpu"


def test_unknown_hardware_returns_not_found(make_client):
    client = make_client(hardware_provider=FakeHardwareProvider())

    response = client.get("/api/v1/hardware/cuda:9", headers=AUTH)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == {"device_id": "cuda:9"}


def test_local_provider_always_exposes_cpu():
    devices = LocalHardwareProvider().list_devices()

    assert devices[0].device_id == "cpu"
    assert devices[0].type == "cpu"
    assert devices[0].available is True


def test_engine_capabilities_include_available_hardware(make_client):
    client = make_client(
        engine_registry=EngineRegistry([UltralyticsYoloEngine()]),
        hardware_provider=FakeHardwareProvider(),
    )

    response = client.get("/api/v1/engine/yolo/capabilities", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["supported_devices"] == ["cpu", "cuda:0"]
