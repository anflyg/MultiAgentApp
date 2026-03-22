import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest

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


def test_storage_add_and_list_reasoning_items_for_decision_and_question():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Reasoning Session")
    storage.add_session(session)

    decision = models.Decision(
        session_id=session.id,
        title="Rollout policy",
        topic="Release",
        decision_text="Use staged rollout.",
    )
    storage.add_decision(decision)
    question = models.ExecutiveQuestion(
        question_text="Should we speed up rollout?",
        topic="Release",
        session_id=session.id,
    )
    storage.add_panel_question(question)

    storage.add_reasoning_item(
        models.ReasoningItem(
            decision_id=decision.id,
            kind="risk",
            content="Fast rollout can increase incident risk.",
            source_type="panel",
            memory_level="formal_decision",
        )
    )
    storage.add_reasoning_item(
        models.ReasoningItem(
            question_id=question.id,
            kind="open_question",
            content="Do we have enough on-call coverage this week?",
            source_type="operator",
            memory_level="transient",
        )
    )

    decision_items = storage.list_reasoning_items_for_decision(decision.id)
    question_items = storage.list_reasoning_items_for_question(question.id)

    assert len(decision_items) == 1
    assert decision_items[0].kind == "risk"
    assert decision_items[0].source_type == "panel"
    assert decision_items[0].memory_level == "formal_decision"

    assert len(question_items) == 1
    assert question_items[0].kind == "open_question"
    assert question_items[0].source_type == "operator"
    assert question_items[0].memory_level == "transient"
    storage.close()


def test_storage_reasoning_item_requires_decision_or_question_reference():
    storage = Storage(db_path=":memory:")
    try:
        with pytest.raises(ValueError, match="must reference either decision_id or question_id"):
            storage.add_reasoning_item(
                models.ReasoningItem(
                    kind="assumption",
                    content="Assume stable traffic.",
                    source_type="system",
                )
            )
    finally:
        storage.close()


def test_storage_workspaces_active_state_and_question_scope():
    storage = Storage(db_path=":memory:")
    try:
        default_workspace = storage.get_active_workspace()
        assert default_workspace.name == "Default"

        workspace = storage.create_workspace(
            name="Finance",
            description="Budget and forecast work",
        )
        selected = storage.set_active_workspace(workspace.id)
        assert selected.id == workspace.id
        assert storage.get_active_workspace().id == workspace.id

        session = models.Session(name="Finance Session", workspace_id=workspace.id)
        storage.add_session(session)
        fetched_session = storage.get_session(session.id)
        assert fetched_session is not None
        assert fetched_session.workspace_id == workspace.id

        question = models.ExecutiveQuestion(
            question_text="Can we increase Q3 budget?",
            topic="Budget",
        )
        storage.add_panel_question(question)
        workspace_questions = storage.list_panel_questions(workspace_id=workspace.id)
        assert len(workspace_questions) == 1
        assert workspace_questions[0].workspace_id == workspace.id
    finally:
        storage.close()


def test_storage_workspace_scoped_lists_for_dashboard_and_panel():
    storage = Storage(db_path=":memory:")
    try:
        ws_a = storage.create_workspace(name="A", description="Workspace A")
        ws_b = storage.create_workspace(name="B", description="Workspace B")

        session_a = models.Session(name="Session A", workspace_id=ws_a.id)
        session_b = models.Session(name="Session B", workspace_id=ws_b.id)
        storage.add_session(session_a)
        storage.add_session(session_b)

        decision_a = models.Decision(
            session_id=session_a.id,
            title="A decision",
            topic="Ops",
            decision_text="A path",
        )
        decision_b = models.Decision(
            session_id=session_b.id,
            title="B decision",
            topic="Ops",
            decision_text="B path",
        )
        storage.add_decision(decision_a)
        storage.add_decision(decision_b)

        candidate_a = models.DecisionCandidate(
            session_id=session_a.id,
            title="A candidate",
            topic="Ops",
            candidate_text="A candidate path",
        )
        candidate_b = models.DecisionCandidate(
            session_id=session_b.id,
            title="B candidate",
            topic="Ops",
            candidate_text="B candidate path",
        )
        storage.add_decision_candidate(candidate_a)
        storage.add_decision_candidate(candidate_b)

        suggestion_a = models.DecisionSuggestion(
            source_decision_id=decision_a.id,
            target_decision_id=decision_a.id,
            suggestion_type="related_decision",
            reason="A scope",
        )
        suggestion_b = models.DecisionSuggestion(
            source_decision_id=decision_b.id,
            target_decision_id=decision_b.id,
            suggestion_type="related_decision",
            reason="B scope",
        )
        # self-links are not valid for realistic usage, but valid FK-wise for this storage-level filter test.
        storage.add_decision_suggestion(suggestion_a)
        storage.add_decision_suggestion(suggestion_b)

        storage.add_session_event(
            models.SessionEvent(
                session_id=session_a.id,
                event_type="decision_created",
                message="A event",
            )
        )
        storage.add_session_event(
            models.SessionEvent(
                session_id=session_b.id,
                event_type="decision_created",
                message="B event",
            )
        )

        assert [d.id for d in storage.list_active_decisions(workspace_id=ws_a.id)] == [decision_a.id]
        assert [c.id for c in storage.list_open_decision_candidates(workspace_id=ws_a.id)] == [candidate_a.id]
        assert [s.id for s in storage.list_open_suggestions(workspace_id=ws_a.id)] == [suggestion_a.id]
        assert [e.session_id for e in storage.list_recent_session_events(workspace_id=ws_a.id)] == [session_a.id]
    finally:
        storage.close()


def test_storage_can_rename_workspace_and_keep_active_workspace_id():
    storage = Storage(db_path=":memory:")
    try:
        workspace = storage.create_workspace(name="Operations", description="Ops desc")
        storage.set_active_workspace(workspace.id)
        updated = storage.update_workspace(
            workspace.id,
            name="Executive Ops",
            description="Exec-level operations",
        )
        assert updated.id == workspace.id
        assert updated.name == "Executive Ops"
        assert updated.description == "Exec-level operations"
        assert storage.get_active_workspace().id == workspace.id
        assert storage.get_active_workspace().name == "Executive Ops"
    finally:
        storage.close()


def test_storage_reasoning_items_migrate_memory_level_default(tmp_path):
    db_path = tmp_path / "legacy_reasoning_visibility.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE reasoning_items (
                id TEXT PRIMARY KEY,
                decision_id TEXT,
                question_id TEXT,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'system',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO reasoning_items (id, decision_id, question_id, kind, content, source_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                None,
                "Q-legacy",
                "open_question",
                "Legacy reasoning without explicit visibility.",
                "system",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    storage = Storage(db_path=str(db_path))
    try:
        items = storage.list_reasoning_items_for_question("Q-legacy")
        assert len(items) == 1
        assert items[0].memory_level == "private_context"
    finally:
        storage.close()
