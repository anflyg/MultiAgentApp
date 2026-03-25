from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIServer, make_server

from .memory_orientation import orient_question_to_memory_by_db
from .memory_retrieval import get_workspace_memory, list_workspace_memories, retrieve_relevant_memory_matches
from .storage import Storage

WSGIApp = Callable[[dict, Callable], list[bytes]]


def create_memory_api_app(
    *,
    db_path: str,
    api_token: str | None = None,
) -> WSGIApp:
    expected_token = (api_token or "").strip()

    def app(environ: dict, start_response: Callable) -> list[bytes]:
        method = (environ.get("REQUEST_METHOD") or "GET").upper()
        path = environ.get("PATH_INFO") or "/"
        query = parse_qs(environ.get("QUERY_STRING") or "", keep_blank_values=False)

        if expected_token and not _authorized(environ, expected_token):
            return _json_response(
                start_response,
                {"error": "unauthorized"},
                status="401 Unauthorized",
            )

        if method == "GET" and path == "/health":
            return _json_response(
                start_response,
                {"status": "ok", "db_path": db_path},
            )

        if method == "POST" and path == "/memory/orient":
            payload = _read_json_body(environ)
            question = str(payload.get("question", "")).strip()
            workspace_id = payload.get("workspace_id")
            limit = int(payload.get("limit", 3))
            try:
                result = orient_question_to_memory_by_db(
                    db_path=db_path,
                    question=question,
                    workspace_id=str(workspace_id) if workspace_id else None,
                    limit=limit,
                )
            except ValueError as exc:
                return _json_response(
                    start_response,
                    {"error": str(exc)},
                    status="400 Bad Request",
                )
            return _json_response(start_response, result.model_dump())

        if method == "GET" and path.startswith("/memory/"):
            memory_id = path.removeprefix("/memory/").strip()
            if not memory_id:
                return _json_response(
                    start_response,
                    {"error": "memory id is required"},
                    status="400 Bad Request",
                )
            workspace_id = _single(query.get("workspace_id"))
            storage = Storage(db_path=db_path)
            try:
                if workspace_id:
                    memory = get_workspace_memory(
                        storage,
                        workspace_id=workspace_id,
                        memory_id=memory_id,
                    )
                else:
                    memory = storage.get_socrates_memory(memory_id)
            finally:
                storage.close()
            if memory is None:
                return _json_response(
                    start_response,
                    {"error": "memory not found"},
                    status="404 Not Found",
                )
            return _json_response(start_response, memory.model_dump())

        if method == "POST" and path == "/memory/search":
            payload = _read_json_body(environ)
            workspace_id = payload.get("workspace_id")
            limit = int(payload.get("limit", 10))
            query_text = str(payload.get("query", "")).strip()
            storage = Storage(db_path=db_path)
            try:
                if workspace_id:
                    scoped_workspace = str(workspace_id)
                else:
                    scoped_workspace = storage.get_active_workspace().id
                if query_text:
                    matches = retrieve_relevant_memory_matches(
                        storage,
                        workspace_id=scoped_workspace,
                        question=query_text,
                        limit=limit,
                    )
                    items = [
                        {
                            "id": match.memory.id,
                            "title": match.memory.title,
                            "summary": match.memory.summary,
                            "relevance_score": round(match.relevance_score, 3),
                            "match_basis": match.match_basis,
                        }
                        for match in matches
                    ]
                else:
                    items = [
                        memory.model_dump()
                        for memory in list_workspace_memories(
                            storage,
                            workspace_id=scoped_workspace,
                            limit=limit,
                        )
                    ]
            finally:
                storage.close()
            return _json_response(
                start_response,
                {
                    "workspace": scoped_workspace,
                    "count": len(items),
                    "items": items,
                },
            )

        return _json_response(
            start_response,
            {"error": "not_found"},
            status="404 Not Found",
        )

    return app


def run_memory_api_server(
    *,
    db_path: str,
    host: str = "127.0.0.1",
    port: int = 8001,
    api_token: str | None = None,
) -> None:
    app = create_memory_api_app(db_path=db_path, api_token=api_token)
    with make_server(host, port, app) as server:  # type: WSGIServer
        server.serve_forever()


def _single(values: list[str] | None) -> str | None:
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _authorized(environ: dict, expected_token: str) -> bool:
    header = (environ.get("HTTP_AUTHORIZATION") or "").strip()
    if not header.startswith("Bearer "):
        return False
    provided = header.removeprefix("Bearer ").strip()
    return bool(provided) and provided == expected_token


def _read_json_body(environ: dict) -> dict[str, object]:
    raw_length = environ.get("CONTENT_LENGTH") or "0"
    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        length = 0
    body = b""
    if length > 0:
        body = environ["wsgi.input"].read(length)
    if not body:
        return {}
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_response(
    start_response: Callable,
    payload: dict[str, object],
    *,
    status: str = "200 OK",
) -> list[bytes]:
    body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
