from __future__ import annotations

from fastapi import status

AUTH = {"Authorization": "Bearer test-token"}
CORRELATION = {
    "X-Opal-Session-Id": "session-1",
    "X-Opal-Transaction-Id": "transaction-1",
    "X-Opal-Request-Id": "request-1",
    "X-Opal-Causation-Id": "causation-1",
}


def test_retired_info_route_returns_not_found(make_client):
    response = make_client().get("/api/v1/info/", headers={**AUTH, **CORRELATION})

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"


def test_health_returns_kernel_report_and_correlation_headers(make_client):
    client = make_client()
    response = client.get("/api/v1/health/", headers={**AUTH, **CORRELATION})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["name"] == "opal-look-yolo-svc"
    assert body["version"] == "0.1.0"
    assert body["api_version"] == "v1"
    assert body["status"] == "ok"
    assert body["live"] is True
    assert body["ready"] is True
    assert body["details"]["engine_available"] is True
    assert body["active_profile_id"] is None
    assert body["pending_restart_fields"] == []
    assert body["uptime_seconds"] >= 0
    assert body["checked_at"]
    assert response.headers["X-Opal-Session-Id"] == "session-1"
    assert response.headers["X-Opal-Transaction-Id"] == "transaction-1"
    assert response.headers["X-Opal-Request-Id"] == "request-1"
    assert response.headers["X-Opal-Causation-Id"] == "causation-1"


def test_health_generates_required_correlation_headers(make_client):
    response = make_client().get("/api/v1/health/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["X-Opal-Transaction-Id"]
    assert response.headers["X-Opal-Request-Id"]
    assert "X-Opal-Session-Id" not in response.headers
    assert "X-Opal-Causation-Id" not in response.headers


def test_health_reports_degraded_when_engine_is_unavailable(make_client):
    response = make_client(engine_probe=lambda: False).get("/api/v1/health/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "degraded"
    assert body["ready"] is False
    assert body["details"]["engine_available"] is False


def test_health_probe_failure_still_reports_200(make_client):
    """The report itself is produced (kernel: 503 only when it cannot be)."""

    def fail() -> bool:
        raise RuntimeError("probe failed")

    response = make_client(engine_probe=fail).get("/api/v1/health/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "degraded"
    assert body["details"]["engine_available"] is False
    assert response.headers["X-Opal-Transaction-Id"]
    assert response.headers["X-Opal-Request-Id"]


def test_missing_bearer_token_returns_opal_error(make_client):
    response = make_client().get("/api/v1/health/")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert response.headers["X-Opal-Transaction-Id"]
    assert response.headers["X-Opal-Request-Id"]


def test_invalid_bearer_token_returns_opal_error(make_client):
    response = make_client().get(
        "/api/v1/health/", headers={"Authorization": "Bearer wrong-token"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_api_route_returns_opal_error(make_client):
    response = make_client().get("/api/v1/missing", headers=AUTH)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"
