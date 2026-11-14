from __future__ import annotations

import importlib.util
from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI

from opal_look_yolo.api.routes import info
from opal_look_yolo.config import Settings
from opal_look_yolo.errors import register_exception_handlers
from opal_look_yolo.middleware.auth import require_bearer_auth
from opal_look_yolo.middleware.correlation import CorrelationMiddleware


def _default_engine_probe() -> bool:
    return importlib.util.find_spec("ultralytics") is not None


def create_app(
    settings: Settings | None = None,
    engine_probe: Callable[[], bool] | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    app = FastAPI(
        title="OPAL YOLO — Simplified Inference Adapter API",
        version=resolved_settings.service_version,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = resolved_settings
    app.state.engine_probe = engine_probe or _default_engine_probe

    app.add_middleware(CorrelationMiddleware)
    register_exception_handlers(app)

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_bearer_auth)])
    api.include_router(info.router)
    app.include_router(api)
    return app


app = create_app()
