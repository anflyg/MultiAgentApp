import sys

import pytest

from multi_agent_app.cli import main
from multi_agent_app.memory_core import SocratesMemory
from multi_agent_app.storage import Storage


def test_cli_memory_orient_outputs_orientation_payload(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "cli_memory_orient.db"
    storage = Storage(db_path=str(db_path))
    try:
        workspace = storage.create_workspace(name="CLI Orient WS", description="")
        storage.save_socrates_memory(
            SocratesMemory(
                workspace_id=workspace.id,
                title="Nordic expansion memory",
                summary="Stepwise expansion in Norway.",
                decision_text="Keep margin guardrail in place.",
            )
        )
    finally:
        storage.close()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "memory-orient",
            "--workspace-id",
            workspace.id,
            "--question",
            "How should we think about expansion in Norway?",
            "--limit",
            "2",
        ],
    )
    main()
    output = capsys.readouterr().out
    assert '"top_matches": [' in output
    assert '"workspace": "' in output
    assert '"memory_belongs":' in output
    assert '"novelty_assessment":' in output
    assert '"reasoning":' in output


def test_cli_serve_memory_api_invokes_runner(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "cli_serve_api.db"
    called: dict[str, object] = {}

    def _fake_run_memory_api_server(*, db_path: str, host: str, port: int, api_token: str | None) -> None:
        called["db_path"] = db_path
        called["host"] = host
        called["port"] = port
        called["api_token"] = api_token

    monkeypatch.setattr("multi_agent_app.cli.run_memory_api_server", _fake_run_memory_api_server)
    monkeypatch.setenv("MULTI_AGENT_APP_API_TOKEN", "env-token")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "serve-memory-api",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
        ],
    )

    main()
    output = capsys.readouterr().out
    assert "Starting memory API on http://127.0.0.1:8010" in output
    assert called == {
        "db_path": str(db_path),
        "host": "127.0.0.1",
        "port": 8010,
        "api_token": "env-token",
    }


def test_cli_memory_orient_requires_question(tmp_path, monkeypatch):
    db_path = tmp_path / "cli_orient_missing_question.db"
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--db-path", str(db_path), "memory-orient"],
    )
    with pytest.raises(SystemExit):
        main()
