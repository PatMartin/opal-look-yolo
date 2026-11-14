from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI

from opal_look_yolo.api.routes import engines, hardware, info, models
from opal_look_yolo.config import Settings
from opal_look_yolo.engines import EngineRegistry, UltralyticsYoloEngine
from opal_look_yolo.errors import register_exception_handlers
from opal_look_yolo.middleware.auth import require_bearer_auth
from opal_look_yolo.middleware.correlation import CorrelationMiddleware
from opal_look_yolo.models import LocalModelRepository, ModelRepository
from opal_look_yolo.services.hardware import (
    HardwareProvider,
    HardwareService,
    LocalHardwareProvider,
)
from opal_look_yolo.services.models import ModelService


def create_app(
    settings: Settings | None = None,
    engine_probe: Callable[[], bool] | None = None,
    engine_registry: EngineRegistry | None = None,
    hardware_provider: HardwareProvider | None = None,
    model_repository: ModelRepository | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    app = FastAPI(
        title="OPAL YOLO — Simplified Inference Adapter API",
        version=resolved_settings.service_version,
        docs_url=None,
        redoc_url=None,
    )
    resolved_registry = engine_registry or EngineRegistry([UltralyticsYoloEngine()])
    resolved_hardware = HardwareService(hardware_provider or LocalHardwareProvider())
    resolved_models = model_repository or LocalModelRepository(resolved_settings.model_dirs)

    app.state.settings = resolved_settings
    app.state.engine_registry = resolved_registry
    app.state.hardware_service = resolved_hardware
    app.state.model_service = ModelService(resolved_models)
    app.state.engine_probe = engine_probe or (
        lambda: resolved_registry.describe("yolo").available
    )

    app.add_middleware(CorrelationMiddleware)
    register_exception_handlers(app)

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_bearer_auth)])
    api.include_router(info.router)
    api.include_router(engines.router)
    api.include_router(hardware.router)
    api.include_router(models.router)
    app.include_router(api)
    return app


app = create_app()
