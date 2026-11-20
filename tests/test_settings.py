from __future__ import annotations

AUTH = {"Authorization": "Bearer test-token"}


def _etag(client) -> str:
    return client.get("/api/v1/setting/", headers=AUTH).headers["ETag"]


def test_settings_map_returns_registered_keys_with_etag(make_client):
    response = make_client().get("/api/v1/setting/", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "model_dirs",
        "max_image_bytes",
        "max_concurrent_predictions",
        "allow_remote_sources",
        "allowed_remote_hosts",
        "remote_source_timeout_seconds",
    }
    assert body["model_dirs"] == ["models"]
    assert body["max_concurrent_predictions"] == 2
    assert response.headers["ETag"].startswith('"')


def test_setting_read_reports_default_provenance(make_client):
    response = make_client().get("/api/v1/setting/max_image_bytes", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "max_image_bytes"
    assert body["value"] == 10 * 1024 * 1024
    assert body["configured_value"] == 10 * 1024 * 1024
    assert body["default"] == 10 * 1024 * 1024
    assert body["has_override"] is False
    assert body["is_default"] is True
    assert body["source"] == "default"
    assert body["restart_required"] is True
    assert body["pending_restart"] is False


def test_unknown_setting_key_is_404(make_client):
    response = make_client().get("/api/v1/setting/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_put_requires_if_match(make_client):
    client = make_client()
    response = client.put(
        "/api/v1/setting/max_image_bytes", headers=AUTH, json={"value": 42}
    )
    assert response.status_code == 428
    assert response.json()["error"]["code"] == "precondition_required"


def test_put_rejects_malformed_if_match(make_client):
    client = make_client()
    response = client.put(
        "/api/v1/setting/max_image_bytes",
        headers={**AUTH, "If-Match": 'W/"weak"'},
        json={"value": 42},
    )
    assert response.status_code == 422


def test_put_rejects_stale_if_match(make_client):
    client = make_client()
    response = client.put(
        "/api/v1/setting/max_image_bytes",
        headers={**AUTH, "If-Match": '"stale"'},
        json={"value": 42},
    )
    assert response.status_code == 412
    assert response.json()["error"]["code"] == "precondition_failed"
    # Stored value unchanged.
    body = client.get("/api/v1/setting/max_image_bytes", headers=AUTH).json()
    assert body["value"] == 10 * 1024 * 1024


def test_put_set_show_delete_roundtrip(make_client):
    client = make_client()
    etag = _etag(client)

    response = client.put(
        "/api/v1/setting/max_image_bytes",
        headers={**AUTH, "If-Match": etag},
        json={"value": 5_000_000},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["value"] == 5_000_000
    assert body["configured_value"] == 5_000_000
    assert body["has_override"] is True
    assert body["is_default"] is False
    assert body["source"] == "persisted"
    assert body["pending_restart"] is True
    new_etag = response.headers["ETag"]
    assert new_etag != etag

    assert client.get("/api/v1/setting/", headers=AUTH).json()["max_image_bytes"] == 5_000_000

    health = client.get("/api/v1/health/", headers=AUTH).json()
    assert health["pending_restart"] is True
    assert "max_image_bytes" in health["pending_restart_fields"]

    response = client.delete(
        "/api/v1/setting/max_image_bytes",
        headers={**AUTH, "If-Match": new_etag},
    )
    assert response.status_code == 204
    assert response.headers["ETag"] != new_etag

    body = client.get("/api/v1/setting/max_image_bytes", headers=AUTH).json()
    assert body["has_override"] is False
    assert body["source"] == "default"
    assert body["pending_restart"] is False


def test_delete_without_override_still_204(make_client):
    client = make_client()
    response = client.delete(
        "/api/v1/setting/allow_remote_sources",
        headers={**AUTH, "If-Match": _etag(client)},
    )
    assert response.status_code == 204


def test_put_invalid_value_is_422(make_client):
    client = make_client()
    response = client.put(
        "/api/v1/setting/max_concurrent_predictions",
        headers={**AUTH, "If-Match": "*"},
        json={"value": 0},
    )
    assert response.status_code == 422


def test_put_list_setting_accepts_native_json(make_client):
    client = make_client()
    response = client.put(
        "/api/v1/setting/model_dirs",
        headers={**AUTH, "If-Match": "*"},
        json={"value": ["weights", "more/weights"]},
    )
    assert response.status_code == 200
    assert response.json()["value"] == ["weights", "more/weights"]


def test_environment_overlay_masks_persisted_override(make_client, monkeypatch):
    client = make_client()
    client.put(
        "/api/v1/setting/allow_remote_sources",
        headers={**AUTH, "If-Match": "*"},
        json={"value": True},
    )
    monkeypatch.setenv("OPAL_YOLO_ALLOW_REMOTE_SOURCES", "false")

    body = client.get("/api/v1/setting/allow_remote_sources", headers=AUTH).json()
    assert body["value"] is False
    assert body["configured_value"] is True
    assert body["has_override"] is True
    assert body["source"] == "environment"
    assert body["pending_restart"] is False
    assert any(w["code"] == "masked_by_environment" for w in body["warnings"])


def test_persisted_override_applies_at_startup(tmp_path):
    from opal_look_yolo.config import Settings
    from opal_look_yolo.main import create_app
    from opal_look_yolo.store import Store

    store = Store(tmp_path / "data")
    store.settings.set("max_concurrent_predictions", 7)
    app = create_app(settings=Settings(auth_disabled=True), store=store)
    assert app.state.settings.max_concurrent_predictions == 7
    assert app.state.running_settings["max_concurrent_predictions"] == 7
