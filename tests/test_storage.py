from multi_agent_app import models
from multi_agent_app.storage import Storage


def test_storage_roundtrip():
    storage = Storage(db_path=":memory:")

    session = models.Session(name="Test Session")
    storage.add_session(session)

    task = models.Task(session_id=session.id, description="Do something")
    storage.add_task(task)

    action = models.AgentAction(task_id=task.id, agent_name="tester", content="Did it")
    storage.add_agent_action(action)

    memory = models.MemoryItem(session_id=session.id, content="Remember this")
    storage.add_memory_items([memory])

    fetched_session = storage.get_session(session.id)
    assert fetched_session is not None
    assert fetched_session.name == "Test Session"

    tasks = storage.list_tasks(session.id)
    assert len(tasks) == 1
    assert tasks[0].description == "Do something"

    actions = storage.list_agent_actions(task.id)
    assert len(actions) == 1
    assert actions[0].content == "Did it"

    memories = storage.list_memory_items(session.id)
    assert len(memories) == 1
    assert memories[0].content == "Remember this"

    storage.close()
