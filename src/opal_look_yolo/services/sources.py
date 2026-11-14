from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from fastapi import status
from PIL import Image, ImageOps

from opal_look_yolo.errors import OpalException


@dataclass(frozen=True)
class ResolvedImage:
    image: Image.Image
    path: Path | None


HttpClientFactory = Callable[..., httpx.Client]


class ImageSourceResolver:
    def __init__(
        self,
        max_image_bytes: int,
        *,
        allow_remote_sources: bool = False,
        allowed_remote_hosts: Iterable[str] = (),
        remote_timeout_seconds: float = 5.0,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self.max_image_bytes = max_image_bytes
        self.allow_remote_sources = allow_remote_sources
        self.allowed_remote_hosts = {host.lower() for host in allowed_remote_hosts}
        self.remote_timeout_seconds = remote_timeout_seconds
        self.http_client_factory = http_client_factory or httpx.Client

    def resolve(self, source: str) -> ResolvedImage:
        location = self._resolve_location(source)
        if isinstance(location, str):
            return self._resolve_remote(location)
        if location is None:
            raise OpalException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "validation_failed",
                "Remote image sources are not permitted",
            )
        return self._resolve_local(location, source)

    def decode(self, data: bytes) -> Image.Image:
        self._check_size(len(data))
        try:
            with Image.open(BytesIO(data)) as image:
                corrected = ImageOps.exif_transpose(image)
                return corrected.convert("RGB")
        except Exception as exc:
            raise OpalException(
                status.HTTP_400_BAD_REQUEST,
                "bad_request",
                "Image bytes are not a supported JPEG or PNG image",
            ) from exc

    def _resolve_local(self, path: Path, source: str) -> ResolvedImage:
        if not path.is_file():
            raise OpalException(
                status.HTTP_404_NOT_FOUND,
                "not_found",
                "Image source not found",
                {"source": source},
            )
        try:
            size = path.stat().st_size
            self._check_size(size)
            data = path.read_bytes()
        except OpalException:
            raise
        except OSError as exc:
            raise OpalException(
                status.HTTP_404_NOT_FOUND,
                "not_found",
                "Image source is not readable",
                {"source": source},
            ) from exc
        return ResolvedImage(image=self.decode(data), path=path)

    def _resolve_location(self, source: str) -> Path | str | None:
        parsed = urlparse(source)
        windows_drive = len(parsed.scheme) == 1 and source[1:3] in {":/", ":\\"}
        if parsed.scheme in {"", None} or windows_drive:
            return Path(source).expanduser()
        if parsed.scheme == "file":
            if parsed.netloc and parsed.netloc.lower() != "localhost":
                return None
            return Path(url2pathname(unquote(parsed.path)))
        if parsed.scheme in {"http", "https"}:
            host = (parsed.hostname or "").lower()
            if self.allow_remote_sources and host in self.allowed_remote_hosts:
                return source
            return None
        return None

    def _resolve_remote(self, source: str) -> ResolvedImage:
        try:
            with self.http_client_factory(
                timeout=self.remote_timeout_seconds,
                follow_redirects=False,
            ) as client:
                with client.stream("GET", source) as response:
                    if response.status_code == status.HTTP_404_NOT_FOUND:
                        raise OpalException(
                            status.HTTP_404_NOT_FOUND,
                            "not_found",
                            "Remote image source not found",
                        )
                    if response.status_code >= 400:
                        raise OpalException(
                            status.HTTP_503_SERVICE_UNAVAILABLE,
                            "service_unavailable",
                            "Remote image source is unavailable",
                        )
                    content_type = response.headers.get("content-type", "").split(";")[0]
                    if content_type not in {"image/jpeg", "image/png"}:
                        raise OpalException(
                            status.HTTP_400_BAD_REQUEST,
                            "bad_request",
                            "Remote source must return JPEG or PNG content",
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        self._check_size(len(data))
            return ResolvedImage(image=self.decode(bytes(data)), path=None)
        except OpalException:
            raise
        except httpx.HTTPError as exc:
            raise OpalException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "Remote image source is unavailable",
            ) from exc

    def _check_size(self, size: int) -> None:
        if size > self.max_image_bytes:
            raise OpalException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "payload_too_large",
                "Image exceeds the configured size limit",
                {"max_image_bytes": self.max_image_bytes},
            )
