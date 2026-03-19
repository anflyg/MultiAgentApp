from multi_agent_app import models
from multi_agent_app.storage import Storage


def test_store_and_get_decision():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Decision Session")
    storage.add_session(session)

    decision = models.Decision(
        session_id=session.id,
        title="Use SQLite",
        topic="Persistence",
        decision_text="Use SQLite for local persistence.",
        rationale="Simple and portable.",
        background="Need fast local setup for pilot teams.",
        assumptions="No strict multi-writer requirement in phase 1.",
        risks="Potential locking under high write load.",
        alternatives_considered="PostgreSQL in managed cloud.",
        consequences="Simpler deploy path, possible future migration cost.",
        follow_up_notes="Re-evaluate after traffic exceeds expected baseline.",
        owner="team",
        tags=["db", "local"],
    )
    storage.add_decision(decision)

    fetched = storage.get_decision(decision.id)
    assert fetched is not None
    assert fetched.title == "Use SQLite"
    assert fetched.background == "Need fast local setup for pilot teams."
    assert fetched.assumptions == "No strict multi-writer requirement in phase 1."
    assert fetched.risks == "Potential locking under high write load."
    assert fetched.alternatives_considered == "PostgreSQL in managed cloud."
    assert fetched.consequences == "Simpler deploy path, possible future migration cost."
    assert fetched.follow_up_notes == "Re-evaluate after traffic exceeds expected baseline."
    assert fetched.tags == ["db", "local"]
    storage.close()


def test_list_decisions_for_session():
    storage = Storage(db_path=":memory:")
    session_a = models.Session(name="A")
    session_b = models.Session(name="B")
    storage.add_session(session_a)
    storage.add_session(session_b)

    storage.add_decision(
        models.Decision(
            session_id=session_a.id,
            title="A1",
            topic="Topic",
            decision_text="Decision A1",
        )
    )
    storage.add_decision(
        models.Decision(
            session_id=session_b.id,
            title="B1",
            topic="Topic",
            decision_text="Decision B1",
        )
    )

    decisions = storage.list_decisions_for_session(session_a.id)
    assert len(decisions) == 1
    assert decisions[0].title == "A1"
    storage.close()


def test_list_active_decisions_only():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Active Session")
    storage.add_session(session)

    storage.add_decision(
        models.Decision(
            session_id=session.id,
            title="Active",
            topic="Topic",
            decision_text="Active decision",
            status="active",
        )
    )
    storage.add_decision(
        models.Decision(
            session_id=session.id,
            title="Superseded",
            topic="Topic",
            decision_text="Old decision",
            status="superseded",
        )
    )

    active_decisions = storage.list_active_decisions()
    assert len(active_decisions) == 1
    assert active_decisions[0].title == "Active"
    storage.close()
