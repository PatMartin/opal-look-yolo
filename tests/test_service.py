from __future__ import annotations

import pytest

from opal_look_yolo import service_control

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture()
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_stop_is_idempotent_when_nothing_running(make_client, chdir_tmp):
    client = make_client()
    response = client.post("/api/v1/service/stop", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "stopped"
    assert body["pid"] is None
    assert body["log_file"].endswith("opal_look_yolo.log")


def test_log_tail_404_without_log_file(make_client, chdir_tmp):
    response = make_client().get("/api/v1/service/log", headers=AUTH)
    assert response.status_code == 404


def test_log_tail_returns_last_lines(make_client, chdir_tmp):
    service_control.log_dir().mkdir()
    service_control.log_path().write_text("\n".join(f"line{i}" for i in range(20)))
    client = make_client()
    response = client.get("/api/v1/service/log?lines=5", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["lines"] == [f"line{i}" for i in range(15, 20)]
    assert body["log_file"].endswith("opal_look_yolo.log")


def test_start_spawns_detached_and_records_pid(
    make_client, chdir_tmp, monkeypatch
):
    spawned = {}

    def fake_spawn(append=False, wait_pid=None, env_extra=None):
        spawned.update(append=append, wait_pid=wait_pid)
        service_control.write_pid(4242)
        return 4242

    monkeypatch.setattr(service_control, "spawn_server", fake_spawn)
    monkeypatch.setattr(service_control, "pid_alive", lambda pid: False)

    client = make_client()
    response = client.post("/api/v1/service/start", headers=AUTH, json={})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "running"
    assert body["pid"] == 4242
    assert body["previous_pid"] is None
    assert spawned == {"append": False, "wait_pid": None}
    assert service_control.read_pid() == 4242


def test_start_restarts_existing_managed_process(
    make_client, chdir_tmp, monkeypatch
):
    service_control.write_pid(1111)
    calls = {}

    monkeypatch.setattr(service_control, "pid_alive", lambda pid: True)
    def fake_spawn(append=False, wait_pid=None, env_extra=None):
        calls["wait_pid"] = wait_pid
        return 2222

    monkeypatch.setattr(service_control, "spawn_server", fake_spawn)
    monkeypatch.setattr(
        service_control, "kill_pid", lambda pid: calls.setdefault("killed", pid)
    )

    client = make_client()
    response = client.post(
        "/api/v1/service/start", headers=AUTH, json={"append": True}
    )
    body = response.json()
    assert body["state"] == "running"
    assert body["pid"] == 2222
    assert body["previous_pid"] == 1111
    assert calls == {"wait_pid": 1111, "killed": 1111}


def test_stop_kills_managed_process(make_client, chdir_tmp, monkeypatch):
    service_control.write_pid(3333)
    killed = []
    monkeypatch.setattr(service_control, "pid_alive", lambda pid: True)
    monkeypatch.setattr(service_control, "kill_pid", killed.append)

    client = make_client()
    response = client.post("/api/v1/service/stop", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["state"] == "stopped"
    assert killed == [3333]
    assert not service_control.pid_path().exists()


def test_pidfile_bookkeeping(chdir_tmp):
    import os

    service_control.ensure_pidfile()
    assert service_control.read_pid() == os.getpid()
    service_control.release_pidfile()
    assert not service_control.pid_path().exists()

    # release_pidfile leaves a foreign pid alone
    service_control.write_pid(9999)
    service_control.release_pidfile()
    assert service_control.read_pid() == 9999


def test_wait_for_death_returns_when_dead(chdir_tmp, monkeypatch):
    monkeypatch.setattr(service_control, "pid_alive", lambda pid: False)
    service_control.wait_for_death(1234, timeout=0.1)


def test_pid_alive_rejects_nonpositive(chdir_tmp):
    assert service_control.pid_alive(0) is False
    assert service_control.pid_alive(-1) is False
