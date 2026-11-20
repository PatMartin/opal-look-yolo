"""Portable service settings: registry, defaults, overlays, provenance.

Registered keys are a subset of config.Settings fields; every key maps to
an ``OPAL_YOLO_<KEY>`` environment overlay (precedence environment >
dotenv > persisted > default). Values are bound into services at startup,
so all registered keys are ``restart_required`` and divergent desired
values surface via ``pending_restart``/``pending_restart_fields``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .store import Store

_log = logging.getLogger(__name__)


def _split_paths(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.startswith("["):
        return json.loads(stripped)
    return [part for part in stripped.split(os.pathsep) if part]


def _split_hosts(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.startswith("["):
        return json.loads(stripped)
    return [part.strip() for part in stripped.split(",") if part.strip()]


class PortableSettings(BaseModel):
    """Registered portable setting keys with native JSON values."""

    model_config = ConfigDict(extra="forbid")

    model_dirs: list[str] = Field(default_factory=lambda: ["models"])
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_concurrent_predictions: int = Field(default=2, ge=1)
    allow_remote_sources: bool = False
    allowed_remote_hosts: list[str] = Field(default_factory=list)
    remote_source_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    _parse_dirs = field_validator("model_dirs", mode="before")(_split_paths)
    _parse_hosts = field_validator("allowed_remote_hosts", mode="before")(_split_hosts)


class PortableSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_dirs: list[str] | None = Field(default=None)
    max_image_bytes: int | None = Field(default=None, ge=1)
    max_concurrent_predictions: int | None = Field(default=None, ge=1)
    allow_remote_sources: bool | None = None
    allowed_remote_hosts: list[str] | None = None
    remote_source_timeout_seconds: float | None = Field(default=None, gt=0, le=60)

    _parse_dirs = field_validator("model_dirs", mode="before")(_split_paths)
    _parse_hosts = field_validator("allowed_remote_hosts", mode="before")(_split_hosts)


class SettingUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any


SETTINGS_KEYS = frozenset(PortableSettings.model_fields)

ENV_PREFIX = "OPAL_YOLO_"
DOTENV_FILE_VAR = "OPAL_DOTENV_FILE"
NO_DOTENV_VAR = "OPAL_NO_DOTENV"
_INVALID = object()


def _parse_setting(key: str, raw: Any) -> Any:
    """JSON-then-string parse + schema validation for one setting value."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        value = raw
    try:
        validated = PortableSettingsPatch.model_validate({key: value})
    except ValidationError:
        return _INVALID
    return validated.model_dump(exclude_unset=True)[key]


def env_setting_overrides(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """OPAL_YOLO_<SETTING_KEY> variables -> validated values.

    Only names matching a registered setting key apply; deployment
    variables (HOST/PORT/TOKEN/AUTH_*/DATA_DIR/URL) are ignored. Values
    that fail schema validation are skipped with a warning.
    """
    env = os.environ if environ is None else environ
    out: dict[str, Any] = {}
    for var, raw in env.items():
        if not var.startswith(ENV_PREFIX):
            continue
        key = var[len(ENV_PREFIX):].lower()
        if key not in SETTINGS_KEYS:
            continue
        value = _parse_setting(key, raw)
        if value is _INVALID:
            _log.warning("ignoring %s=%r: invalid value for setting %r", var, raw, key)
            continue
        out[key] = value
    return out


def _dotenv_setting_keys(environ: dict[str, str]) -> set[str]:
    """Setting keys whose process value was sourced from the dotenv file."""
    path = environ.get(DOTENV_FILE_VAR)
    if not path or environ.get(NO_DOTENV_VAR):
        return set()
    from dotenv import dotenv_values
    try:
        file_vars = dotenv_values(path)
    except OSError:
        return set()
    keys = set()
    for var, value in file_vars.items():
        if not isinstance(var, str) or not var.startswith(ENV_PREFIX):
            continue
        key = var[len(ENV_PREFIX):].lower()
        if key not in SETTINGS_KEYS or value is None:
            continue
        if environ.get(var) == value:
            keys.add(key)
    return keys


def env_overlays(environ: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """{key: {"value", "source"}} for env/dotenv-supplied setting values."""
    env = os.environ if environ is None else environ
    dotenv_keys = _dotenv_setting_keys(env)
    return {
        key: {"value": value,
              "source": "dotenv" if key in dotenv_keys else "environment"}
        for key, value in env_setting_overrides(env).items()
    }


def effective_settings(store: Store) -> PortableSettings:
    """Effective values: persisted overrides under environment/.env overlays."""
    overrides = dict(store.settings.overrides())
    for key, overlay in env_overlays().items():
        overrides[key] = overlay["value"]
    return PortableSettings.model_validate(
        {k: v for k, v in overrides.items() if k in SETTINGS_KEYS}
    )


def pending_restart_fields(store: Store, running: dict[str, Any]) -> list[str]:
    """Registered keys whose desired effective value diverges from the
    value the running process was started with (env-masked edits never
    diverge, so they report masked rather than pending)."""
    effective = effective_settings(store).model_dump(mode="json")
    return sorted(key for key in SETTINGS_KEYS if effective[key] != running.get(key))


def apply_persisted_overrides(store: Store, settings: Any) -> None:
    """Layer persisted overrides under environment/.env overlays onto the
    startup Settings before services are built (restart activation)."""
    overlays = env_overlays()
    persisted = {
        key: value
        for key, value in store.settings.overrides().items()
        if key in SETTINGS_KEYS and key not in overlays
    }
    if not persisted:
        return
    current = effective_settings(store).model_dump(mode="json")
    for key, value in persisted.items():
        try:
            setattr(settings, key, _settings_value(key, current[key]))
        except (TypeError, ValueError) as exc:
            _log.warning("ignoring persisted override %r=%r: %s", key, value, exc)


def _settings_value(key: str, value: Any) -> Any:
    if key == "model_dirs":
        from pathlib import Path
        return [Path(part) for part in value]
    return value


def running_values(settings: Any) -> dict[str, Any]:
    """JSON-normalized registered values as bound at startup."""
    values = settings.model_dump(mode="json")
    return {key: values[key] for key in SETTINGS_KEYS}
