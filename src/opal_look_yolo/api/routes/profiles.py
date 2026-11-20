"""Profile endpoints (kernel OpalProfile/Create/Patch): portable namespaced
profile documents with shared + per-module compartments. This adapter's
own compartment is an explicit empty schema; foreign compartments are
preserved verbatim through reads, own-compartment edits and config
save/load.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from opal_look_yolo.errors import OpalException
from opal_look_yolo.precondition import check_if_match, require_if_match
from opal_look_yolo.profiles import (
    profile_read,
    validate_modules,
    validate_shared,
)
from opal_look_yolo.timeutil import now_iso

router = APIRouter(tags=["profile"])

_CREATE_FIELDS = {"id", "name", "description", "is_active", "shared", "modules"}
_PATCH_FIELDS = {"name", "description", "is_active", "shared", "modules"}


def _get_profile_or_404(store, profile_id: str):
    row = store.profiles.get(profile_id)
    if row is None:
        raise OpalException(404, "not_found", f"Unknown profile: {profile_id}")
    return row


def _check_name(name) -> None:
    if not isinstance(name, str) or not name or len(name) > 100:
        raise OpalException(
            422, "validation_failed",
            "Profile 'name' must be a string of 1-100 chars.")


@router.get("/profile/", operation_id="opal_profile_list")
def list_profiles(request: Request) -> JSONResponse:
    store = request.app.state.store
    return JSONResponse(
        [profile_read(r) for r in store.profiles.list()],
        headers={"ETag": store.config_revision()},
    )


@router.post("/profile/", operation_id="opal_profile_create", status_code=201)
def create_profile(request: Request, body: dict) -> JSONResponse:
    require_if_match(request)
    if not isinstance(body, dict):
        raise OpalException(
            422, "validation_failed", "Profile body must be a JSON object.")
    unknown = set(body) - _CREATE_FIELDS
    if unknown:
        raise OpalException(
            422, "validation_failed", f"Unknown profile fields: {sorted(unknown)}.")
    if "name" not in body:
        raise OpalException(422, "validation_failed", "Profile 'name' is required.")
    _check_name(body["name"])
    if "id" in body and (not isinstance(body["id"], str) or not body["id"]):
        raise OpalException(
            422, "validation_failed", "Profile 'id' must be a non-empty string.")
    if "description" in body and body["description"] is not None \
            and not isinstance(body["description"], str):
        raise OpalException(
            422, "validation_failed",
            "Profile 'description' must be a string or null.")
    if "is_active" in body and not isinstance(body["is_active"], bool):
        raise OpalException(422, "validation_failed", "is_active must be a boolean.")
    validate_shared(body.get("shared"))
    validate_modules(body.get("modules"), patch=False)

    pid = body.get("id") or f"p-{secrets.token_hex(6)}"
    now = now_iso()
    fields = {
        "profile_id": pid,
        "name": body["name"],
        "description": body.get("description"),
        "is_active": bool(body.get("is_active")),
        "shared": body.get("shared") or {},
        "modules": body.get("modules") or {},
        "created_at": now,
        "updated_at": now,
    }
    store = request.app.state.store
    with store.write_txn():
        check_if_match(request, store)
        if store.profiles.get(pid) is not None:
            raise OpalException(409, "conflict", f"Profile {pid!r} already exists.")
        store.profiles.insert(fields)
        if fields["is_active"]:
            store.profiles.set_active(pid)
        revision = store.bump_revision()
    return JSONResponse(
        profile_read(store.profiles.get(pid)),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/profile/{pid}"},
    )


@router.get("/profile/{profile_id}", operation_id="opal_profile_get")
def get_profile(request: Request, profile_id: str) -> JSONResponse:
    store = request.app.state.store
    row = _get_profile_or_404(store, profile_id)
    return JSONResponse(profile_read(row), headers={"ETag": store.config_revision()})


@router.patch("/profile/{profile_id}", operation_id="opal_profile_patch")
def patch_profile(request: Request, profile_id: str, body: dict) -> JSONResponse:
    require_if_match(request)
    store = request.app.state.store
    _get_profile_or_404(store, profile_id)
    if not isinstance(body, dict):
        raise OpalException(
            422, "validation_failed", "Profile patch must be a JSON object.")
    if not body:
        raise OpalException(
            422, "validation_failed", "Empty profile patches are not allowed.")
    unknown = set(body) - _PATCH_FIELDS
    if unknown:
        raise OpalException(
            422, "validation_failed",
            f"Unknown profile patch fields: {sorted(unknown)}.")
    if "name" in body:
        if body["name"] is None:
            raise OpalException(
                422, "validation_failed", "Profile 'name' may not be null.")
        _check_name(body["name"])
    if "description" in body and body["description"] is not None \
            and not isinstance(body["description"], str):
        raise OpalException(
            422, "validation_failed",
            "Profile 'description' must be a string or null.")
    if "is_active" in body and not isinstance(body["is_active"], bool):
        raise OpalException(422, "validation_failed", "is_active must be a boolean.")
    validate_shared(body.get("shared"))
    validate_modules(body.get("modules"), patch=True)

    update: dict = {}
    if "name" in body:
        update["name"] = body["name"]
    if "description" in body:
        update["description"] = body["description"]
    # `shared` and the own compartment are closed-empty today: a supplied {}
    # merges to a no-op; field-wise merge lands here when fields exist.
    update["updated_at"] = now_iso()
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.update(profile_id, update)
        if body.get("is_active"):
            # True activates; false leaves the local selection unchanged.
            store.profiles.set_active(profile_id)
        revision = store.bump_revision()
    return JSONResponse(
        profile_read(store.profiles.get(profile_id)), headers={"ETag": revision})


@router.delete("/profile/{profile_id}", operation_id="opal_profile_delete", status_code=204)
def delete_profile(request: Request, response: Response, profile_id: str) -> None:
    require_if_match(request)
    store = request.app.state.store
    _get_profile_or_404(store, profile_id)
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.delete(profile_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/profile/{profile_id}/activate", operation_id="opal_profile_activate")
def activate_profile(request: Request, profile_id: str) -> JSONResponse:
    require_if_match(request)
    store = request.app.state.store
    _get_profile_or_404(store, profile_id)
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.set_active(profile_id)
        revision = store.bump_revision()
    return JSONResponse(
        profile_read(store.profiles.get(profile_id)), headers={"ETag": revision})
