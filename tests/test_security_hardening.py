from __future__ import annotations

import logging
from io import BytesIO

import httpx
import pytest
from fastapi import status
from PIL import Image

from opal_look_yolo.config import Settings
from opal_look_yolo.errors import OpalException
from opal_look_yolo.services.sources import ImageSourceResolver

AUTH = {"Authorization": "Bearer test-token"}


def png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), color="white").save(output, format="PNG")
    return output.getvalue()


def resolver_for(handler, **overrides):
    transport = httpx.MockTransport(handler)
    options = {
        "allow_remote_sources": True,
        "allowed_remote_hosts": ["images.example"],
        "http_client_factory": lambda **kwargs: httpx.Client(
            transport=transport,
            **kwargs,
        ),
    }
    options.update(overrides)
    return ImageSourceResolver(10 * 1024, **options)


def test_non_loopback_requires_authentication_and_token():
    with pytest.raises(ValueError, match="loopback"):
        Settings(host="0.0.0.0", auth_disabled=True)
    with pytest.raises(ValueError, match="AUTH_TOKEN"):
        Settings(host="0.0.0.0", auth_disabled=False, auth_token=None)

    settings = Settings(host="0.0.0.0", auth_disabled=False, auth_token="secret")

    assert settings.auth_disabled is False
    assert settings.auth_token == "secret"


def test_remote_sources_require_explicit_enable_and_host_allowlist(tmp_path):
    url = "https://images.example/one.png"
    disabled = ImageSourceResolver(10 * 1024)
    unlisted = resolver_for(
        lambda request: httpx.Response(200, content=png()),
        allowed_remote_hosts=["other.example"],
    )

    with pytest.raises(OpalException) as denied:
        disabled.resolve(url)
    with pytest.raises(OpalException) as not_listed:
        unlisted.resolve(url)

    assert denied.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert not_listed.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_allowlisted_remote_source_is_bounded_and_decoded():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=png(),
        )

    resolver = resolver_for(handler)
    resolved = resolver.resolve("https://images.example/one.png")

    assert seen == ["https://images.example/one.png"]
    assert resolved.path is None
    assert resolved.image.size == (4, 3)


def test_remote_source_rejects_wrong_media_and_not_found():
    wrong_type = resolver_for(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"text",
        )
    )
    missing = resolver_for(lambda request: httpx.Response(404, content=b"missing"))

    with pytest.raises(OpalException) as bad:
        wrong_type.resolve("https://images.example/a.png")
    with pytest.raises(OpalException) as not_found:
        missing.resolve("https://images.example/a.png")

    assert bad.value.status_code == status.HTTP_400_BAD_REQUEST
    assert not_found.value.status_code == status.HTTP_404_NOT_FOUND


def test_remote_source_size_limit_is_enforced():
    resolver = resolver_for(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=png(),
        )
    )
    resolver.max_image_bytes = 4

    with pytest.raises(OpalException) as exc:
        resolver.resolve("https://images.example/a.png")

    assert exc.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE


def test_request_logging_includes_correlation_id(make_client, caplog):
    client = make_client()

    with caplog.at_level(logging.INFO, logger="opal_look_yolo.requests"):
        response = client.get(
            "/api/v1/info/",
            headers={**AUTH, "X-Opal-Request-Id": "request-log-1"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert "request-log-1" in caplog.text
    assert "GET" in caplog.text
    assert "/api/v1/info/" in caplog.text
