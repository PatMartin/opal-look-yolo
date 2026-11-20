"""CLI coverage for the v0.1.0 kernel command groups (x-opal-cli bindings)."""

from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from opal_look_yolo.cli import create_cli_app


def invoke(arguments, handler):
    transport = httpx.MockTransport(handler)
    app = create_cli_app(transport=transport)
    return CliRunner().invoke(
        app,
        ["--url", "http://yolo.test", "--token", "secret", *arguments],
    )


def test_setting_set_sends_parsed_value_with_if_match():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url),
                     request.headers.get("if-match")))
        if request.method == "GET":
            return httpx.Response(200, json={}, headers={"ETag": '"rev-3"'})
        return httpx.Response(200, json={"key": "max_image_bytes"})

    result = invoke(
        ["config", "setting", "set", "max_image_bytes", "4096"], handler)

    assert result.exit_code == 0, result.output
    assert seen == [
        ("GET", "http://yolo.test/api/v1/setting/", None),
        ("PUT", "http://yolo.test/api/v1/setting/max_image_bytes", '"rev-3"'),
    ]


def test_setting_list_and_show():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    assert invoke(["config", "setting", "list"], handler).exit_code == 0
    assert invoke(["config", "setting", "show", "model_dirs"], handler).exit_code == 0
    assert seen == [
        "http://yolo.test/api/v1/setting/",
        "http://yolo.test/api/v1/setting/model_dirs",
    ]


def test_config_save_out_writes_snapshot_file(tmp_path):
    out = tmp_path / "snap.json"

    def handler(request):
        assert json.loads(request.content) == {"destination": "response"}
        return httpx.Response(200, json={
            "snapshot": {"module": "opal-look-yolo", "format_version": "1.0.0"},
            "managed": False,
        })

    result = invoke(["config", "save", "--out", str(out)], handler)

    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["module"] == "opal-look-yolo"


def test_config_load_in_sends_snapshot_with_if_match(tmp_path):
    snap = {"format_version": "1.0.0", "module": "opal-look-yolo"}
    file = tmp_path / "snap.json"
    file.write_text(json.dumps(snap))
    seen = []

    def handler(request):
        seen.append((request.method, request.headers.get("if-match")))
        if request.method == "GET":
            return httpx.Response(200, json={}, headers={"ETag": '"r"'})
        assert json.loads(request.content) == {"snapshot": snap}
        return httpx.Response(200, json={"applied": True})

    result = invoke(["config", "load", "--in", str(file)], handler)

    assert result.exit_code == 0, result.output
    assert seen == [("GET", None), ("POST", '"r"')]


def test_config_validate_live_by_default():
    def handler(request):
        assert json.loads(request.content) == {}
        return httpx.Response(200, json={"valid": True, "errors": []})

    result = invoke(["config", "validate"], handler)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["valid"] is True


def test_persona_list_enabled_filter():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    assert invoke(["persona", "list", "--enabled"], handler).exit_code == 0
    assert invoke(["persona", "list"], handler).exit_code == 0
    assert seen == [
        "http://yolo.test/api/v1/persona/?enabled=true",
        "http://yolo.test/api/v1/persona/",
    ]


def test_persona_add_with_explicit_if_match():
    seen = []

    def handler(request):
        seen.append((request.headers.get("if-match"),
                     json.loads(request.content)))
        return httpx.Response(201, json={"persona_id": "amy"})

    result = invoke(
        ["persona", "add", "--persona-id", "amy", "--name", "Amy",
         "--voice-id", "v1", "--if-match", '"e1"'],
        handler,
    )

    assert result.exit_code == 0, result.output
    assert seen == [('"e1"', {"persona_id": "amy", "name": "Amy",
                             "voice_id": "v1"})]


def test_profile_activate_uses_etag():
    seen = []

    def handler(request):
        seen.append(request.headers.get("if-match"))
        if request.method == "GET":
            return httpx.Response(200, json={}, headers={"ETag": '"r7"'})
        return httpx.Response(200, json={"id": "home", "is_active": True})

    result = invoke(["profile", "activate", "home"], handler)

    assert result.exit_code == 0, result.output
    assert '"r7"' in seen


def test_profile_add_from_file(tmp_path):
    doc = {"name": "Home", "modules": {"opal-say": {"voice_id": "v"}}}
    file = tmp_path / "p.json"
    file.write_text(json.dumps(doc))
    seen = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={}, headers={"ETag": '"r"'})
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "p-1"})

    result = invoke(["profile", "add", "--in", str(file)], handler)

    assert result.exit_code == 0, result.output
    assert seen == [doc]


def test_service_log_prints_tail():
    def handler(request):
        assert "lines=3" in str(request.url)
        return httpx.Response(
            200, json={"log_file": "logs/x.log", "lines": ["a", "b", "c"]})

    result = invoke(["service", "log", "--lines", "3"], handler)

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["a", "b", "c"]


def test_service_start_rest_post():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"state": "running", "pid": 5})

    result = invoke(["service", "start", "--append"], handler)

    assert result.exit_code == 0
    assert seen == [{"append": True}]
    assert json.loads(result.stdout)["state"] == "running"
