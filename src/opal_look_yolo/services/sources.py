from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from fastapi import status
from PIL import Image, ImageOps

from opal_look_yolo.errors import OpalException


@dataclass(frozen=True)
class ResolvedImage:
    image: Image.Image
    path: Path | None


class ImageSourceResolver:
    def __init__(self, max_image_bytes: int) -> None:
        self.max_image_bytes = max_image_bytes

    def resolve(self, source: str) -> ResolvedImage:
        path = self._resolve_path(source)
        if path is None:
            raise OpalException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "validation_failed",
                "Remote image sources are not permitted",
            )
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

    def _resolve_path(self, source: str) -> Path | None:
        parsed = urlparse(source)
        windows_drive = len(parsed.scheme) == 1 and source[1:3] in {":/", ":\\"}
        if parsed.scheme in {"", None} or windows_drive:
            return Path(source).expanduser()
        if parsed.scheme == "file":
            if parsed.netloc and parsed.netloc.lower() != "localhost":
                return None
            return Path(url2pathname(unquote(parsed.path)))
        return None

    def _check_size(self, size: int) -> None:
        if size > self.max_image_bytes:
            raise OpalException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "payload_too_large",
                "Image exceeds the configured size limit",
                {"max_image_bytes": self.max_image_bytes},
            )
