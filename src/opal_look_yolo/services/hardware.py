from __future__ import annotations

import platform
from typing import Protocol

from fastapi import status

from opal_look_yolo.errors import OpalException
from opal_look_yolo.schemas.hardware import Hardware


class HardwareProvider(Protocol):
    def list_devices(self) -> list[Hardware]: ...


class LocalHardwareProvider:
    def list_devices(self) -> list[Hardware]:
        devices = [
            Hardware(
                device_id="cpu",
                type="cpu",
                available=True,
                name=platform.processor() or "CPU",
            )
        ]
        devices.extend(self._torch_devices())
        return devices

    def _torch_devices(self) -> list[Hardware]:
        try:
            import torch
        except ImportError:
            return []

        devices: list[Hardware] = []
        if torch.cuda.is_available():
            for index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(index)
                devices.append(
                    Hardware(
                        device_id=f"cuda:{index}",
                        type="gpu",
                        available=True,
                        memory_mb=properties.total_memory // (1024 * 1024),
                        name=properties.name,
                    )
                )
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            devices.append(
                Hardware(
                    device_id="mps:0",
                    type="accelerator",
                    available=True,
                    name="Apple Metal Performance Shaders",
                )
            )
        return devices


class HardwareService:
    def __init__(self, provider: HardwareProvider) -> None:
        self.provider = provider

    def list_devices(self) -> list[Hardware]:
        return self.provider.list_devices()

    def get_device(self, device_id: str) -> Hardware:
        for device in self.list_devices():
            if device.device_id == device_id:
                return device
        raise OpalException(
            status.HTTP_404_NOT_FOUND,
            "not_found",
            "Hardware device not found",
            {"device_id": device_id},
        )
