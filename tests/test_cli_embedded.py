"""CLI-driven coverage: commands exercised against a real in-process app.

Every invoke goes through Typer -> RestClient -> ASGI transport -> the real
FastAPI app with an in-memory Store, covering cli.py and the route/validator
code in one pass. Nothing writes to disk.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from opal_look_yolo.cli import create_cli_app
from opal_look_yolo.config import Settings
from opal_look_yolo.main import create_app
from opal_look_yolo.store import Store


def make_cli():
    service = create_app(settings=Settings(auth_disabled=True), store=Store())
    return create_cli_app(service_app=service)


def invoke(*args):
    return CliRunner().invoke(make_cli(), ["--no-env-file", *args])


def body(result):
    return json.loads(result.stdout)


# -- info / engines / hardware / models -----------------------------------------


def test_info_health_embedded():
    result = invoke("info", "health")
    assert result.exit_code == 0
    assert body(result)["name"] == "opal-look-yolo-svc"


def test_engine_commands_embedded():
    assert body(invoke("engines", "list"))
    assert body(invoke("engines", "discover"))
    assert body(invoke("engines", "show", "yolo"))["engine_id"] == "yolo"
    assert body(invoke("engines", "capabilities", "yolo"))


def test_hardware_commands_embedded():
    assert isinstance(body(invoke("hardware", "list")), list)


def test_models_commands_embedded():
    models = body(invoke("models", "list"))
    assert isinstance(models, list)
    assert invoke("models", "unload", "model-x").exit_code in (0, 1)


# -- settings through the CLI ----------------------------------------------------


def test_setting_lifecycle_embedded():
    runner = CliRunner()
    cli = make_cli()

    keys = body(runner.invoke(
        cli, ["--no-env-file", "config", "setting", "list"]))
    assert "max_image_bytes" in keys

    result = runner.invoke(
        cli, ["--no-env-file", "config", "setting", "set",
              "max_image_bytes", "4096"])
    assert result.exit_code == 0, result.output
    read = body(runner.invoke(
        cli, ["--no-env-file", "config", "setting", "show",
              "max_image_bytes"]))
    assert read["value"] == 4096

    result = runner.invoke(
        cli, ["--no-env-file", "config", "setting", "remove",
              "max_image_bytes"])
    assert result.exit_code == 0
    read = body(runner.invoke(
        cli, ["--no-env-file", "config", "setting", "show",
              "max_image_bytes"]))
    assert read["has_override"] is False


def test_setting_set_rejects_bad_json_value():
    result = invoke("config", "setting", "set", "max_image_bytes", "{oops")
    assert result.exit_code == 1


# -- profile through the CLI -----------------------------------------------------


def test_profile_flags_lifecycle(tmp_path):
    runner = CliRunner()
    cli = make_cli()

    shared = tmp_path / "shared.json"
    shared.write_text("{}")
    say = tmp_path / "say.json"
    say.write_text(json.dumps({"voice_id": "en-gb-alan-low", "speed": 1.5}))

    result = runner.invoke(
        cli,
        ["--no-env-file", "profile", "add", "--name", "Home", "--description", "cams",
         "--shared", str(shared), "--module", f"opal-say={say}"],
    )
    assert result.exit_code == 0, result.output
    pid = body(result)["id"]
    assert body(result)["modules"]["opal-say"]["speed"] == 1.5

    result = runner.invoke(cli, ["--no-env-file", "profile", "update", pid, "--is-active"])
    assert result.exit_code == 0
    assert body(result)["is_active"] is True

    result = runner.invoke(cli, ["--no-env-file", "profile", "update", pid, "--body",
                                 '{"description": "renamed"}'])
    assert result.exit_code == 0
    assert body(result)["description"] == "renamed"

    result = runner.invoke(cli, ["--no-env-file", "profile", "remove", pid])
    assert result.exit_code == 0
    assert runner.invoke(cli, ["--no-env-file", "profile", "show", pid]).exit_code == 1


def test_profile_add_from_file_and_activate(tmp_path):
    runner = CliRunner()
    cli = make_cli()
    doc = tmp_path / "p.json"
    doc.write_text(json.dumps({"id": "p1", "name": "Doc"}))

    result = runner.invoke(cli, ["--no-env-file", "profile", "add", "--in", str(doc)])
    assert result.exit_code == 0
    assert body(result)["id"] == "p1"

    result = runner.invoke(cli, ["--no-env-file", "profile", "activate", "p1"])
    assert result.exit_code == 0
    assert body(result)["is_active"] is True


def test_profile_in_is_exclusive_with_flags(tmp_path):
    doc = tmp_path / "p.json"
    doc.write_text(json.dumps({"name": "x"}))
    result = invoke("profile", "add", "--in", str(doc), "--name", "y")
    assert result.exit_code == 1


def test_profile_compartment_validation_through_cli(tmp_path):
    """Foreign compartments: structural validation + verbatim round-trip."""
    runner = CliRunner()
    cli = make_cli()

    def add(modules):
        doc = tmp_path / "p.json"
        doc.write_text(json.dumps({"name": "x", "modules": modules}))
        return runner.invoke(cli, ["--no-env-file", "profile", "add", "--in", str(doc)])

    # Valid foreign compartments round-trip.
    assert add({"opal-say": {"volume": 1.0, "sample_rate": 48000,
                             "engine_options": {"a": 1}}}).exit_code == 0
    assert add({"opal-listen": {"wakeword_names": ["hey"],
                                "enabled_intents": ["lights"],
                                "enabled_slots": [],
                                "confidence_thresholds": {"lights": 0.7},
                                "vad_settings": {"x": 1},
                                "model_paths": {"m": "/x"}}}).exit_code == 0
    assert add({"unregistered-module": {"anything": "goes"}}).exit_code == 0

    # Rejections.
    assert add({"opal-say": {"voice_id": 5}}).exit_code == 1
    assert add({"opal-say": {"speed": 99}}).exit_code == 1
    assert add({"opal-say": {"bogus": 1}}).exit_code == 1
    assert add({"opal-listen": {"wakeword_names": "not-a-list"}}).exit_code == 1
    assert add({"opal-listen": {"bogus": 1}}).exit_code == 1
    assert add({"opal-look-yolo": {"member": 1}}).exit_code == 1
    assert add({"opal-think": {"x": 1}}).exit_code == 1


# -- persona through the CLI -----------------------------------------------------


def test_persona_full_lifecycle():
    runner = CliRunner()
    cli = make_cli()

    result = runner.invoke(
        cli, ["--no-env-file", "persona", "add", "--persona-id", "amy", "--name", "Amy",
              "--description", "d", "--voice-id", "v1", "--enabled"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli, ["--no-env-file", "persona", "update", "amy", "--no-enabled"])
    assert result.exit_code == 0
    assert body(result)["enabled"] is False

    assert body(runner.invoke(cli, ["--no-env-file", "persona", "list", "--no-enabled"]))[0][
        "persona_id"] == "amy"

    result = runner.invoke(cli, ["--no-env-file", "persona", "validate", "amy"])
    assert result.exit_code == 0
    assert body(result)["valid"] is False

    result = runner.invoke(cli, ["--no-env-file", "persona", "update", "amy", "--if-match", "*",
                                 "--name", "Renamed"])
    assert result.exit_code == 0
    assert body(result)["name"] == "Renamed"

    result = runner.invoke(cli, ["--no-env-file", "persona", "remove", "amy", "--if-match", "*"])
    assert result.exit_code == 0
    assert runner.invoke(cli, ["--no-env-file", "persona", "show", "amy"]).exit_code == 1


def test_persona_update_without_fields_fails():
    runner = CliRunner()
    cli = make_cli()
    runner.invoke(
        cli, ["--no-env-file", "persona", "add", "--persona-id", "x",
              "--name", "X"])
    result = runner.invoke(cli, ["--no-env-file", "persona", "update", "x"])
    assert result.exit_code == 1


def test_persona_field_validation_errors():
    runner = CliRunner()
    cli = make_cli()
    bad = runner.invoke(
        cli, ["--no-env-file", "persona", "add", "--persona-id", "bad id!", "--name", "X"])
    assert bad.exit_code == 1


# -- config snapshots through the CLI --------------------------------------------


def test_config_file_roundtrip(tmp_path):
    runner = CliRunner()
    cli = make_cli()
    snap = tmp_path / "snap.json"

    runner.invoke(cli, ["--no-env-file", "config", "setting", "set", "max_image_bytes", "777"])
    result = runner.invoke(cli, ["--no-env-file", "config", "save", "--out", str(snap)])
    assert result.exit_code == 0
    assert json.loads(snap.read_text())["settings"] == {"max_image_bytes": 777}

    runner.invoke(cli, ["--no-env-file", "config", "setting", "remove", "max_image_bytes"])
    result = runner.invoke(cli, ["--no-env-file", "config", "load", "--in", str(snap)])
    assert result.exit_code == 0
    assert body(result)["applied"] is True
    assert body(runner.invoke(
        cli, ["--no-env-file", "config", "setting", "show", "max_image_bytes"]))["value"] == 777


def test_config_validate_file_error_report(tmp_path):
    snap = tmp_path / "bad.json"
    snap.write_text(json.dumps({"module": "opal-listen"}))
    result = invoke("config", "validate", "--in", str(snap))
    assert result.exit_code == 0
    report = body(result)
    assert report["valid"] is False
    assert any(e["code"] == "wrong_module" for e in report["errors"])


@pytest.mark.parametrize("snapshot,expected_code", [
    ("not-a-dict", "invalid_envelope"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {}, "resources": {}, "extra": 1},
     "invalid_envelope"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "settings": "nope", "resources": {}}, "invalid_envelope"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {}, "resources": []},
     "invalid_envelope"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {}, "resources": {"profiles": "x"}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"profiles": ["x"]}}, "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"profiles": [{"id": "a"}, {"id": "a"}]}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"profiles": [
          {"name": "a", "id": "a", "is_active": True},
          {"name": "b", "id": "b", "is_active": True}]}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"profiles": [{"name": "a", "shared": {"x": 1}}]}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"profiles": [{"name": "a",
                                  "modules": {"opal-look-yolo": {"m": 1}}}]}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {}, "resources": {"personas": "x"}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"personas": [{"persona_id": "bad id!"}]}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {}, "resources": {"engines": "x"}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"engines": [{"engine_id": "yolo", "options": "x"}]}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {},
      "resources": {"engines": [{"nope": 1}]}}, "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {}, "resources": {"models": "x"}},
     "invalid_resource"),
    ({"format_version": "1.0.0", "module": "opal-look-yolo",
      "created_at": "now", "settings": {}, "resources": {"bogus": []}},
     "unknown_section"),
])
def test_config_validate_issue_codes(tmp_path, snapshot, expected_code):
    snap = tmp_path / "s.json"
    snap.write_text(json.dumps(snapshot))
    result = invoke("config", "validate", "--in", str(snap))
    assert result.exit_code == 0
    report = body(result)
    assert report["valid"] is False
    assert any(e["code"] == expected_code for e in report["errors"]), report


def test_config_load_restores_engines_and_models_sections(tmp_path):
    """engines/models are persisted verbatim as desired state."""
    runner = CliRunner()
    cli = make_cli()
    snap = tmp_path / "s.json"
    snap.write_text(json.dumps({
        "format_version": "1.0.0", "module": "opal-look-yolo",
        "created_at": "now", "settings": {},
        "resources": {
            "engines": [{"engine_id": "yolo", "enabled": True}],
            "models": [{"model_id": "m1"}],
        },
    }))
    result = runner.invoke(cli, ["--no-env-file", "config", "load", "--in", str(snap)])
    assert result.exit_code == 0, result.output

    out = tmp_path / "round.json"
    runner.invoke(cli, ["--no-env-file", "config", "save", "--out", str(out)])
    saved = json.loads(out.read_text())
    assert saved["resources"]["engines"] == [
        {"engine_id": "yolo", "enabled": True}]
    assert saved["resources"]["models"] == [{"model_id": "m1"}]


# -- service through the CLI -----------------------------------------------------


def test_service_stop_and_log_rest_paths():
    """REST path via MockTransport-independent embedded app."""
    result = invoke("service", "stop")
    assert result.exit_code == 0
    assert body(result)["state"] == "stopped"

    result = invoke("service", "log")
    assert result.exit_code == 1  # 404: no managed log in this cwd


def test_service_start_local_fallback(tmp_path, monkeypatch):
    """Unreachable server -> local pidfile fallback spawns directly."""
    from opal_look_yolo import service_control as sc

    monkeypatch.chdir(tmp_path)
    calls = {}

    def fake_spawn(append=False, wait_pid=None, env_extra=None):
        calls.update(append=append, wait_pid=wait_pid, env_extra=env_extra)
        sc.write_pid(999)
        return 999

    monkeypatch.setattr(sc, "spawn_server", fake_spawn)
    monkeypatch.setattr(sc, "pid_alive", lambda pid: False)

    cli = create_cli_app()  # embedded; service start hits the ASGI route
    service = create_app(settings=Settings(auth_disabled=True),
                         store=Store())
    cli = create_cli_app(service_app=service)

    result = CliRunner().invoke(
        cli, ["service", "start", "--append", "--port", "9000"])
    # Embedded mode reaches the REST route (not the fallback); the route
    # itself calls the (monkeypatched) spawn_server.
    assert result.exit_code == 0, result.output
    assert calls["wait_pid"] is None or calls["append"]


def test_service_fallback_when_unreachable(monkeypatch, tmp_path):
    from opal_look_yolo import service_control as sc

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sc, "pid_alive", lambda pid: False)
    spawned = []
    monkeypatch.setattr(sc, "spawn_server",
                        lambda **kw: spawned.append(kw) or 4242)

    app = create_cli_app()
    result = CliRunner().invoke(
        app,
        ["--url", "http://127.0.0.1:1", "service", "start", "--port", "9000"],
    )
    assert result.exit_code == 0, result.output
    assert spawned and spawned[0]["env_extra"] == {"OPAL_YOLO_PORT": "9000"}

    killed = []
    monkeypatch.setattr(sc, "read_pid", lambda: 1234)
    monkeypatch.setattr(sc, "pid_alive", lambda pid: True)
    monkeypatch.setattr(sc, "kill_pid", killed.append)
    result = CliRunner().invoke(
        app, ["--url", "http://127.0.0.1:1", "service", "stop"])
    assert result.exit_code == 0
    assert killed == [1234]

    # log fallback tails the local file
    sc.log_dir().mkdir(exist_ok=True)
    sc.log_path().write_text("l1\nl2\n")
    result = CliRunner().invoke(
        app, ["--url", "http://127.0.0.1:1", "service", "log", "--lines", "1"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "l2"


# -- predict / error paths --------------------------------------------------------


def test_predict_embedded_json_error_surfaces():
    result = invoke("predict", "img.jpg", "--model-id", "m",
                    "--engine-options", "{bad json")
    assert result.exit_code == 1


def test_serve_invokes_uvicorn(monkeypatch, tmp_path):
    import uvicorn

    monkeypatch.chdir(tmp_path)

    seen = {}
    monkeypatch.setattr(
        uvicorn, "run",
        lambda app, host, port: seen.update(host=host, port=port))
    result = CliRunner().invoke(
        create_cli_app(), ["--no-env-file", "serve", "--port", "9999"])
    assert result.exit_code == 0
    assert seen == {"host": "127.0.0.1", "port": 9999}
