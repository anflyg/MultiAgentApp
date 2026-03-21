import sys

import pytest

from multi_agent_app import models
from multi_agent_app.cli import create_decision, create_session, link_decisions, main
from multi_agent_app.storage import Storage


def test_store_and_get_decision_link():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Decision Link Session")
    storage.add_session(session)

    decision_a = models.Decision(
        session_id=session.id,
        title="A",
        topic="Topic",
        decision_text="Decision A",
    )
    decision_b = models.Decision(
        session_id=session.id,
        title="B",
        topic="Topic",
        decision_text="Decision B",
    )
    storage.add_decision(decision_a)
    storage.add_decision(decision_b)

    link = models.DecisionLink(
        from_decision_id=decision_b.id,
        to_decision_id=decision_a.id,
        relation_type="clarifies",
    )
    storage.add_decision_link(link)

    fetched = storage.get_decision_link(link.id)
    assert fetched is not None
    assert fetched.from_decision_id == decision_b.id
    assert fetched.to_decision_id == decision_a.id
    assert fetched.relation_type == "clarifies"
    storage.close()


def test_list_links_for_decision_includes_incoming_and_outgoing():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Decision Link Listing")
    storage.add_session(session)

    decision_a = models.Decision(session_id=session.id, title="A", topic="Topic", decision_text="A")
    decision_b = models.Decision(session_id=session.id, title="B", topic="Topic", decision_text="B")
    decision_c = models.Decision(session_id=session.id, title="C", topic="Topic", decision_text="C")
    storage.add_decision(decision_a)
    storage.add_decision(decision_b)
    storage.add_decision(decision_c)

    storage.add_decision_link(
        models.DecisionLink(
            from_decision_id=decision_a.id,
            to_decision_id=decision_b.id,
            relation_type="clarifies",
        )
    )
    storage.add_decision_link(
        models.DecisionLink(
            from_decision_id=decision_c.id,
            to_decision_id=decision_a.id,
            relation_type="supplements",
        )
    )

    all_links = storage.list_links_for_decision(decision_a.id)
    outgoing_links = storage.list_outgoing_links(decision_a.id)
    incoming_links = storage.list_incoming_links(decision_a.id)
    assert len(all_links) == 2
    assert len(outgoing_links) == 1
    assert len(incoming_links) == 1
    storage.close()


def test_supersedes_updates_target_decision_status(tmp_path):
    db_path = tmp_path / "decision_link_supersedes.db"
    session = create_session(str(db_path), "Supersedes Session")
    old_decision = create_decision(str(db_path), session.id, "Old", "Topic", "Old decision")
    new_decision = create_decision(str(db_path), session.id, "New", "Topic", "New decision")

    link = link_decisions(str(db_path), new_decision.id, old_decision.id, "supersedes")
    assert link.relation_type == "supersedes"

    storage = Storage(db_path=str(db_path))
    try:
        updated_target = storage.get_decision(old_decision.id)
        assert updated_target is not None
        assert updated_target.status == "superseded"

        events = storage.list_session_events(session.id)
        assert any(event.event_type == "decision_link_created" for event in events)
        assert any(
            "supersedes" in event.message and new_decision.id in event.message and old_decision.id in event.message
            for event in events
            if event.event_type == "decision_link_created"
        )
    finally:
        storage.close()


def test_clarifies_does_not_change_target_status(tmp_path):
    db_path = tmp_path / "decision_link_clarifies.db"
    session = create_session(str(db_path), "Clarifies Session")
    target_decision = create_decision(str(db_path), session.id, "Target", "Topic", "Target decision")
    source_decision = create_decision(str(db_path), session.id, "Source", "Topic", "Source decision")

    link_decisions(str(db_path), source_decision.id, target_decision.id, "clarifies")

    storage = Storage(db_path=str(db_path))
    try:
        updated_target = storage.get_decision(target_decision.id)
        assert updated_target is not None
        assert updated_target.status == "active"
    finally:
        storage.close()


def test_supplements_does_not_change_target_status(tmp_path):
    db_path = tmp_path / "decision_link_supplements.db"
    session = create_session(str(db_path), "Supplements Session")
    target_decision = create_decision(str(db_path), session.id, "Target", "Topic", "Target decision")
    source_decision = create_decision(str(db_path), session.id, "Source", "Topic", "Source decision")

    link_decisions(str(db_path), source_decision.id, target_decision.id, "supplements")

    storage = Storage(db_path=str(db_path))
    try:
        updated_target = storage.get_decision(target_decision.id)
        assert updated_target is not None
        assert updated_target.status == "active"
    finally:
        storage.close()


