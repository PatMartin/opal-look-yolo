"""Configuration snapshot endpoints (kernel config_save/load/validate).

Save captures a portable OpalConfigSnapshot (managed store or response
body), load atomically replaces persistent configuration under If-Match,
validate runs the same checks without mutating. No actions execute on
load.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from opal_look_yolo.configuration import (
    apply_snapshot,
    build_snapshot,
    load_managed,
    save_managed,
    validate_snapshot,
)
from opal_look_yolo.errors import OpalException
from opal_look_yolo.precondition import check_if_match, require_if_match

router = APIRouter(tags=["config"])


def _registry(request: Request):
    return request.app.state.engine_registry


@router.post("/config/save", operation_id="opal_config_save")
def config_save(request: Request, body: dict | None = None) -> JSONResponse:
    store = request.app.state.store
    body = body or {}
    if not isinstance(body, dict):
        raise OpalException(
            422, "validation_failed", "config save body must be a JSON object.")
    unknown = set(body) - {"destination"}
    if unknown:
        raise OpalException(
            422, "validation_failed", f"Unknown fields: {sorted(unknown)}.")
    destination = body.get("destination", "managed")
    if destination not in ("managed", "response"):
        raise OpalException(
            422, "validation_failed",
            "destination must be 'managed' or 'response'.")
    snapshot = build_snapshot(store)
    if destination == "managed":
        save_managed(store, snapshot)
    # Save is not a live mutation: ETag carries the captured revision.
    return JSONResponse(
        {"snapshot": snapshot, "managed": destination == "managed"},
        headers={"ETag": store.config_revision()})


@router.post("/config/load", operation_id="opal_config_load")
def config_load(request: Request, body: dict | None = None) -> JSONResponse:
    require_if_match(request)
    store = request.app.state.store
    body = body or {}
    if not isinstance(body, dict):
        raise OpalException(
            422, "validation_failed", "config load body must be a JSON object.")
    unknown = set(body) - {"snapshot"}
    if unknown:
        raise OpalException(
            422, "validation_failed", f"Unknown fields: {sorted(unknown)}.")
    if "snapshot" in body:
        if body["snapshot"] is None:
            raise OpalException(
                422, "validation_failed", "An explicit null snapshot is invalid.")
        snapshot = body["snapshot"]
    else:
        snapshot = load_managed(store)
        if snapshot is None:
            raise OpalException(404, "not_found", "No managed snapshot exists.")

    errors, warnings = validate_snapshot(store, snapshot, _registry(request))
    if errors:
        raise OpalException(
            422, "validation_failed",
            "Snapshot is invalid: "
            + "; ".join(e["message"] for e in errors[:4]),
            details={"issues": errors})
    with store.write_txn():
        check_if_match(request, store)
        pending = apply_snapshot(store, snapshot, _registry(request))
        revision = store.bump_revision()
    return JSONResponse(
        {"applied": True, "pending_restart_fields": pending,
         "warnings": warnings},
        headers={"ETag": revision})


@router.post("/config/validate", operation_id="opal_config_validate")
def config_validate(request: Request, body: dict | None = None) -> JSONResponse:
    store = request.app.state.store
    body = body or {}
    if not isinstance(body, dict):
        raise OpalException(
            422, "validation_failed",
            "config validate body must be a JSON object.")
    unknown = set(body) - {"snapshot"}
    if unknown:
        raise OpalException(
            422, "validation_failed", f"Unknown fields: {sorted(unknown)}.")
    if "snapshot" not in body:
        snapshot = build_snapshot(store)  # live configuration
    else:
        if body["snapshot"] is None:
            raise OpalException(
                422, "validation_failed", "An explicit null snapshot is invalid.")
        snapshot = body["snapshot"]
    errors, warnings = validate_snapshot(store, snapshot, _registry(request))
    return JSONResponse(
        {"valid": not errors, "errors": errors, "warnings": warnings},
        headers={"ETag": store.config_revision()})
