import pytest

from multi_agent_app.agents import BaseAgent
from multi_agent_app.orchestrator import OrchestrationError, Orchestrator
from multi_agent_app.storage import Storage


class SuccessAgent(BaseAgent):
    name = "success"

    def run(self, task):
        return f"Success for {task.description}"


class FailingAgent(BaseAgent):
    name = "failing"

    def run(self, task):
        raise RuntimeError("agent failed intentionally")


def test_orchestrator_success_sets_owner_and_result_kind():
    storage = Storage(db_path=":memory:")
    orchestrator = Orchestrator(storage, agents={"success": SuccessAgent()})

    session = orchestrator.create_session("Route Test")
    task = orchestrator.create_task(session.id, "Check routing")
    action = orchestrator.route_task(task, "success")

    assert action.agent_name == "success"
    assert action.kind == "result"

    stored_task = storage.get_task(task.id)
    assert stored_task is not None
    assert stored_task.owner_agent == "success"
    assert stored_task.status == "completed"

    memory = storage.list_memory_for_task(task.id)
    assert len(memory) == 1
    assert memory[0].source_agent == "success"

    storage.close()


def test_orchestrator_failure_sets_failed_and_error_action():
    storage = Storage(db_path=":memory:")
    orchestrator = Orchestrator(storage, agents={"failing": FailingAgent()})

    session = orchestrator.create_session("Failure Test")
    task = orchestrator.create_task(session.id, "Trigger failure")

    with pytest.raises(OrchestrationError):
        orchestrator.route_task(task, "failing")

    stored_task = storage.get_task(task.id)
    assert stored_task is not None
    assert stored_task.owner_agent == "failing"
    assert stored_task.status == "failed"

    actions = storage.list_agent_actions(task.id)
    assert len(actions) == 1
    assert actions[0].kind == "error"
    assert "intentionally" in actions[0].content

    storage.close()
