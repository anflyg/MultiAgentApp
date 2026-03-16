from multi_agent_app.orchestrator import Orchestrator
from multi_agent_app.storage import Storage


def test_orchestrator_routes_correct_agent():
    storage = Storage(db_path=":memory:")

    orchestrator = Orchestrator(
        storage,
        agents={
            "alpha": lambda task: f"Alpha handled {task.description}",
            "beta": lambda task: f"Beta handled {task.description}",
        },
    )

    session = orchestrator.create_session("Route Test")
    task = orchestrator.create_task(session.id, "Check routing")
    action = orchestrator.route_task(task, "beta")

    assert action.agent_name == "beta"
    assert "Beta handled" in action.content

    actions = storage.list_agent_actions(task.id)
    assert len(actions) == 1
    assert actions[0].agent_name == "beta"

    tasks = storage.list_tasks(session.id)
    assert tasks[0].status == "completed"

    storage.close()
