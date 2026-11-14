from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from opal_look_yolo import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPAL_YOLO_", env_file=".env", extra="ignore")

    service_name: str = "opal-yolo"
    service_version: str = __version__
    engine_id: str = "yolo"
    host: str = "127.0.0.1"
    port: int = Field(default=8086, ge=1, le=65535)
    auth_disabled: bool = True
    auth_token: str | None = None
    model_dirs: list[Path] = Field(default_factory=lambda: [Path("models")])
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_concurrent_predictions: int = Field(default=2, ge=1)

    @field_validator("model_dirs", mode="before")
    @classmethod
    def parse_model_dirs(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            return json.loads(stripped)
        return [part for part in stripped.split(os.pathsep) if part]

    @model_validator(mode="after")
    def validate_auth_policy(self) -> Settings:
        if self.auth_disabled:
            if not self._is_loopback_host():
                raise ValueError("authentication can only be disabled for loopback deployments")
        elif not self.auth_token:
            raise ValueError("OPAL_YOLO_AUTH_TOKEN is required when authentication is enabled")
        return self

    def _is_loopback_host(self) -> bool:
        host = self.host.strip("[]").lower()
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