def test_self_link_fails_clearly(tmp_path):
    db_path = tmp_path / "decision_link_self.db"
    session = create_session(str(db_path), "Self Link Session")
    decision = create_decision(str(db_path), session.id, "Only", "Topic", "Single decision")

    with pytest.raises(ValueError, match="cannot be linked to itself"):
        link_decisions(str(db_path), decision.id, decision.id, "clarifies")


def test_invalid_decision_ids_fail_clearly(tmp_path):
    db_path = tmp_path / "decision_link_invalid_ids.db"
    session = create_session(str(db_path), "Invalid Id Session")
    decision = create_decision(str(db_path), session.id, "Real", "Topic", "Real decision")

    with pytest.raises(ValueError, match="Source decision 'NOPE_SOURCE' was not found"):
        link_decisions(str(db_path), "NOPE_SOURCE", decision.id, "clarifies")

    with pytest.raises(ValueError, match=f"Target decision 'NOPE_TARGET' was not found"):
        link_decisions(str(db_path), decision.id, "NOPE_TARGET", "clarifies")


def test_show_decision_includes_relation_info(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "show_decision_link_cli.db"
    session = create_session(str(db_path), "Show Decision Session")
    old_decision = create_decision(str(db_path), session.id, "Old", "Topic", "Old decision")
    new_decision = create_decision(
        str(db_path),
        session.id,
        "New",
        "Topic",
        "New decision",
        background="Background details",
        assumptions="Assumptions details",
        risks="Risk details",
        alternatives_considered="Alternative details",
        consequences="Consequence details",
        follow_up_notes="Follow-up details",
    )
    storage = Storage(db_path=str(db_path))
    try:
        storage.add_reasoning_item(
            models.ReasoningItem(
                decision_id=new_decision.id,
                kind="objection",
                content="Objection: rollout timeline may be too aggressive.",
                source_type="manual",
            )
        )
    finally:
        storage.close()
    link_decisions(str(db_path), new_decision.id, old_decision.id, "clarifies")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "show-decision",
            "--decision-id",
            new_decision.id,
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Background: Background details" in output
    assert "Assumptions: Assumptions details" in output
    assert "Risks: Risk details" in output
    assert "Alternatives considered: Alternative details" in output
    assert "Consequences: Consequence details" in output
    assert "Follow-up notes: Follow-up details" in output
    assert "Key reasoning notes: 1" in output
    assert "Critical objection:" in output
    assert "rollout timeline may be too aggressive" in output
    assert "Outgoing links: 1" in output
    assert "Incoming links: 0" in output
    assert "clarifies" in output
    assert old_decision.id in output


def test_link_creation_writes_events_to_both_sessions_when_cross_session(tmp_path):
    db_path = tmp_path / "decision_link_cross_session_events.db"
    source_session = create_session(str(db_path), "Source Session")
    target_session = create_session(str(db_path), "Target Session")
    source_decision = create_decision(str(db_path), source_session.id, "Source", "Topic", "Source decision")
    target_decision = create_decision(str(db_path), target_session.id, "Target", "Topic", "Target decision")

    link_decisions(str(db_path), source_decision.id, target_decision.id, "clarifies")

    storage = Storage(db_path=str(db_path))
    try:
        source_events = storage.list_session_events(source_session.id)
        target_events = storage.list_session_events(target_session.id)
        assert any(event.event_type == "decision_link_created" for event in source_events)
        assert any(event.event_type == "decision_link_created" for event in target_events)
    finally:
        storage.close()


def test_list_decision_links_command_lists_links(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "decision_link_list_cli.db"
    session = create_session(str(db_path), "List Link Session")
    target_decision = create_decision(str(db_path), session.id, "Target", "Topic", "Target decision")
    source_decision = create_decision(str(db_path), session.id, "Source", "Topic", "Source decision")
    link_decisions(str(db_path), source_decision.id, target_decision.id, "supplements")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-decision-links",
            "--decision-id",
            target_decision.id,
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Decision links" in output
    assert "supplements" in output
    assert source_decision.id in output
    assert target_decision.id in output
