from __future__ import annotations

AUTH = {"Authorization": "Bearer test-token"}


def _etag(client) -> str:
    return client.get("/api/v1/setting/", headers=AUTH).headers["ETag"]


def _create(client, persona_id="amy", **fields):
    body = {"persona_id": persona_id, "name": "Amy", **fields}
    return client.post(
        "/api/v1/persona/", headers={**AUTH, "If-Match": _etag(client)}, json=body
    )


def test_empty_catalog_returns_empty_list(make_client):
    response = make_client().get("/api/v1/persona/", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["ETag"].startswith('"')


def test_persona_crud_roundtrip(make_client):
    client = make_client()

    response = _create(client, voice_id="en-gb-alan-low", enabled=False)
    assert response.status_code == 201
    assert response.headers["Location"] == "/api/v1/persona/amy"
    assert response.headers["ETag"]
    body = response.json()
    assert body["persona_id"] == "amy"
    assert body["voice_id"] == "en-gb-alan-low"
    assert body["enabled"] is False
    assert body["origin"] == "local"
    assert body["created_at"] and body["updated_at"]

    body = client.get("/api/v1/persona/amy", headers=AUTH).json()
    assert body["name"] == "Amy"

    response = client.patch(
        "/api/v1/persona/amy",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"voice_id": None, "enabled": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["voice_id"] is None
    assert body["enabled"] is True

    response = client.delete(
        "/api/v1/persona/amy", headers={**AUTH, "If-Match": _etag(client)}
    )
    assert response.status_code == 204
    assert response.headers["ETag"]

    assert client.get("/api/v1/persona/amy", headers=AUTH).status_code == 404


def test_create_requires_if_match(make_client):
    response = make_client().post(
        "/api/v1/persona/", headers=AUTH, json={"persona_id": "amy", "name": "Amy"}
    )
    assert response.status_code == 428


def test_create_duplicate_is_409(make_client):
    client = make_client()
    assert _create(client).status_code == 201
    assert _create(client).status_code == 409


def test_create_validates_body(make_client):
    client = make_client()
    etag = {"If-Match": "*"}
    assert client.post(
        "/api/v1/persona/", headers={**AUTH, **etag}, json={"name": "No id"}
    ).status_code == 422
    assert client.post(
        "/api/v1/persona/", headers={**AUTH, **etag},
        json={"persona_id": "bad id!", "name": "X"},
    ).status_code == 422
    assert client.post(
        "/api/v1/persona/", headers={**AUTH, **etag},
        json={"persona_id": "x", "name": "X", "bogus": 1},
    ).status_code == 422


def test_enabled_filter(make_client):
    client = make_client()
    _create(client, "on", enabled=True)
    _create(client, "off", enabled=False)

    all_ids = [p["persona_id"] for p in client.get("/api/v1/persona/", headers=AUTH).json()]
    assert all_ids == ["off", "on"]
    enabled = client.get("/api/v1/persona/?enabled=true", headers=AUTH).json()
    assert [p["persona_id"] for p in enabled] == ["on"]
    disabled = client.get("/api/v1/persona/?enabled=false", headers=AUTH).json()
    assert [p["persona_id"] for p in disabled] == ["off"]


def test_patch_requires_if_match_and_nonempty_body(make_client):
    client = make_client()
    _create(client)
    assert client.patch(
        "/api/v1/persona/amy", headers=AUTH, json={"name": "B"}
    ).status_code == 428
    assert client.patch(
        "/api/v1/persona/amy", headers={**AUTH, "If-Match": "*"}, json={}
    ).status_code == 422


def test_persona_validate_reports_enabled_and_opaque_voice(make_client):
    client = make_client()
    _create(client, "ok", enabled=True)
    _create(client, "vox", enabled=False, voice_id="en-gb-alan-low")

    report = client.post("/api/v1/persona/ok/validate", headers=AUTH).json()
    assert report["valid"] is True
    assert report["errors"] == []

    report = client.post("/api/v1/persona/vox/validate", headers=AUTH).json()
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "persona_disabled"
    assert report["warnings"][0]["code"] == "binding_unresolvable"

    assert client.post("/api/v1/persona/nope/validate", headers=AUTH).status_code == 404


def test_stale_if_match_is_412_and_stored_unchanged(make_client):
    client = make_client()
    _create(client)
    response = client.patch(
        "/api/v1/persona/amy",
        headers={**AUTH, "If-Match": '"stale"'},
        json={"name": "Changed"},
    )
    assert response.status_code == 412
    assert client.get("/api/v1/persona/amy", headers=AUTH).json()["name"] == "Amy"
