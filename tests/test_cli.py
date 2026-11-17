from __future__ import annotations

import json
from io import BytesIO

import httpx
from PIL import Image
from typer.testing import CliRunner

from opal_look_yolo.cli import create_cli_app
from opal_look_yolo.config import Settings
from opal_look_yolo.main import create_app


def invoke(arguments, handler):
    transport = httpx.MockTransport(handler)
    app = create_cli_app(transport=transport)
    return CliRunner().invoke(
        app,
        ["--url", "http://yolo.test", "--token", "secret", *arguments],
    )


def test_info_show_dispatches_bearer_request():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json={"service": "opal-yolo"})

    result = invoke(["info", "show"], handler)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["service"] == "opal-yolo"
    assert seen == [("GET", "http://yolo.test/api/v1/info/", "Bearer secret")]


def test_model_load_sends_device_payload():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "model-a", "loaded": True})

    result = invoke(["models", "load", "model-a", "--device", "cpu"], handler)

    assert result.exit_code == 0
    assert seen == [{"device": "cpu"}]
    assert json.loads(result.stdout)["loaded"] is True


def test_predict_builds_contract_json_body():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"engine": "yolo", "detections": []})

    result = invoke(
        [
            "predict",
            "input.png",
            "--model-id",
            "model-a",
            "--confidence",
            "0.7",
            "--device",
            "cpu",
            "--engine-options",
            '{"imgsz": 640}',
            "--include-native",
        ],
        handler,
    )

    assert result.exit_code == 0
    assert seen == [
        {
            "engine": "yolo",
            "model_id": "model-a",
            "source": "input.png",
            "confidence": 0.7,
            "device": "cpu",
            "engine_options": {"imgsz": 640},
            "include_native": True,
        }
    ]


def test_predict_frame_sends_multipart_frame(tmp_path):
    output = BytesIO()
    Image.new("RGB", (2, 2)).save(output, format="PNG")
    image = tmp_path / "frame.png"
    image.write_bytes(output.getvalue())
    frame = {
        "stream_id": "stream-1",
        "frame_id": "frame-1",
        "sequence": 1,
        "captured_at": "2025-01-01T00:00:00Z",
        "image": {"width": 2, "height": 2, "format": "png"},
    }
    seen = []

    def handler(request):
        seen.append(request.headers["content-type"])
        return httpx.Response(200, json={"engine": "yolo", "frame": frame})

    result = invoke(
        [
            "predict-frame",
            "--image",
            str(image),
            "--frame",
            json.dumps(frame),
            "--model-id",
            "model-a",
        ],
        handler,
    )

    assert result.exit_code == 0
    assert seen[0].startswith("multipart/form-data;")
    assert json.loads(result.stdout)["frame"]["frame_id"] == "frame-1"


def test_api_errors_are_reported_as_json():
    def handler(request):
        return httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "Model not found"}},
        )

    result = invoke(["models", "show", "missing"], handler)

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "not_found"


def test_connection_failure_is_reported_as_json():
    def handler(request):
        raise httpx.ConnectError("unreachable", request=request)

    result = invoke(["info", "health"], handler)

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "connection_failed"


def test_tree_renders_live_command_tree():
    result = CliRunner().invoke(create_cli_app(), ["tree"])

    assert result.exit_code == 0, result.output
    output = result.output
    assert output.splitlines()[0].startswith("opal-yolo")
    for command in (
        "info",
        "engines",
        "models",
        "hardware",
        "predict",
        "predict-frame",
        "tree",
    ):
        assert command in output
    assert "source" in output
    assert "[--model-id]" not in output
    assert "--model-id" in output
    assert "--help" not in output
    assert "--install-completion" not in output
    assert "\x1b[" not in output


def test_tree_ascii_variant():
    result = CliRunner().invoke(create_cli_app(), ["tree", "--ascii"])

    assert result.exit_code == 0, result.output
    output = result.output
    assert output.splitlines()[0].startswith("opal-yolo")
    assert "|-- " in output
    assert "`-- " in output
    assert "├──" not in output
    assert "└──" not in output
    assert "│" not in output
    assert "\x1b[" not in output
    output.encode("ascii")


def test_embedded_asgi_is_the_default_mode():
    service = create_app(
        settings=Settings(auth_disabled=True),
        engine_probe=lambda: True,
    )
    app = create_cli_app(service_app=service)

    result = CliRunner().invoke(app, ["info", "health"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "status": "ok",
        "engine_available": True,
    }


def test_yolo_look_alias_renders_its_own_tree_root():
    result = CliRunner().invoke(create_cli_app(label="yolo-look"), ["tree", "--ascii"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0].startswith("yolo-look")
