from __future__ import annotations

import pytest
from starlette.requests import Request

from opal_look_yolo.errors import OpalException
from opal_look_yolo.precondition import check_if_match, require_if_match
from opal_look_yolo.store import Store

AUTH = {"Authorization": "Bearer test-token"}


def _request(if_match: str | None) -> Request:
    headers = [] if if_match is None else [(b"if-match", if_match.encode())]
    return Request({"type": "http", "method": "PUT", "headers": headers})


def test_error_envelope_carries_correlation_ids(make_client):
    client = make_client()
    response = client.get("/api/v1/nope", headers=AUTH)
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Opal-Request-Id"]
    assert error["transaction_id"] == response.headers["X-Opal-Transaction-Id"]
    assert error["session_id"] is None
    assert error["causation_id"] is None


def test_error_envelope_echoes_supplied_correlation_ids(make_client):
    client = make_client()
    headers = {
        **AUTH,
        "X-Opal-Session-Id": "sess-1",
        "X-Opal-Transaction-Id": "txn-1",
        "X-Opal-Request-Id": "req-1",
        "X-Opal-Causation-Id": "cause-1",
    }
    response = client.get("/api/v1/nope", headers=headers)
    error = response.json()["error"]
    assert error["request_id"] == "req-1"
    assert error["transaction_id"] == "txn-1"
    assert error["session_id"] == "sess-1"
    assert error["causation_id"] == "cause-1"


def test_invalid_correlation_header_returns_422(make_client):
    client = make_client()
    response = client.get(
        "/api/v1/health/", headers={**AUTH, "X-Opal-Request-Id": "bad value"}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_correlation_header"


def test_store_revision_bumps_inside_write_txn():
    store = Store()
    before = store.config_revision()
    with store.write_txn():
        store.bump_revision()
        assert store.config_revision() != before
    assert store.config_revision() != before


def test_store_write_txn_rolls_back_on_failure():
    store = Store()
    revision = store.config_revision()
    with pytest.raises(RuntimeError):
        with store.write_txn():
            store.settings.set("k", 1)
            store.bump_revision()
            raise RuntimeError("boom")
    assert store.config_revision() == revision
    assert store.settings.overrides() == {}


def test_store_write_txn_nests_via_savepoint():
    store = Store()
    with store.write_txn():
        store.settings.set("a", 1)
        with pytest.raises(RuntimeError):
            with store.write_txn():
                store.settings.set("b", 2)
                raise RuntimeError("inner")
        store.settings.set("c", 3)
    assert store.settings.overrides() == {"a": 1, "c": 3}


def test_require_if_match_missing_is_428():
    with pytest.raises(OpalException) as exc:
        require_if_match(_request(None))
    assert exc.value.status_code == 428


def test_require_if_match_weak_or_malformed_is_422():
    for bad in ('W/"abc"', '"a","b"', "abc", '"'):
        with pytest.raises(OpalException) as exc:
            require_if_match(_request(bad))
        assert exc.value.status_code == 422, bad


def test_check_if_match_stale_is_412_and_star_passes():
    store = Store()
    with store.write_txn():
        with pytest.raises(OpalException) as exc:
            check_if_match(_request('"stale"'), store)
        assert exc.value.status_code == 412
        check_if_match(_request("*"), store)
        check_if_match(_request(store.config_revision()), store)


def test_persistent_store_roundtrips_revision_and_overrides(tmp_path):
    first = Store(tmp_path / "data")
    with first.write_txn():
        first.settings.set("max_image_bytes", 123)
    revision = first.config_revision()
    first.close()

    second = Store(tmp_path / "data")
    assert second.config_revision() == revision
    assert second.settings.overrides() == {"max_image_bytes": 123}
    second.close()
