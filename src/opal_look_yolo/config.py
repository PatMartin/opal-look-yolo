from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from opal_look_yolo import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPAL_YOLO_", extra="ignore")

    service_name: str = "opal-yolo"
    service_version: str = __version__
    engine_id: str = "yolo"
    host: str = "127.0.0.1"
    port: int = Field(default=8086, ge=1, le=65535)
    data_dir: Path = Path("data")
    auth_disabled: bool = True
    auth_token: str | None = None
    model_dirs: Annotated[list[Path], NoDecode] = Field(default_factory=lambda: [Path("models")])
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_concurrent_predictions: int = Field(default=2, ge=1)
    allow_remote_sources: bool = False
    allowed_remote_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    remote_source_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @field_validator("model_dirs", mode="before")
    @classmethod
    def parse_model_dirs(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            return json.loads(stripped)
        return [part for part in stripped.split(os.pathsep) if part]

    @field_validator("allowed_remote_hosts", mode="before")
    @classmethod
    def parse_remote_hosts(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            return json.loads(stripped)
        return [part.strip() for part in stripped.split(",") if part.strip()]

    @model_validator(mode="after")
    def validate_auth_policy(self) -> Settings:
        if self.auth_disabled:
            if not self._is_loopback_host():
                raise ValueError("authentication can only be disabled for loopback deployments")
        elif not self.auth_token:
            raise ValueError("OPAL_YOLO_AUTH_TOKEN is required when authentication is enabled")
        if self.allow_remote_sources and not self.allowed_remote_hosts:
            raise ValueError(
                "OPAL_YOLO_ALLOWED_REMOTE_HOSTS is required when remote sources are enabled"
            )
        return self

    def _is_loopback_host(self) -> bool:
        host = self.host.strip("[]").lower()
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False


def dotenv_baseline() -> dict[str, object]:
    defaults = Settings.model_construct()
    return {
        "OPAL_YOLO_HOST": defaults.host,
        "OPAL_YOLO_PORT": defaults.port,
        "OPAL_YOLO_AUTH_DISABLED": defaults.auth_disabled,
        "OPAL_YOLO_MODEL_DIRS": os.pathsep.join(str(path) for path in defaults.model_dirs),
        "OPAL_YOLO_MAX_IMAGE_BYTES": defaults.max_image_bytes,
        "OPAL_YOLO_MAX_CONCURRENT_PREDICTIONS": defaults.max_concurrent_predictions,
        "OPAL_YOLO_ALLOW_REMOTE_SOURCES": defaults.allow_remote_sources,
        "OPAL_YOLO_ALLOWED_REMOTE_HOSTS": ",".join(defaults.allowed_remote_hosts),
        "OPAL_YOLO_REMOTE_SOURCE_TIMEOUT_SECONDS": defaults.remote_source_timeout_seconds,
        "OPAL_YOLO_AUTH_TOKEN": "<set-a-token>",
    }
