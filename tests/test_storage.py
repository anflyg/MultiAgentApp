import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

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


def test_storage_recent_and_open_decision_helpers():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Helper Session")
    storage.add_session(session)

    decision = models.Decision(
        session_id=session.id,
        title="Decision A",
        topic="Topic",
        decision_text="Use option A",
    )
    storage.add_decision(decision)

    candidate = models.DecisionCandidate(
        session_id=session.id,
        title="Candidate A",
        topic="Topic",
        candidate_text="Maybe option B",
        status="proposed",
    )
    storage.add_decision_candidate(candidate)

    storage.add_session_event(
        models.SessionEvent(
            session_id=session.id,
            event_type="decision_created",
            message="Decision created",
        )
    )
    storage.add_session_event(
        models.SessionEvent(
            session_id=session.id,
            event_type="decision_candidate_created",
            message="Candidate created",
        )
    )

    suggestion = models.DecisionSuggestion(
        source_decision_id=decision.id,
        target_decision_id=decision.id,
        suggestion_type="possible_conflict",
        reason="Review conflict",
    )
    # Need distinct source/target ids for FK and uniqueness constraints.
    decision_b = models.Decision(
        session_id=session.id,
        title="Decision B",
        topic="Topic",
        decision_text="Use option B",
    )
    storage.add_decision(decision_b)
    suggestion = models.DecisionSuggestion(
        source_decision_id=decision.id,
        target_decision_id=decision_b.id,
        suggestion_type="possible_conflict",
        reason="Review conflict",
    )
    storage.add_decision_suggestion(suggestion)

    recent_events = storage.list_recent_session_events(limit=1)
    assert len(recent_events) == 1
    assert recent_events[0].event_type in {"decision_created", "decision_candidate_created"}

    open_candidates = storage.list_open_decision_candidates()
    assert len(open_candidates) == 1
    assert open_candidates[0].id == candidate.id

    open_suggestions = storage.list_open_decision_suggestions()
    assert len(open_suggestions) == 1
    assert open_suggestions[0].id == suggestion.id

    storage.close()


def test_storage_migrates_decision_context_columns_for_existing_db(tmp_path):
    db_path = tmp_path / "legacy_decisions.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );
            CREATE TABLE decisions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                decision_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        session_id = str(uuid4())
        decision_id = str(uuid4())
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn.execute(
            "INSERT INTO sessions (id, name, status, created_at) VALUES (?, ?, ?, ?)",
            (session_id, "Legacy", "active", created_at),
        )
        conn.execute(
            """
            INSERT INTO decisions (id, session_id, title, topic, decision_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (decision_id, session_id, "Legacy Decision", "Ops", "Keep rollout", created_at),
        )
        conn.commit()
    finally:
        conn.close()

    storage = Storage(db_path=str(db_path))
    try:
        fetched = storage.get_decision(decision_id)
        assert fetched is not None
        assert fetched.title == "Legacy Decision"
        assert fetched.background is None
        assert fetched.assumptions is None
        assert fetched.risks is None
        assert fetched.alternatives_considered is None
        assert fetched.consequences is None
        assert fetched.follow_up_notes is None
    finally:
        storage.close()
