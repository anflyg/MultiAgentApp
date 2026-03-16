from multi_agent_app.cli import run_example_flow


def test_cli_example_flow_returns_expected_objects():
    result = run_example_flow(
        db_path=":memory:",
        session_name="CLI Session",
        task_description="Test the CLI flow",
        agent_name="planner",
    )

    assert result["session"].name == "CLI Session"
    assert result["task"].description == "Test the CLI flow"
    assert result["action"].agent_name == "planner"
    assert len(result["memory_items"]) == 1
