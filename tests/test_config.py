from __future__ import annotations

AUTH = {"Authorization": "Bearer test-token"}


def _etag(client) -> str:
    return client.get("/api/v1/setting/", headers=AUTH).headers["ETag"]


def _seed(client):
    """Persisted state worth snapshotting: a setting, profile, persona."""
    client.put(
        "/api/v1/setting/max_image_bytes",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"value": 1234},
    )
    client.post(
        "/api/v1/profile/",
        headers={**AUTH, "If-Match": _etag(client)},
        json={
            "name": "Home",
            "id": "home",
            "is_active": True,
            "modules": {"opal-say": {"voice_id": "v"}},
        },
    )
    client.post(
        "/api/v1/persona/",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"persona_id": "amy", "name": "Amy", "enabled": False},
    )


def _wipe(client):
    """Remove the seeded state through public ops."""
    client.delete(
        "/api/v1/setting/max_image_bytes",
        headers={**AUTH, "If-Match": _etag(client)},
    )
    client.delete(
        "/api/v1/profile/home", headers={**AUTH, "If-Match": _etag(client)}
    )
    client.delete(
        "/api/v1/persona/amy", headers={**AUTH, "If-Match": _etag(client)}
    )


def test_save_returns_portable_snapshot(make_client):
    client = make_client()
    _seed(client)
    response = client.post(
        "/api/v1/config/save", headers=AUTH, json={"destination": "response"}
    )
    assert response.status_code == 200
    assert response.headers["ETag"]
    body = response.json()
    assert body["managed"] is False
    snap = body["snapshot"]
    assert snap["format_version"] == "1.0.0"
    assert snap["module"] == "opal-look-yolo"
    assert snap["settings"] == {"max_image_bytes": 1234}
    resources = snap["resources"]
    assert set(resources) == {"profiles", "personas", "engines", "models"}
    assert resources["profiles"][0]["id"] == "home"
    assert resources["profiles"][0]["is_active"] is True
    assert resources["profiles"][0]["modules"]["opal-say"]["voice_id"] == "v"
    assert resources["personas"][0]["persona_id"] == "amy"
    assert resources["personas"][0]["enabled"] is False
    assert resources["engines"] == [] and resources["models"] == []


def test_save_load_roundtrip_restores_state(make_client):
    client = make_client()
    _seed(client)
    saved = client.post(
        "/api/v1/config/save", headers=AUTH, json={"destination": "managed"}
    ).json()
    assert saved["managed"] is True

    _wipe(client)
    assert client.get("/api/v1/persona/amy", headers=AUTH).status_code == 404

    # Load without an explicit snapshot restores the managed one.
    response = client.post(
        "/api/v1/config/load",
        headers={**AUTH, "If-Match": _etag(client)},
        json={},
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert response.headers["ETag"]

    # Everything restored through public reads.
    setting = client.get("/api/v1/setting/max_image_bytes", headers=AUTH).json()
    assert setting["value"] == 1234
    profile = client.get("/api/v1/profile/home", headers=AUTH).json()
    assert profile["is_active"] is True
    assert profile["modules"]["opal-say"]["voice_id"] == "v"
    persona = client.get("/api/v1/persona/amy", headers=AUTH).json()
    assert persona["enabled"] is False


def test_load_requires_if_match_and_snapshot_is_validated(make_client):
    client = make_client()
    assert client.post(
        "/api/v1/config/load", headers=AUTH, json={"snapshot": {}}
    ).status_code == 428

    client.post("/api/v1/config/save", headers=AUTH, json={})
    response = client.post(
        "/api/v1/config/load", headers={**AUTH, "If-Match": '"stale"'}, json={}
    )
    assert response.status_code == 412


def test_load_without_managed_snapshot_is_404(make_client):
    response = make_client().post(
        "/api/v1/config/load", headers={**AUTH, "If-Match": "*"}, json={}
    )
    assert response.status_code == 404


def test_validate_reports_envelope_errors(make_client):
    client = make_client()
    good = client.post(
        "/api/v1/config/save", headers=AUTH, json={"destination": "response"}
    ).json()["snapshot"]

    report = client.post(
        "/api/v1/config/validate", headers=AUTH, json={"snapshot": good}
    ).json()
    assert report["valid"] is True
    assert report["errors"] == []

    bad_module = {**good, "module": "opal-listen"}
    report = client.post(
        "/api/v1/config/validate", headers=AUTH, json={"snapshot": bad_module}
    ).json()
    assert report["valid"] is False
    assert any(e["code"] == "wrong_module" for e in report["errors"])

    bad_version = {**good, "format_version": "9.9.9"}
    report = client.post(
        "/api/v1/config/validate", headers=AUTH, json={"snapshot": bad_version}
    ).json()
    assert any(e["code"] == "unsupported_version" for e in report["errors"])

    bad_settings = {**good, "settings": {"not_a_key": 1, "max_image_bytes": -5}}
    report = client.post(
        "/api/v1/config/validate", headers=AUTH, json={"snapshot": bad_settings}
    ).json()
    codes = {e["code"] for e in report["errors"]}
    assert {"unknown_setting", "invalid_setting"} <= codes

    bad_section = {**good, "resources": {**good["resources"], "bogus": []}}
    report = client.post(
        "/api/v1/config/validate", headers=AUTH, json={"snapshot": bad_section}
    ).json()
    assert any(e["code"] == "unknown_section" for e in report["errors"])


def test_validate_without_snapshot_checks_live_config(make_client):
    client = make_client()
    _seed(client)
    report = client.post("/api/v1/config/validate", headers=AUTH, json={}).json()
    assert report["valid"] is True


def test_unknown_engine_warns_but_does_not_fail(make_client):
    client = make_client()
    good = client.post(
        "/api/v1/config/save", headers=AUTH, json={"destination": "response"}
    ).json()["snapshot"]
    snap = {
        **good,
        "resources": {
            **good["resources"],
            "engines": [{"engine_id": "not-an-engine", "enabled": False}],
        },
    }
    report = client.post(
        "/api/v1/config/validate", headers=AUTH, json={"snapshot": snap}
    ).json()
    assert report["valid"] is True
    assert report["warnings"][0]["code"] == "unknown_engine"


def test_load_executes_no_actions_and_is_atomic(make_client):
    client = make_client()
    _seed(client)
    snap = client.post(
        "/api/v1/config/save", headers=AUTH, json={"destination": "response"}
    ).json()["snapshot"]
    _wipe(client)

    # A stale If-Match must abort the whole apply, not partially restore.
    assert client.post(
        "/api/v1/config/load",
        headers={**AUTH, "If-Match": '"stale"'},
        json={"snapshot": snap},
    ).status_code == 412
    assert client.get("/api/v1/persona/amy", headers=AUTH).status_code == 404

    # Invalid snapshots never reach apply.
    invalid = {**snap, "settings": {"bad": 1}}
    assert client.post(
        "/api/v1/config/load",
        headers={**AUTH, "If-Match": "*"},
        json={"snapshot": invalid},
    ).status_code == 422
    assert client.get("/api/v1/persona/amy", headers=AUTH).status_code == 404
