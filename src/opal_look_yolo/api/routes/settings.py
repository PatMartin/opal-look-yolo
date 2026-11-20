"""Portable settings endpoints: whole-map GET and per-key GET/PUT/DELETE.

Setting records carry kernel provenance: `value` is the effective value
after environment/.env overlays, `configured_value` the persisted desired
value, `source` the winning layer (environment > dotenv > persisted >
default). All registered keys are restart-required: writes persist the
desired value and surface through `pending_restart` until the service
restarts (see portable_settings).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from opal_look_yolo.errors import OpalException
from opal_look_yolo.portable_settings import (
    SETTINGS_KEYS,
    PortableSettings,
    PortableSettingsPatch,
    SettingUpdateBody,
    effective_settings,
    env_overlays,
)
from opal_look_yolo.precondition import check_if_match

router = APIRouter(tags=["config"])

_KEY_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)*$")


def _check_key_path(key: str) -> None:
    if not _KEY_PATH.match(key):
        raise OpalException(422, "validation_failed", f"Invalid setting key path: {key!r}")


def _known_key(key: str) -> None:
    if key not in SETTINGS_KEYS:
        raise OpalException(404, "not_found", f"Unknown setting key: {key!r}")


def _setting_read(request: Request, key: str) -> dict:
    """Kernel SettingRead: effective/configured/default plus provenance."""
    store = request.app.state.store
    running = request.app.state.running_settings
    effective = effective_settings(store).model_dump(mode="json")
    override = store.settings.entry(key)
    overlays = env_overlays()
    default = PortableSettings.model_fields[key].get_default(call_default_factory=True)
    if key in overlays:
        source = overlays[key]["source"]
    elif override is not None:
        source = "persisted"
    else:
        source = "default"
    warnings = []
    if source in ("environment", "dotenv") and override is not None:
        warnings.append({
            "code": f"masked_by_{source}",
            "path": key,
            "message": (f"The {source} overlay masks the persisted "
                        f"override for {key!r}."),
        })
    body = {
        "key": key,
        "value": effective[key],
        "configured_value": override["value"] if override else default,
        "default": default,
        "has_override": override is not None,
        "is_default": source == "default",
        "source": source,
        "restart_required": True,
        "pending_restart": effective[key] != running.get(key),
        "warnings": warnings,
    }
    if override and override.get("updated_at"):
        body["updated_at"] = override["updated_at"]
    return body


@router.get("/setting/", operation_id="opal_setting_list")
def list_settings(request: Request) -> JSONResponse:
    store = request.app.state.store
    body = effective_settings(store).model_dump(mode="json")
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.get("/setting/{key}", operation_id="opal_setting_get")
def get_setting(request: Request, key: str) -> JSONResponse:
    _check_key_path(key)
    _known_key(key)
    return JSONResponse(
        _setting_read(request, key),
        headers={"ETag": request.app.state.store.config_revision()},
    )


@router.put("/setting/{key}", operation_id="opal_setting_put")
def put_setting(request: Request, key: str, body: SettingUpdateBody) -> JSONResponse:
    _check_key_path(key)
    _known_key(key)
    try:
        validated = PortableSettingsPatch.model_validate({key: body.value})
    except ValidationError as exc:
        raise OpalException(
            422, "validation_failed", f"Invalid value for setting {key!r}.",
            details={"errors": exc.errors()},
        ) from exc
    value = validated.model_dump(exclude_unset=True)[key]

    store = request.app.state.store
    with store.write_txn():
        check_if_match(request, store)
        store.settings.set(key, value)
        revision = store.bump_revision()
    return JSONResponse(_setting_read(request, key), headers={"ETag": revision})


@router.delete("/setting/{key}", operation_id="opal_setting_delete", status_code=204)
def delete_setting(request: Request, response: Response, key: str) -> None:
    _check_key_path(key)
    _known_key(key)
    store = request.app.state.store
    with store.write_txn():
        check_if_match(request, store)
        store.settings.delete(key)
        response.headers["ETag"] = store.bump_revision()
