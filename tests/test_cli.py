import sys

from multi_agent_app.cli import (
    add_task_to_session,
    create_session,
    get_session_status,
    list_memory_for_session,
    list_tasks_for_session,
    main,
    route_task_by_id,
    run_example_flow,
)


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
            "list-memory",
            "--session-id",
            result["session"].id,
        ],
    )
    main()
    captured = capsys.readouterr().out
    assert "memory item(s)" in captured
    assert "Drafted text for" in captured


def test_multiple_tasks_in_one_session_and_list_tasks(tmp_path):
    db_path = tmp_path / "multi_tasks.db"
    session = create_session(str(db_path), "Incremental Session")
    task1 = add_task_to_session(str(db_path), session.id, "First task")
    task2 = add_task_to_session(str(db_path), session.id, "Second task")

    tasks = list_tasks_for_session(str(db_path), session.id)
    task_ids = {task.id for task in tasks}
    assert len(tasks) == 2
    assert task1.id in task_ids
    assert task2.id in task_ids


def test_session_status_across_multiple_tasks(tmp_path):
    db_path = tmp_path / "status_tasks.db"
    session = create_session(str(db_path), "Status Session")
    task1 = add_task_to_session(str(db_path), session.id, "Task one")
    task2 = add_task_to_session(str(db_path), session.id, "Task two")

    assert get_session_status(str(db_path), session.id) == "active"

    route_task_by_id(str(db_path), task1.id, "writer")
    assert get_session_status(str(db_path), session.id) == "active"

    route_task_by_id(str(db_path), task2.id, "planner")
    assert get_session_status(str(db_path), session.id) == "completed"


def test_cli_list_tasks_command_prints_entries(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "list_tasks_cli.db"
    session = create_session(str(db_path), "List Tasks Session")
    add_task_to_session(str(db_path), session.id, "One task")
    add_task_to_session(str(db_path), session.id, "Two task")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-tasks",
            "--session-id",
            session.id,
        ],
    )
    main()
    captured = capsys.readouterr().out
    assert "2 task(s)" in captured
    assert "One task" in captured
    assert "Two task" in captured


def test_cli_run_task_command(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "run_task_cli.db"
    session = create_session(str(db_path), "Run Task Session")
    task = add_task_to_session(str(db_path), session.id, "Execute me")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "run-task",
            "--task-id",
            task.id,
            "--agent",
            "writer",
        ],
    )
    main()
    captured = capsys.readouterr().out
    assert "Ran task" in captured
    assert "Drafted text for" in captured


def test_cli_show_session_command(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "show_session_cli.db"
    session = create_session(str(db_path), "Show Session")
    task = add_task_to_session(str(db_path), session.id, "Inspect me")
    route_task_by_id(str(db_path), task.id, "planner")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "show-session",
            "--session-id",
            session.id,
        ],
    )
    main()
    captured = capsys.readouterr().out
    assert "Session" in captured
    assert "Tasks: 1" in captured
    assert "History:" in captured
