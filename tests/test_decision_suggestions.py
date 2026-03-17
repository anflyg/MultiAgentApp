import sys

import pytest

from multi_agent_app import models
from multi_agent_app.cli import (
    accept_decision_suggestion,
    create_decision,
    create_session,
    dismiss_decision_suggestion,
    list_decision_suggestions,
    main,
    suggest_decision_links,
)
from multi_agent_app.storage import Storage


def test_store_and_get_decision_suggestion():
    storage = Storage(db_path=":memory:")
    session = models.Session(name="Suggestion Store Session")
    storage.add_session(session)
    source = models.Decision(session_id=session.id, title="Source", topic="Topic", decision_text="Source text")
    target = models.Decision(session_id=session.id, title="Target", topic="Topic", decision_text="Target text")
    storage.add_decision(source)
    storage.add_decision(target)

    suggestion = models.DecisionSuggestion(
        source_decision_id=source.id,
        target_decision_id=target.id,
        suggestion_type="related_decision",
        reason="Decisions share topic.",
    )
    storage.add_decision_suggestion(suggestion)

    fetched = storage.get_decision_suggestion(suggestion.id)
    assert fetched is not None
    assert fetched.suggestion_type == "related_decision"
    assert fetched.status == "open"
    storage.close()


def test_generate_suggestions_for_same_topic_decisions(tmp_path):
    db_path = tmp_path / "suggest_same_topic.db"
    session = create_session(str(db_path), "Same Topic Session")
    source = create_decision(str(db_path), session.id, "Source", "Policy", "Use SQLite.")
    create_decision(str(db_path), session.id, "Target", "Policy", "Use SQLite.")

    suggestions = suggest_decision_links(str(db_path), source.id)
    assert any(s.suggestion_type == "related_decision" for s in suggestions)
    assert all("share topic" in s.reason for s in suggestions)


def test_generate_possible_supersedes_for_same_topic_different_text(tmp_path):
    db_path = tmp_path / "suggest_possible_supersedes.db"
    session = create_session(str(db_path), "Supersedes Suggestion Session")
    source = create_decision(str(db_path), session.id, "Source", "Policy", "Use PostgreSQL.")
    create_decision(str(db_path), session.id, "Target", "Policy", "Use SQLite.")

    suggestions = suggest_decision_links(str(db_path), source.id)
    types = {s.suggestion_type for s in suggestions}
    assert "related_decision" in types
    assert "possible_supersedes" in types


def test_list_suggestions_for_decision_includes_source_and_target(tmp_path):
    db_path = tmp_path / "suggest_list_for_decision.db"
    session = create_session(str(db_path), "List Suggestion Session")
    source = create_decision(str(db_path), session.id, "Source", "TopicA", "Text A")
    target = create_decision(str(db_path), session.id, "Target", "TopicA", "Text B")

    suggest_decision_links(str(db_path), source.id)
    source_view = list_decision_suggestions(str(db_path), decision_id=source.id)
    target_view = list_decision_suggestions(str(db_path), decision_id=target.id)
    assert len(source_view) >= 1
    assert len(target_view) >= 1


def test_accept_possible_supersedes_creates_supersedes_link(tmp_path):
    db_path = tmp_path / "suggest_accept_supersedes.db"
    session = create_session(str(db_path), "Accept Supersedes Session")
    source = create_decision(str(db_path), session.id, "Source", "Storage", "Use Postgres.")
    target = create_decision(str(db_path), session.id, "Target", "Storage", "Use SQLite.")

    suggestions = suggest_decision_links(str(db_path), source.id)
    suggestion = next(s for s in suggestions if s.suggestion_type == "possible_supersedes")
    updated, link = accept_decision_suggestion(str(db_path), suggestion.id)

    assert updated.status == "accepted"
    assert link.relation_type == "supersedes"
    storage = Storage(db_path=str(db_path))
    try:
        target_decision = storage.get_decision(target.id)
        assert target_decision is not None
        assert target_decision.status == "superseded"
        events = storage.list_session_events(session.id)
        assert any(event.event_type == "decision_suggestion_accepted" for event in events)
    finally:
        storage.close()


def test_accept_related_decision_creates_supplements_link(tmp_path):
    db_path = tmp_path / "suggest_accept_related.db"
    session = create_session(str(db_path), "Accept Related Session")
    source = create_decision(str(db_path), session.id, "Source", "UI", "Use a sidebar.")
    target = create_decision(str(db_path), session.id, "Target", "UI", "Use a sidebar.")

    suggestions = suggest_decision_links(str(db_path), source.id)
    suggestion = next(s for s in suggestions if s.suggestion_type == "related_decision")
    updated, link = accept_decision_suggestion(str(db_path), suggestion.id)

    assert updated.status == "accepted"
    assert link.relation_type == "supplements"


