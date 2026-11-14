from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from opal_look_yolo.config import Settings
from opal_look_yolo.engines import EngineRegistry
from opal_look_yolo.main import create_app
from opal_look_yolo.models import ModelRepository, ModelRuntime
from opal_look_yolo.services.hardware import HardwareProvider


@pytest.fixture
def make_client() -> Callable[..., TestClient]:
    def factory(
        *,
        auth_disabled: bool = False,
        auth_token: str | None = "test-token",
        engine_probe: Callable[[], bool] | None = None,
        engine_registry: EngineRegistry | None = None,
        hardware_provider: HardwareProvider | None = None,
        model_repository: ModelRepository | None = None,
        model_runtime: ModelRuntime | None = None,
        service_settings: Settings | None = None,
    ) -> TestClient:
        settings = service_settings or Settings(
            auth_disabled=auth_disabled,
            auth_token=auth_token,
        )
        app = create_app(
            settings=settings,
            engine_probe=engine_probe or (lambda: True),
            engine_registry=engine_registry,
            hardware_provider=hardware_provider,
            model_repository=model_repository,
            model_runtime=model_runtime,
        )
        return TestClient(app)

    return factory
