from __future__ import annotations

from fastapi import status

from opal_look_yolo.models import LocalModelRepository

AUTH = {"Authorization": "Bearer test-token"}


def make_repository(tmp_path):
    root = tmp_path / "models"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "detector.pt").write_bytes(b"pt-weights")
    (nested / "segmenter.onnx").write_bytes(b"onnx-weights")
    (root / "notes.txt").write_text("not a model", encoding="utf-8")
    return LocalModelRepository([root])


def test_model_list_returns_discovered_models(make_client, tmp_path):
    client = make_client(model_repository=make_repository(tmp_path))

    response = client.get("/api/v1/model/", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    models = {model["model_id"]: model for model in response.json()}
    assert set(models) == {"detector", "segmenter"}
    assert models["detector"]["engine_id"] == "yolo"
    assert models["detector"]["tasks"] == ["detect"]
    assert models["detector"]["loaded"] is False
    assert models["detector"]["available"] is True
    assert models["detector"]["metadata"]["format"] == "pt"


def test_model_show_returns_metadata(make_client, tmp_path):
    client = make_client(model_repository=make_repository(tmp_path))

    response = client.get("/api/v1/model/segmenter", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["model_id"] == "segmenter"
    assert response.json()["metadata"]["format"] == "onnx"


def test_unknown_model_returns_not_found(make_client, tmp_path):
    client = make_client(model_repository=make_repository(tmp_path))

    response = client.get("/api/v1/model/missing", headers=AUTH)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == {"model_id": "missing"}


def test_duplicate_model_stems_get_stable_unique_ids(tmp_path):
    root = tmp_path / "models"
    first = root / "one"
    second = root / "two"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "same.pt").write_bytes(b"one")
    (second / "same.pt").write_bytes(b"two")

    records = LocalModelRepository([root]).list_records()

    assert len(records) == 2
    assert len({record.model_id for record in records}) == 2
    assert {record.model_id for record in records} != {"same"}


def test_missing_model_directory_returns_empty_catalog(tmp_path):
    repository = LocalModelRepository([tmp_path / "missing"])

    assert repository.list_records() == []
