from __future__ import annotations

AUTH = {"Authorization": "Bearer test-token"}


def _etag(client) -> str:
    return client.get("/api/v1/setting/", headers=AUTH).headers["ETag"]


def _create(client, name="Home", **fields):
    body = {"name": name, **fields}
    return client.post(
        "/api/v1/profile/", headers={**AUTH, "If-Match": _etag(client)}, json=body
    )


def test_empty_catalog_returns_empty_list(make_client):
    response = make_client().get("/api/v1/profile/", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == []


def test_profile_crud_roundtrip(make_client):
    client = make_client()

    response = _create(
        client,
        id="home",
        description="House cameras",
        shared={},
        modules={"opal-say": {"voice_id": "en-gb-alan-low", "speed": 1.2}},
    )
    assert response.status_code == 201
    assert response.headers["Location"] == "/api/v1/profile/home"
    body = response.json()
    assert body["id"] == "home"
    assert body["is_active"] is False
    assert body["modules"]["opal-say"]["voice_id"] == "en-gb-alan-low"

    # Foreign compartment is preserved verbatim on read.
    body = client.get("/api/v1/profile/home", headers=AUTH).json()
    assert body["modules"]["opal-say"]["speed"] == 1.2

    response = client.patch(
        "/api/v1/profile/home",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"description": "Updated"},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "Updated"
    # Unpatched foreign compartment intact.
    assert response.json()["modules"]["opal-say"]["voice_id"] == "en-gb-alan-low"

    response = client.delete(
        "/api/v1/profile/home", headers={**AUTH, "If-Match": _etag(client)}
    )
    assert response.status_code == 204
    assert client.get("/api/v1/profile/home", headers=AUTH).status_code == 404


def test_create_requires_if_match(make_client):
    response = make_client().post(
        "/api/v1/profile/", headers=AUTH, json={"name": "x"}
    )
    assert response.status_code == 428


def test_create_duplicate_id_is_409(make_client):
    client = make_client()
    assert _create(client, id="a").status_code == 201
    assert _create(client, name="Other", id="a").status_code == 409


def test_own_compartment_members_rejected(make_client):
    client = make_client()
    response = client.post(
        "/api/v1/profile/",
        headers={**AUTH, "If-Match": "*"},
        json={"name": "x", "modules": {"opal-look-yolo": {"anything": 1}}},
    )
    assert response.status_code == 422
    # The empty own compartment itself is accepted.
    response = client.post(
        "/api/v1/profile/",
        headers={**AUTH, "If-Match": "*"},
        json={"name": "x", "modules": {"opal-look-yolo": {}}},
    )
    assert response.status_code == 201


def test_shared_members_rejected(make_client):
    response = make_client().post(
        "/api/v1/profile/",
        headers={**AUTH, "If-Match": "*"},
        json={"name": "x", "shared": {"theme": "dark"}},
    )
    assert response.status_code == 422


def test_patch_rejects_foreign_compartments(make_client):
    client = make_client()
    _create(client, id="a", modules={"opal-say": {"voice_id": "v"}})
    response = client.patch(
        "/api/v1/profile/a",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"modules": {"opal-say": {"voice_id": "v2"}}},
    )
    assert response.status_code == 422
    # Own-compartment (empty) patch is allowed.
    response = client.patch(
        "/api/v1/profile/a",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"modules": {"opal-look-yolo": {}}},
    )
    assert response.status_code == 200


def test_activate_and_single_active(make_client):
    client = make_client()
    assert _create(client, name="A", id="a", is_active=True).status_code == 201
    assert _create(client, name="B", id="b").status_code == 201

    response = client.post(
        "/api/v1/profile/b/activate", headers={**AUTH, "If-Match": _etag(client)}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True

    profiles = {p["id"]: p for p in client.get("/api/v1/profile/", headers=AUTH).json()}
    assert profiles["a"]["is_active"] is False
    assert profiles["b"]["is_active"] is True

    # Active profile is surfaced in health.
    health = client.get("/api/v1/health/", headers=AUTH).json()
    assert health["active_profile_id"] == "b"

    # Activate is If-Match-guarded and 404s on unknown ids.
    assert client.post(
        "/api/v1/profile/b/activate", headers=AUTH
    ).status_code == 428
    assert client.post(
        "/api/v1/profile/nope/activate", headers={**AUTH, "If-Match": "*"}
    ).status_code == 404


def test_patch_is_active_true_activates(make_client):
    client = make_client()
    _create(client, name="A", id="a")
    _create(client, name="B", id="b", is_active=True)

    response = client.patch(
        "/api/v1/profile/a",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"is_active": True},
    )
    assert response.json()["is_active"] is True
    profiles = {p["id"]: p for p in client.get("/api/v1/profile/", headers=AUTH).json()}
    assert profiles["b"]["is_active"] is False

    # False leaves the selection unchanged.
    client.patch(
        "/api/v1/profile/b",
        headers={**AUTH, "If-Match": _etag(client)},
        json={"is_active": False},
    )
    profiles = {p["id"]: p for p in client.get("/api/v1/profile/", headers=AUTH).json()}
    assert profiles["a"]["is_active"] is True


def test_validation_errors(make_client):
    client = make_client()
    etag = {"If-Match": "*"}
    assert client.post(
        "/api/v1/profile/", headers={**AUTH, **etag}, json={}
    ).status_code == 422
    assert client.post(
        "/api/v1/profile/", headers={**AUTH, **etag},
        json={"name": "x", "bogus": 1},
    ).status_code == 422
    assert client.post(
        "/api/v1/profile/", headers={**AUTH, **etag},
        json={"name": "x", "modules": {"opal-say": {"voice_id": 5}}},
    ).status_code == 422
    assert client.patch(
        "/api/v1/profile/nope", headers={**AUTH, **etag}, json={"name": "y"}
    ).status_code == 404
