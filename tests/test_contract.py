from __future__ import annotations

import yaml
from openapi_spec_validator import validate

from opal_look_yolo.main import create_app

EXPECTED_OPERATIONS = {
    ("GET", "/api/v1/info/"): "yolo_info_show",
    ("GET", "/api/v1/health/"): "yolo_info_health",
    ("GET", "/api/v1/engine/"): "yolo_engines_list",
    ("POST", "/api/v1/engine/discover"): "yolo_engines_discover",
    ("GET", "/api/v1/engine/{engine_id}"): "yolo_engines_show",
    ("GET", "/api/v1/engine/{engine_id}/capabilities"): "yolo_engines_capabilities",
    ("GET", "/api/v1/model/"): "yolo_models_list",
    ("GET", "/api/v1/model/{model_id}"): "yolo_models_show",
    ("POST", "/api/v1/model/{model_id}/load"): "yolo_models_load",
    ("POST", "/api/v1/model/{model_id}/unload"): "yolo_models_unload",
    ("GET", "/api/v1/hardware/"): "yolo_hardware_list",
    ("GET", "/api/v1/hardware/{device_id}"): "yolo_hardware_show",
    ("POST", "/api/v1/predict"): "yolo_predict",
    ("POST", "/api/v1/predict/frame"): "yolo_predict_frame",
}


def contract_spec():
    with open("openapi/opal_look_yolo.yaml", encoding="utf-8") as source:
        return yaml.safe_load(source)


def test_source_contract_is_valid_openapi():
    spec = contract_spec()

    validate(spec)

    assert spec["info"]["version"] == "2.0.0-mvp-plus"


def test_application_schema_covers_every_contract_operation():
    spec = contract_spec()
    generated = create_app().openapi()

    for (method, path), operation_id in EXPECTED_OPERATIONS.items():
        contract_operation = spec["paths"][path][method.lower()]
        generated_operation = generated["paths"][path][method.lower()]

        assert contract_operation["operationId"] == operation_id
        assert generated_operation["operationId"] == operation_id
        assert set(contract_operation["responses"]).issubset(generated_operation["responses"])
        assert generated_operation["security"] == [{"BearerAuth": []}]

    assert generated["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }


def test_application_has_no_extra_api_operations():
    generated_paths = {
        (method.upper(), path)
        for path, item in create_app().openapi()["paths"].items()
        for method in item
    }

    assert generated_paths == set(EXPECTED_OPERATIONS)
