import sys

from multi_agent_app.cli import list_memory_for_session, main, run_example_flow


def test_cli_example_flow_returns_expected_objects():
    result = run_example_flow(
        db_path=":memory:",
        session_name="CLI Session",
        task_description="Test the CLI flow",
        agent_name="planner",
    )

    assert result["session"].name == "CLI Session"
    assert result["session"].status == "completed"
    assert result["task"].description == "Test the CLI flow"
    assert result["task"].status == "completed"
    assert result["task"].owner_agent == "planner"
    assert result["action"].agent_name == "planner"
    assert result["action"].kind == "result"
    assert len(result["memory_items"]) == 1


def test_cli_list_memory_for_session(tmp_path):
    db_path = tmp_path / "cli_memory.db"
    result = run_example_flow(
        db_path=str(db_path),
        session_name="Memory Session",
        task_description="Capture memory",
        agent_name="writer",
    )
    memory_items = list_memory_for_session(str(db_path), result["session"].id)
    assert len(memory_items) == 1


def test_cli_list_memory_prints_entries(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "cli_memory_print.db"
    result = run_example_flow(
        db_path=str(db_path),
        session_name="Memory Print Session",
        task_description="Capture memory for print",
        agent_name="writer",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "--list-memory",
            result["session"].id,
        ],
    )
    main()
    captured = capsys.readouterr().out
    assert "memory item(s)" in captured
    assert "Drafted text for" in captured
