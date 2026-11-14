from __future__ import annotations

from fastapi import status

from opal_look_yolo.engines import EngineRegistry
from opal_look_yolo.schemas.engines import Capabilities, Engine

AUTH = {"Authorization": "Bearer test-token"}


class FakeYoloEngine:
    def __init__(self) -> None:
        self.discoveries = 0

    def describe(self) -> Engine:
        return Engine(
            engine_id="yolo",
            name="Fake YOLO",
            available=True,
            enabled=True,
            tasks=["detect"],
            options_schema={"type": "object", "additionalProperties": False},
            version="1.0.0",
        )

    def discover(self) -> Engine:
        self.discoveries += 1
        return self.describe()

    def capabilities(self, supported_devices=None) -> Capabilities:
        return Capabilities(
            engine_id="yolo",
            tasks=["detect"],
            options_schema={"type": "object", "additionalProperties": False},
            formats=["jpg", "png"],
            supported_devices=list(supported_devices or ["cpu"]),
        )


def test_engine_list_returns_registered_engine(make_client):
    adapter = FakeYoloEngine()
    client = make_client(engine_registry=EngineRegistry([adapter]))

    response = client.get("/api/v1/engine/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [
        {
            "engine_id": "yolo",
            "name": "Fake YOLO",
            "available": True,
            "enabled": True,
            "tasks": ["detect"],
            "options_schema": {"type": "object", "additionalProperties": False},
            "version": "1.0.0",
        }
    ]


def test_engine_discover_refreshes_availability(make_client):
    adapter = FakeYoloEngine()
    client = make_client(engine_registry=EngineRegistry([adapter]))

    response = client.post("/api/v1/engine/discover", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert adapter.discoveries == 1
    assert response.json()[0]["engine_id"] == "yolo"


def test_engine_show_returns_engine(make_client):
    client = make_client(engine_registry=EngineRegistry([FakeYoloEngine()]))

    response = client.get("/api/v1/engine/yolo", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["engine_id"] == "yolo"
    assert response.json()["tasks"] == ["detect"]


def test_unknown_engine_returns_not_found(make_client):
    client = make_client(engine_registry=EngineRegistry([FakeYoloEngine()]))

    response = client.get("/api/v1/engine/onnx", headers=AUTH)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == {"engine_id": "onnx"}


def test_engine_capabilities_returns_option_schema(make_client):
    client = make_client(engine_registry=EngineRegistry([FakeYoloEngine()]))

    response = client.get("/api/v1/engine/yolo/capabilities", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "engine_id": "yolo",
        "tasks": ["detect"],
        "options_schema": {"type": "object", "additionalProperties": False},
        "formats": ["jpg", "png"],
        "supported_devices": ["cpu"],
    }


def test_unknown_engine_capabilities_returns_not_found(make_client):
    client = make_client(engine_registry=EngineRegistry([FakeYoloEngine()]))

    response = client.get("/api/v1/engine/onnx/capabilities", headers=AUTH)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"
