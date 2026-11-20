from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from opal_look_yolo.api.routes import (
    engines,
    hardware,
    health,
    models,
    predict,
)
from opal_look_yolo.api.routes import (
    settings as settings_routes,
)
from opal_look_yolo.config import Settings
from opal_look_yolo.engines import EngineRegistry, UltralyticsYoloEngine
from opal_look_yolo.errors import register_exception_handlers
from opal_look_yolo.middleware.auth import require_bearer_auth
from opal_look_yolo.middleware.correlation import CorrelationMiddleware
from opal_look_yolo.middleware.logging import RequestLoggingMiddleware
from opal_look_yolo.models import (
    EngineModelRuntime,
    LocalModelRepository,
    ModelRepository,
    ModelRuntime,
)
from opal_look_yolo.portable_settings import apply_persisted_overrides, running_values
from opal_look_yolo.services.hardware import (
    HardwareProvider,
    HardwareService,
    LocalHardwareProvider,
)
from opal_look_yolo.services.models import ModelService
from opal_look_yolo.services.prediction import PredictionService
from opal_look_yolo.services.sources import ImageSourceResolver
from opal_look_yolo.store import Store

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    settings: Settings | None = None,
    engine_probe: Callable[[], bool] | None = None,
    engine_registry: EngineRegistry | None = None,
    hardware_provider: HardwareProvider | None = None,
    model_repository: ModelRepository | None = None,
    model_runtime: ModelRuntime | None = None,
    store: Store | None = None,
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
    resolved_runtime = model_runtime or EngineModelRuntime.from_registry(resolved_registry)

    app.state.settings = resolved_settings
    app.state.store = store or Store(resolved_settings.data_dir)
    apply_persisted_overrides(app.state.store, resolved_settings)
    app.state.running_settings = running_values(resolved_settings)
    app.state.started_monotonic = time.monotonic()
    app.state.engine_registry = resolved_registry
    app.state.hardware_service = resolved_hardware
    resolved_model_service = ModelService(
        resolved_models,
        resolved_runtime,
        resolved_hardware,
    )
    resolved_prediction = PredictionService(
        resolved_model_service,
        resolved_runtime,
        resolved_registry,
        ImageSourceResolver(
            resolved_settings.max_image_bytes,
            allow_remote_sources=resolved_settings.allow_remote_sources,
            allowed_remote_hosts=resolved_settings.allowed_remote_hosts,
            remote_timeout_seconds=resolved_settings.remote_source_timeout_seconds,
        ),
        resolved_settings.max_concurrent_predictions,
    )

    app.state.model_service = resolved_model_service
    app.state.prediction_service = resolved_prediction
    app.state.engine_probe = engine_probe or (
        lambda: resolved_registry.describe("yolo").available
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(CorrelationMiddleware)
    register_exception_handlers(app)

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_bearer_auth)])
    api.include_router(health.router)
    api.include_router(settings_routes.router)
    api.include_router(engines.router)
    api.include_router(hardware.router)
    api.include_router(models.router)
    api.include_router(predict.router)
    app.include_router(api)

    @app.get("/", include_in_schema=False)
    def spa_redirect() -> RedirectResponse:
        return RedirectResponse("/app/")

    app.mount("/app", StaticFiles(directory=_STATIC_DIR, html=True), name="spa")
    return app


app = create_app()
