import sys

import pytest

from multi_agent_app.cli import (
    add_task_to_session,
    alpha_demo_setup,
    create_session,
    get_session_status,
    list_memory_for_session,
    list_tasks_for_session,
    main,
    route_task_by_id,
    run_example_flow,
)
from multi_agent_app.storage import Storage


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


def test_cli_create_decision_command_adds_event(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "decision_create_cli.db"
    session = create_session(str(db_path), "Decision Session")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "create-decision",
            "--session-id",
            session.id,
            "--title",
            "Use SQLite",
            "--topic",
            "Persistence",
            "--text",
            "Use SQLite as decision store",
            "--rationale",
            "Portable and simple",
            "--owner",
            "platform",
            "--tag",
            "db",
            "--tag",
            "step1",
        ],
    )
    main()
    captured = capsys.readouterr().out
    assert "Created decision:" in captured
    assert "Use SQLite" in captured

    storage = Storage(db_path=str(db_path))
    try:
        events = storage.list_session_events(session.id)
        assert any(event.event_type == "decision_created" for event in events)
    finally:
        storage.close()


def test_cli_list_decisions_command(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "decision_list_cli.db"
    session = create_session(str(db_path), "Decision List Session")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "create-decision",
            "--session-id",
            session.id,
            "--title",
            "Keep logs",
            "--topic",
            "Observability",
            "--text",
            "Retain logs for 30 days",
        ],
    )
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-decisions",
            "--session-id",
            session.id,
        ],
    )
    main()
    session_output = capsys.readouterr().out
    assert "Decisions" in session_output
    assert "Keep logs" in session_output

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-decisions",
        ],
    )
    main()
    global_output = capsys.readouterr().out
    assert "all active" in global_output
    assert "Keep logs" in global_output


def test_cli_create_decision_invalid_session_fails(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "decision_invalid_create_cli.db"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "create-decision",
            "--session-id",
            "DIN_SESSION_ID",
            "--title",
            "Invalid",
            "--topic",
            "Validation",
            "--text",
            "Should fail",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Decision creation failed" in output
    assert "DIN_SESSION_ID" in output


def test_cli_list_decisions_invalid_session_fails(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "decision_invalid_list_cli.db"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-decisions",
            "--session-id",
            "DIN_SESSION_ID",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Decision listing failed" in output
    assert "DIN_SESSION_ID" in output


def test_cli_create_and_list_decision_candidates(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "candidate_cli.db"
    session = create_session(str(db_path), "Candidate CLI Session")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "create-decision-candidate",
            "--session-id",
            session.id,
            "--title",
            "Keep default DB",
            "--topic",
            "Persistence",
            "--text",
            "Keep SQLite for local use",
            "--tag",
            "db",
        ],
    )
    main()
    create_output = capsys.readouterr().out
    assert "Created decision candidate:" in create_output

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-decision-candidates",
        ],
    )
    main()
    list_output = capsys.readouterr().out
    assert "all proposed" in list_output
    assert "Keep default DB" in list_output


def test_cli_confirm_invalid_candidate_id_fails(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "candidate_confirm_invalid_cli.db"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "confirm-decision-candidate",
            "--candidate-id",
            "NOPE",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Decision candidate confirmation failed" in output


def test_cli_confirm_non_proposed_candidate_fails(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "candidate_confirm_non_proposed_cli.db"
    session = create_session(str(db_path), "Candidate status session")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "create-decision-candidate",
            "--session-id",
            session.id,
            "--title",
            "Candidate",
            "--topic",
            "Topic",
            "--text",
            "Text",
        ],
    )
    main()
    create_output = capsys.readouterr().out
    candidate_id = next(line.split(": ", 1)[1].strip() for line in create_output.splitlines() if line.startswith("Created decision candidate:"))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "dismiss-decision-candidate",
            "--candidate-id",
            candidate_id,
        ],
    )
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "confirm-decision-candidate",
            "--candidate-id",
            candidate_id,
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "cannot be confirmed" in output


def test_cli_list_decision_candidates_invalid_session_fails(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "candidate_invalid_session_cli.db"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-decision-candidates",
            "--session-id",
            "DIN_SESSION_ID",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Decision candidate listing failed" in output


def test_alpha_demo_setup_function_and_command(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "alpha_demo_setup.db"
    result = alpha_demo_setup(db_path=str(db_path))
    assert result["session"].id
    assert result["active_decision"].id
    assert result["candidate"].id
    assert result["panel_question"].id
    assert result["assessment"].alignment in {
        "aligned",
        "clarification_needed",
        "potential_deviation",
        "likely_new_decision_required",
    }

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "alpha-demo-setup",
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Alpha demo is ready." in output
    assert "Panel question id:" in output
    assert "Suggested follow-up commands:" in output

    storage = Storage(db_path=str(db_path))
    try:
        questions = storage.list_panel_questions(limit=5)
        assert questions
    finally:
        storage.close()


def test_cli_default_run_prints_onboarding_tip(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "default_cli_onboarding.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Session ID:" in output
    assert "Onboarding tip:" in output
    assert "alpha-demo-setup" in output
    assert "tui" in output
