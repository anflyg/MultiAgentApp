from __future__ import annotations

import io
import json

from multi_agent_app.api_server import create_memory_api_app
from multi_agent_app.memory_core import SocratesMemory
from multi_agent_app.storage import Storage

def _call_app(
    app,
    *,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    auth_header: str | None = None,
    query: str = "",
) -> tuple[int, dict[str, str], dict[str, object]]:
    body_bytes = b""
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")

    environ = {
        "REQUEST_METHOD": method.upper(),
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body_bytes)),
        "wsgi.input": io.BytesIO(body_bytes),
    }
    if auth_header:
        environ["HTTP_AUTHORIZATION"] = auth_header

    status_holder: dict[str, object] = {}

    def _start_response(status: str, headers: list[tuple[str, str]]) -> None:
        status_holder["status"] = status
        status_holder["headers"] = dict(headers)

    body = b"".join(app(environ, _start_response))
    status_code = int(str(status_holder["status"]).split(" ", 1)[0])
    headers = status_holder["headers"] if isinstance(status_holder.get("headers"), dict) else {}
    parsed = json.loads(body.decode("utf-8")) if body else {}
    return status_code, headers, parsed


def test_api_health_endpoint(tmp_path):
    db_path = tmp_path / "api_health.db"
    app = create_memory_api_app(db_path=str(db_path))
    status_code, _, payload = _call_app(app, method="GET", path="/health")
    assert status_code == 200
    assert payload["status"] == "ok"
    assert payload["db_path"] == str(db_path)


def test_api_memory_orient_endpoint(tmp_path):
    db_path = tmp_path / "api_orient.db"
    storage = Storage(db_path=str(db_path))
    try:
        workspace = storage.create_workspace(name="API Orient WS", description="")
        storage.save_socrates_memory(
            SocratesMemory(
                workspace_id=workspace.id,
                title="Nordic expansion memory",
                summary="Stepwise expansion in Norway with margin guardrail.",
                decision_text="Continue only when margin is stable.",
            )
        )
    finally:
        storage.close()

    app = create_memory_api_app(db_path=str(db_path))
    status_code, _, payload = _call_app(
        app,
        method="POST",
        path="/memory/orient",
        payload={
            "question": "How should we handle Norway expansion with margin guardrail?",
            "workspace_id": workspace.id,
            "limit": 2,
        },
    )
    assert status_code == 200
    assert payload["workspace"] == workspace.id
    assert payload["top_matches"]
    assert payload["top_matches"][0]["title"] == "Nordic expansion memory"
    assert payload["novelty_assessment"] in {"existing", "partly_new", "new"}


def test_api_memory_read_endpoint_and_auth(tmp_path):
    db_path = tmp_path / "api_read.db"
    storage = Storage(db_path=str(db_path))
    try:
        workspace = storage.create_workspace(name="API Read WS", description="")
        memory = SocratesMemory(
            workspace_id=workspace.id,
            title="Liquidity safety memory",
            summary="Keep 12 month runway.",
        )
        storage.save_socrates_memory(memory)
    finally:
        storage.close()

    app = create_memory_api_app(db_path=str(db_path), api_token="secret-token")
    unauthorized_status, _, _ = _call_app(
        app,
        method="GET",
        path=f"/memory/{memory.id}",
    )
    assert unauthorized_status == 401

    authorized_status, _, payload = _call_app(
        app,
        method="GET",
        path=f"/memory/{memory.id}",
        auth_header="Bearer secret-token",
    )
    assert authorized_status == 200
    assert payload["id"] == memory.id
    assert payload["title"] == "Liquidity safety memory"


def test_api_memory_create_endpoint(tmp_path):
    db_path = tmp_path / "api_create.db"
    storage = Storage(db_path=str(db_path))
    try:
        workspace = storage.create_workspace(name="API Create WS", description="")
    finally:
        storage.close()

    app = create_memory_api_app(db_path=str(db_path), api_token="secret-token")

    status_code, _, payload = _call_app(
        app,
        method="POST",
        path="/memory",
        auth_header="Bearer secret-token",
        payload={
            "workspace_id": workspace.id,
            "title": "Board decision memory",
            "summary": "Preserve optionality in Q3 funding timeline.",
            "assumptions": ["Revenue target remains on track"],
        },
    )
    assert status_code == 201
    assert payload["workspace_id"] == workspace.id
    assert payload["title"] == "Board decision memory"
    assert payload["summary"] == "Preserve optionality in Q3 funding timeline."

    read_status, _, read_payload = _call_app(
        app,
        method="GET",
        path=f"/memory/{payload['id']}",
        auth_header="Bearer secret-token",
    )
    assert read_status == 200
    assert read_payload["id"] == payload["id"]
    assert read_payload["title"] == "Board decision memory"
