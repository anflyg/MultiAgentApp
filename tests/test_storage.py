from multi_agent_app import models
from multi_agent_app.storage import Storage


def test_storage_persists_richer_fields():
    storage = Storage(db_path=":memory:")

    session = models.Session(name="Test Session", status="active")
    storage.add_session(session)

    task = models.Task(
        session_id=session.id,
        description="Do something",
        priority=3,
        owner_agent="writer",
        status="in_progress",
    )
    storage.add_task(task)

    action = models.AgentAction(
        session_id=session.id,
        task_id=task.id,
        agent_name="writer",
        kind="result",
        content="Did it",
    )
    storage.add_agent_action(action)

    memory = models.MemoryItem(
        session_id=session.id,
        scope="session",
        kind="decision",
        source_agent="writer",
        task_id=task.id,
        content="Remember this",
    )
    storage.add_memory_items([memory])

    fetched_session = storage.get_session(session.id)
    assert fetched_session is not None
    assert fetched_session.status == "active"

    fetched_task = storage.get_task(task.id)
    assert fetched_task is not None
    assert fetched_task.priority == 3
    assert fetched_task.owner_agent == "writer"

    actions_by_task = storage.list_agent_actions(task.id)
    assert len(actions_by_task) == 1
    assert actions_by_task[0].kind == "result"

    actions_by_session = storage.list_agent_actions_for_session(session.id)
    assert len(actions_by_session) == 1
    assert actions_by_session[0].session_id == session.id

    memory_by_session = storage.list_memory_items(session.id)
    assert len(memory_by_session) == 1
    assert memory_by_session[0].kind == "decision"

    memory_by_task = storage.list_memory_for_task(task.id)
    assert len(memory_by_task) == 1
    assert memory_by_task[0].source_agent == "writer"

    storage.add_session_event(
        models.SessionEvent(
            session_id=session.id,
            event_type="session_status_changed",
            message="Session status changed: active -> completed",
        )
    )
    events = storage.list_session_events(session.id)
    assert len(events) == 1
    assert events[0].event_type == "session_status_changed"

    history = storage.list_session_history(session.id)
    assert len(history) >= 3
    assert any(item["source"] == "event" for item in history)
    assert any(item["source"] == "agent_action" for item in history)
    assert any(item["source"] == "memory" for item in history)

    storage.close()