def test_dismiss_suggestion_updates_status(tmp_path):
    db_path = tmp_path / "suggest_dismiss.db"
    session = create_session(str(db_path), "Dismiss Suggestion Session")
    source = create_decision(str(db_path), session.id, "Source", "Ops", "Enable alerts.")
    create_decision(str(db_path), session.id, "Target", "Ops", "Enable alerts.")

    suggestions = suggest_decision_links(str(db_path), source.id)
    suggestion = next(s for s in suggestions if s.suggestion_type == "related_decision")
    updated = dismiss_decision_suggestion(str(db_path), suggestion.id)
    assert updated.status == "dismissed"


def test_invalid_suggestion_id_fails_clearly(tmp_path):
    db_path = tmp_path / "suggest_invalid_id.db"
    create_session(str(db_path), "Invalid Suggestion Session")

    with pytest.raises(ValueError, match="Decision suggestion 'NOPE' was not found"):
        accept_decision_suggestion(str(db_path), "NOPE")
    with pytest.raises(ValueError, match="Decision suggestion 'NOPE' was not found"):
        dismiss_decision_suggestion(str(db_path), "NOPE")


def test_accepting_already_handled_suggestion_fails_clearly(tmp_path):
    db_path = tmp_path / "suggest_double_accept.db"
    session = create_session(str(db_path), "Double Accept Session")
    source = create_decision(str(db_path), session.id, "Source", "Auth", "Use SSO.")
    create_decision(str(db_path), session.id, "Target", "Auth", "Use SSO.")

    suggestions = suggest_decision_links(str(db_path), source.id)
    suggestion = next(s for s in suggestions if s.suggestion_type == "related_decision")
    accept_decision_suggestion(str(db_path), suggestion.id)

    with pytest.raises(ValueError, match="cannot be accepted"):
        accept_decision_suggestion(str(db_path), suggestion.id)


def test_list_open_suggestions_only_returns_open(tmp_path):
    db_path = tmp_path / "suggest_list_open.db"
    session = create_session(str(db_path), "List Open Session")
    source = create_decision(str(db_path), session.id, "Source", "Docs", "Keep changelog.")
    create_decision(str(db_path), session.id, "Target", "Docs", "Keep changelog.")

    suggestions = suggest_decision_links(str(db_path), source.id)
    suggestion = next(s for s in suggestions if s.suggestion_type == "related_decision")
    dismiss_decision_suggestion(str(db_path), suggestion.id)

    open_suggestions = list_decision_suggestions(str(db_path))
    assert all(s.status == "open" for s in open_suggestions)
    assert all(s.id != suggestion.id for s in open_suggestions)


def test_cli_suggest_and_list_open_suggestions(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "suggest_cli.db"
    session = create_session(str(db_path), "Suggestion CLI Session")
    source = create_decision(str(db_path), session.id, "Source", "API", "Use REST.")
    create_decision(str(db_path), session.id, "Target", "API", "Use GraphQL.")

    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--db-path", str(db_path), "suggest-decision-links", "--decision-id", source.id],
    )
    main()
    suggest_output = capsys.readouterr().out
    assert "Created decision suggestions:" in suggest_output
    assert "possible_supersedes" in suggest_output

    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--db-path", str(db_path), "list-decision-suggestions"],
    )
    main()
    list_output = capsys.readouterr().out
    assert "Decision suggestions (all open)" in list_output
    assert "open/related_decision" in list_output


def test_cli_accept_suggestion_creates_decision_link(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "suggest_accept_cli.db"
    session = create_session(str(db_path), "Accept Suggestion CLI Session")
    source = create_decision(str(db_path), session.id, "Source", "Cache", "Use Redis.")
    target = create_decision(str(db_path), session.id, "Target", "Cache", "Use Memcached.")
    suggestions = suggest_decision_links(str(db_path), source.id)
    suggestion = next(s for s in suggestions if s.suggestion_type == "possible_supersedes")

    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--db-path", str(db_path), "accept-decision-suggestion", "--suggestion-id", suggestion.id],
    )
    main()
    output = capsys.readouterr().out
    assert "Accepted decision suggestion" in output
    assert "Relation: supersedes" in output

    storage = Storage(db_path=str(db_path))
    try:
        incoming = storage.list_incoming_links(target.id)
        assert any(link.from_decision_id == source.id and link.relation_type == "supersedes" for link in incoming)
    finally:
        storage.close()
