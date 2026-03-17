import pytest

from multi_agent_app import models
from multi_agent_app.cli import (
    confirm_decision_candidate,
    create_decision_candidate,
    create_session,
    dismiss_decision_candidate,
)
from multi_agent_app.storage import Storage


def test_store_and_get_decision_candidate():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Candidate Session")
    storage.add_session(session)

    candidate = models.DecisionCandidate(
        session_id=session.id,
        title="Use SLA",
        topic="Operations",
        candidate_text="Set internal SLA to 24h",
        tags=["ops"],
    )
    storage.add_decision_candidate(candidate)

    fetched = storage.get_decision_candidate(candidate.id)
    assert fetched is not None
    assert fetched.title == "Use SLA"
    assert fetched.status == "proposed"
    storage.close()


def test_list_candidates_for_session():
    storage = Storage(db_path=":memory:")
    session_a = models.Session(name="A")
    session_b = models.Session(name="B")
    storage.add_session(session_a)
    storage.add_session(session_b)
    storage.add_decision_candidate(
        models.DecisionCandidate(
            session_id=session_a.id,
            title="A candidate",
            topic="Topic",
            candidate_text="A text",
        )
    )
    storage.add_decision_candidate(
        models.DecisionCandidate(
            session_id=session_b.id,
            title="B candidate",
            topic="Topic",
            candidate_text="B text",
        )
    )

    candidates = storage.list_decision_candidates_for_session(session_a.id)
    assert len(candidates) == 1
    assert candidates[0].title == "A candidate"
    storage.close()


def test_list_open_decision_candidates_only():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Open Candidates")
    storage.add_session(session)
    proposed = models.DecisionCandidate(
        session_id=session.id,
        title="Proposed",
        topic="Topic",
        candidate_text="Text",
    )
    confirmed = models.DecisionCandidate(
        session_id=session.id,
        title="Confirmed",
        topic="Topic",
        candidate_text="Text",
        status="confirmed",
    )
    storage.add_decision_candidate(proposed)
    storage.add_decision_candidate(confirmed)

    open_candidates = storage.list_open_decision_candidates()
    assert len(open_candidates) == 1
    assert open_candidates[0].id == proposed.id
    storage.close()


def test_confirm_candidate_creates_decision_and_updates_status(tmp_path):
    db_path = tmp_path / "candidate_confirm.db"
    session = create_session(str(db_path), "Candidate confirm")
    candidate = create_decision_candidate(
        db_path=str(db_path),
        session_id=session.id,
        title="Use SQLite",
        topic="Storage",
        candidate_text="SQLite should remain default",
    )

    updated_candidate, decision = confirm_decision_candidate(str(db_path), candidate.id)
    assert updated_candidate.status == "confirmed"
    assert decision.title == "Use SQLite"

    storage = Storage(db_path=str(db_path))
    try:
        stored_decision = storage.get_decision(decision.id)
        assert stored_decision is not None
        events = storage.list_session_events(session.id)
        assert any(event.event_type == "decision_created" for event in events)
        assert any(event.event_type == "decision_candidate_confirmed" for event in events)
    finally:
        storage.close()


def test_dismiss_candidate_updates_status(tmp_path):
    db_path = tmp_path / "candidate_dismiss.db"
    session = create_session(str(db_path), "Candidate dismiss")
    candidate = create_decision_candidate(
        db_path=str(db_path),
        session_id=session.id,
        title="Dismiss me",
        topic="Topic",
        candidate_text="Dismiss this",
    )

    updated = dismiss_decision_candidate(str(db_path), candidate.id)
    assert updated.status == "dismissed"


def test_invalid_candidate_id_fails_clearly(tmp_path):
    db_path = tmp_path / "candidate_invalid.db"
    with pytest.raises(ValueError, match="was not found"):
        confirm_decision_candidate(str(db_path), "no-such-candidate")


def test_confirming_non_proposed_candidate_fails_clearly(tmp_path):
    db_path = tmp_path / "candidate_non_proposed.db"
    session = create_session(str(db_path), "Non proposed")
    candidate = create_decision_candidate(
        db_path=str(db_path),
        session_id=session.id,
        title="Already handled",
        topic="Topic",
        candidate_text="Candidate text",
    )
    dismiss_decision_candidate(str(db_path), candidate.id)

    with pytest.raises(ValueError, match="cannot be confirmed"):
        confirm_decision_candidate(str(db_path), candidate.id)
