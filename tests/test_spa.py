from __future__ import annotations

from fastapi import status


def test_root_redirects_to_spa(make_client):
    client = make_client()

    response = client.get("/", follow_redirects=False)

    assert response.status_code == status.HTTP_307_TEMPORARY_REDIRECT
    assert response.headers["location"] == "/app/"


def test_spa_is_served_without_api_authentication(make_client):
    client = make_client()

    response = client.get("/app/")

    assert response.status_code == status.HTTP_200_OK
    assert "OPAL Look YOLO" in response.text
    assert 'id="predict"' in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_spa_does_not_shadow_api_routes(make_client):
    client = make_client()

    response = client.get("/api/v1/health/", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "opal-look-yolo-svc"
