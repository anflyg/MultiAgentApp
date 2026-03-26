from __future__ import annotations

import json
from pathlib import Path


def test_memory_openapi_contract_has_required_paths_and_schemas():
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "openapi" / "memory_api.openapi.json"
    assert schema_path.exists()

    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    assert payload["openapi"].startswith("3.")
    assert "paths" in payload
    assert "components" in payload

    paths = payload["paths"]
    assert "/health" in paths
    assert "/memory" in paths
    assert "/memory/orient" in paths
    assert "/memory/search" in paths
    assert "/memory/{id}" in paths

    assert paths["/health"]["get"]["operationId"] == "getHealth"
    assert paths["/memory"]["post"]["operationId"] == "postMemoryCreate"
    assert paths["/memory/orient"]["post"]["operationId"] == "postMemoryOrient"
    assert paths["/memory/search"]["post"]["operationId"] == "postMemorySearch"
    assert paths["/memory/{id}"]["get"]["operationId"] == "getMemoryById"

    schemas = payload["components"]["schemas"]
    assert "MemoryCreateRequest" in schemas
    assert "MemoryOrientRequest" in schemas
    assert "MemoryOrientResponse" in schemas
    assert "MemoryObject" in schemas
    assert "ErrorResponse" in schemas

    get_memory_schema = (
        paths["/memory/{id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    assert get_memory_schema["$ref"] == "#/components/schemas/MemoryObject"
