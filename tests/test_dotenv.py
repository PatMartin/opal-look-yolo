from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from opal_look_yolo.cli import create_cli_app
from opal_look_yolo.config import dotenv_baseline
from opal_look_yolo.dotenv import DotenvError, prepare


@pytest.fixture(autouse=True)
def clean_policy(monkeypatch):
    monkeypatch.delenv("OPAL_DOTENV_FILE", raising=False)
    monkeypatch.delenv("OPAL_NO_DOTENV", raising=False)
    monkeypatch.delenv("APP_VALUE", raising=False)
    yield
    os.environ.pop("OPAL_DOTENV_FILE", None)
    os.environ.pop("OPAL_NO_DOTENV", None)
    os.environ.pop("APP_VALUE", None)


def test_default_env_created_and_loaded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = prepare(baseline={"APP_VALUE": "from-default"})
    assert result.created
    assert os.environ["APP_VALUE"] == "from-default"
    assert (tmp_path / ".env").read_text(encoding="utf-8").startswith("# Generated OPAL")


def test_existing_nonempty_environment_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_VALUE", "real-env")
    (tmp_path / ".env").write_text("APP_VALUE='dotenv'\n")
    prepare()
    assert os.environ["APP_VALUE"] == "real-env"


def test_existing_empty_environment_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_VALUE", "")
    (tmp_path / ".env").write_text("APP_VALUE='dotenv'\n")
    prepare()
    assert os.environ["APP_VALUE"] == ""


def test_env_file_wins_over_default_and_no_parent_search(tmp_path, monkeypatch):
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (root / ".env").write_text("APP_VALUE='parent'\n")
    monkeypatch.chdir(child)
    prepare(baseline={"APP_VALUE": "baseline"})
    assert os.environ["APP_VALUE"] == "baseline"
    assert not (root / ".env").read_text().startswith("# Generated")


def test_existing_env_not_rewritten(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".env"
    path.write_text("APP_VALUE='custom'\n")
    prepare(baseline={"APP_VALUE": "baseline"})
    assert path.read_text() == "APP_VALUE='custom'\n"


def test_no_env_file_disables_loading_and_creation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = prepare(no_env_file=True)
    assert result.disabled and not result.loaded and not (tmp_path / ".env").exists()


def test_explicit_missing_and_mutually_exclusive_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DotenvError, match="not found"):
        prepare(env_file="missing.env")
    with pytest.raises(DotenvError, match="mutually exclusive"):
        prepare(env_file=".env", no_env_file=True)


def test_explicit_relative_path_resolves_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "conf" / "local.env"
    explicit.parent.mkdir()
    explicit.write_text("APP_VALUE='explicit'\n")
    prepare(env_file="conf/local.env")
    assert os.environ["APP_VALUE"] == "explicit"


def test_generated_file_omits_secret_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prepare(baseline={"APP_TOKEN": "super-secret", "APP_VALUE": "safe"})
    text = (tmp_path / ".env").read_text()
    assert "super-secret" not in text
    assert "# APP_TOKEN=<redacted>" in text


def test_cli_dotenv_controls(tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(create_cli_app(), ["--no-env-file", "info", "health"])
    assert result.exit_code == 0
    assert not (tmp_path / ".env").exists()
    result = runner.invoke(create_cli_app(), ["--env-file", "missing.env", "info", "health"])
    assert result.exit_code == 1
    assert "dotenv file not found" in result.output


def test_empty_url_environment_selects_embedded_mode(tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPAL_YOLO_URL", "")
    (tmp_path / ".env").write_text("OPAL_YOLO_URL='http://127.0.0.1:1'\n")
    result = runner.invoke(create_cli_app(), ["info", "health"])
    assert result.exit_code == 0


def test_yolo_baseline_contains_supported_defaults():
    baseline = dotenv_baseline()
    assert baseline["OPAL_YOLO_PORT"] == 8086
    assert baseline["OPAL_YOLO_MODEL_DIRS"] == '["models"]'
