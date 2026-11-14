from __future__ import annotations

from fastapi import status

AUTH = {"Authorization": "Bearer test-token"}
CORRELATION = {
    "X-Opal-Session-Id": "session-1",
    "X-Opal-Transaction-Id": "transaction-1",
    "X-Opal-Request-Id": "request-1",
    "X-Opal-Causation-Id": "causation-1",
}


def test_info_returns_contract_fields_and_correlation_headers(make_client):
    client = make_client()
    response = client.get("/api/v1/info/", headers={**AUTH, **CORRELATION})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"name": "opal-yolo", "version": "0.1.0", "engine_id": "yolo"}
    assert response.headers["X-Opal-Session-Id"] == "session-1"
    assert response.headers["X-Opal-Transaction-Id"] == "transaction-1"
    assert response.headers["X-Opal-Request-Id"] == "request-1"
    assert response.headers["X-Opal-Causation-Id"] == "causation-1"


def test_info_generates_required_correlation_headers(make_client):
    response = make_client().get("/api/v1/info/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["X-Opal-Transaction-Id"]
    assert response.headers["X-Opal-Request-Id"]
    assert "X-Opal-Session-Id" not in response.headers
    assert "X-Opal-Causation-Id" not in response.headers


def test_health_reports_available_engine(make_client):
    response = make_client(engine_probe=lambda: True).get("/api/v1/health/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok", "engine_available": True, "detail": None}


def test_health_reports_degraded_when_engine_is_unavailable(make_client):
    response = make_client(engine_probe=lambda: False).get("/api/v1/health/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "degraded"
    assert response.json()["engine_available"] is False


def test_health_probe_failure_returns_opal_error(make_client):
    def fail() -> bool:
        raise RuntimeError("probe failed")

    response = make_client(engine_probe=fail).get("/api/v1/health/", headers=AUTH)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = response.json()
    assert body["error"]["code"] == "service_unavailable"
    assert response.headers["X-Opal-Transaction-Id"]
    assert response.headers["X-Opal-Request-Id"]


def test_missing_bearer_token_returns_opal_error(make_client):
    response = make_client().get("/api/v1/info/")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert response.headers["X-Opal-Transaction-Id"]
    assert response.headers["X-Opal-Request-Id"]


def test_invalid_bearer_token_returns_opal_error(make_client):
    response = make_client().get("/api/v1/info/", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_api_route_returns_opal_error(make_client):
    response = make_client().get("/api/v1/missing", headers=AUTH)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"
