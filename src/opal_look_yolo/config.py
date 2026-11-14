from __future__ import annotations

import ipaddress

from pydantic import Field, model_validator
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
