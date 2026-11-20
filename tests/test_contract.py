from __future__ import annotations

from pathlib import Path

import yaml
from openapi_spec_validator import validate

from opal_look_yolo.main import create_app

SPEC_PATH = Path("openapi/engines/opal_look_yolo.yaml")

# Target operations not yet implemented. Shrinks as migration steps land;
# must be empty at completion. Tracked per (METHOD, path).
PENDING_OPERATIONS = {
    ("POST", "/api/v1/config/save"),
    ("POST", "/api/v1/config/load"),
    ("POST", "/api/v1/config/validate"),
    ("GET", "/api/v1/profile/"),
    ("POST", "/api/v1/profile/"),
    ("GET", "/api/v1/profile/{profile_id}"),
    ("PATCH", "/api/v1/profile/{profile_id}"),
    ("DELETE", "/api/v1/profile/{profile_id}"),
    ("POST", "/api/v1/profile/{profile_id}/activate"),
    ("POST", "/api/v1/service/start"),
    ("POST", "/api/v1/service/stop"),
    ("GET", "/api/v1/service/log"),
}


def contract_spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def resolved_operations() -> dict[tuple[str, str], str]:
    """{(METHOD, path): operation_id} with kernel pathItem $refs resolved."""
    kernel = yaml.safe_load(
        (SPEC_PATH.parent.parent / "shared" / "opal_kernel.yaml").read_text(
            encoding="utf-8"
        )
    )
    operations: dict[tuple[str, str], str] = {}
    for path, item in contract_spec()["paths"].items():
        if "$ref" in item:
            ref = item["$ref"]
            assert ref.startswith("../shared/opal_kernel.yaml#/"), ref
            node: object = kernel
            for part in ref.split("#")[1].lstrip("/").split("/"):
                node = node[part]
            item = node
        for method, operation in item.items():
            if method in ("get", "post", "put", "patch", "delete"):
                operations[(method.upper(), path)] = operation["operationId"]
    return operations


def test_source_contract_is_valid_openapi():
    spec = contract_spec()

    validate(spec, base_uri=SPEC_PATH.resolve().as_uri())

    assert spec["info"]["version"] == "0.1.0"


def test_application_schema_covers_implemented_contract_operations():
    generated = create_app().openapi()
    generated_paths = {
        (method.upper(), path): operation
        for path, item in generated["paths"].items()
        for method, operation in item.items()
    }
    target = resolved_operations()

    for (method, path), operation_id in target.items():
        if (method, path) in PENDING_OPERATIONS:
            continue
        generated_operation = generated_paths[(method, path)]
        assert generated_operation["operationId"] == operation_id
        assert generated_operation["security"] == [{"BearerAuth": []}]

    assert generated["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }


def test_generated_surface_matches_target_minus_pending():
    """No extra operations beyond the contract; every implemented target
    operation is served (tracked pending ops are explicitly listed)."""
    generated_paths = {
        (method.upper(), path)
        for path, item in create_app().openapi()["paths"].items()
        for method in item
    }

    assert generated_paths == set(resolved_operations()) - PENDING_OPERATIONS
