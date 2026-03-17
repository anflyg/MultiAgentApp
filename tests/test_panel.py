import sys

from multi_agent_app import models
from multi_agent_app.cli import ask_decision_panel, create_decision, create_session, main
from multi_agent_app.panel import assess_question_against_active_decisions, build_context_packet
from multi_agent_app.storage import Storage


def test_store_and_get_panel_question():
    storage = Storage(db_path=":memory:")
    question = models.PanelQuestion(question="Should we change DB?", topic="Persistence")
    storage.add_panel_question(question)

    fetched = storage.get_panel_question(question.id)
    assert fetched is not None
    assert fetched.question == "Should we change DB?"
    assert fetched.topic == "Persistence"
    storage.close()


def test_store_and_list_panel_responses():
    storage = Storage(db_path=":memory:")
    question = models.PanelQuestion(question="What next?", topic="Roadmap")
    storage.add_panel_question(question)
    responses = [
        models.PanelResponse(question_id=question.id, agent_name="strateg", response_text="Direction is stable."),
        models.PanelResponse(question_id=question.id, agent_name="analyst", response_text="Some assumptions unclear."),
    ]
    storage.add_panel_responses(responses)

    fetched = storage.list_panel_responses(question.id)
    assert len(fetched) == 2
    assert fetched[0].agent_name == "strateg"
    assert fetched[1].agent_name == "analyst"
    storage.close()


def test_retrieval_returns_active_and_superseded_by_topic(tmp_path):
    db_path = tmp_path / "panel_retrieval.db"
    session = create_session(str(db_path), "Panel Retrieval")
    active = create_decision(str(db_path), session.id, "Active", "API", "Keep REST API.")
    create_decision(str(db_path), session.id, "Other Topic", "Infra", "Unrelated")
    storage = Storage(db_path=str(db_path))
    try:
        old = models.Decision(
            session_id=session.id,
            title="Old",
            topic="API",
            decision_text="Use SOAP API.",
            status="superseded",
        )
        storage.add_decision(old)
        context = build_context_packet(storage, topic="API")
        active_ids = {decision.id for decision in context["active_decisions"]}
        historical_ids = {decision.id for decision in context["historical_decisions"]}
        assert active.id in active_ids
        assert old.id in historical_ids
    finally:
        storage.close()


def test_ask_decision_panel_with_relevant_decisions_stores_question_and_responses(tmp_path):
    db_path = tmp_path / "panel_with_data.db"
    session = create_session(str(db_path), "Panel Data")
    create_decision(str(db_path), session.id, "Direction", "Platform", "Use SQLite.")

    question, context, assessment, responses, combined, likely_new_decision, next_step = ask_decision_panel(
        db_path=str(db_path),
        question="How should we execute this plan?",
        topic="Platform",
    )
    assert question.id
    assert assessment.alignment in {
        "aligned",
        "clarification_needed",
        "potential_deviation",
        "likely_new_decision_required",
    }
    assert len(responses) == 4
    assert context["active_decisions"]
    assert combined
    assert likely_new_decision in {"yes", "no", "probably"}
    assert next_step

    storage = Storage(db_path=str(db_path))
    try:
        stored_question = storage.get_panel_question(question.id)
        stored_responses = storage.list_panel_responses(question.id)
        assert stored_question is not None
        assert len(stored_responses) == 4
    finally:
        storage.close()


def test_ask_decision_panel_with_no_decisions_still_returns_structure(tmp_path):
    db_path = tmp_path / "panel_no_data.db"
    create_session(str(db_path), "Panel No Data")

    question, context, assessment, responses, combined, likely_new_decision, next_step = ask_decision_panel(
        db_path=str(db_path),
        question="What should we do next for this area?",
        topic="UnknownTopic",
    )
    assert question.id
    assert len(context["active_decisions"]) == 0
    assert assessment.alignment == "clarification_needed"
    governance = next(response for response in responses if response.agent_name == "governance")
    assert "No active governing decisions" in governance.response_text
    assert combined
    assert likely_new_decision in {"yes", "no", "probably"}
    assert next_step


def test_governance_mentions_active_decisions_when_present(tmp_path):
    db_path = tmp_path / "panel_governance.db"
    session = create_session(str(db_path), "Panel Governance")
    decision = create_decision(str(db_path), session.id, "Govern", "Security", "Enforce MFA.")

    _, _, _, responses, _, _, _ = ask_decision_panel(
        db_path=str(db_path),
        question="Does current policy cover this?",
        topic="Security",
    )
    governance = next(response for response in responses if response.agent_name == "governance")
    assert decision.id in governance.response_text
    assert decision.title in governance.response_text


def test_assessment_execution_question_is_aligned_or_clarification_needed(tmp_path):
    db_path = tmp_path / "panel_execution_assessment.db"
    session = create_session(str(db_path), "Panel Execution Assessment")
    decision = create_decision(str(db_path), session.id, "Deploy Policy", "Release", "Use staged rollout.")
    assessment = assess_question_against_active_decisions(
        "Hur implementera staged rollout nästa steg?",
        [decision],
    )
    assert assessment.alignment in {"aligned", "clarification_needed"}


def test_assessment_deviation_question_detected(tmp_path):
    db_path = tmp_path / "panel_deviation_assessment.db"
    session = create_session(str(db_path), "Panel Deviation Assessment")
    decision = create_decision(str(db_path), session.id, "Country Rollout", "Expansion", "Wait for Norway readiness.")
    assessment = assess_question_against_active_decisions(
        "Kan vi byta riktning och gå vidare med Danmark?",
        [decision],
    )
    assert assessment.alignment == "potential_deviation"


def test_assessment_explicit_conflict_detected(tmp_path):
    db_path = tmp_path / "panel_conflict_assessment.db"
    session = create_session(str(db_path), "Panel Conflict Assessment")
    create_decision(
        str(db_path),
        session.id,
        "Nordic sequencing",
        "Expansion",
        "Open Denmark only after Norway is stable.",
    )
    _, _, assessment, responses, combined, likely_new_decision, _ = ask_decision_panel(
        db_path=str(db_path),
        question="Ska vi öppna Danmark ändå trots att Norge är försenat?",
        topic="Expansion",
    )
    assert assessment.alignment == "likely_new_decision_required"
    assert likely_new_decision == "yes"
    strateg = next(response for response in responses if response.agent_name == "strateg")
    governance = next(response for response in responses if response.agent_name == "governance")
    assert "challenge" in strateg.response_text.lower() or "deviation" in strateg.response_text.lower()
    assert "potential new decision" in governance.response_text.lower()
    assert "do not proceed as routine execution" in combined.lower()


def test_ask_decision_panel_output_includes_required_sections(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "panel_cli_output.db"
    session = create_session(str(db_path), "Panel CLI")
    create_decision(str(db_path), session.id, "Direction", "Ops", "Keep weekly release.")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "ask-decision-panel",
            "--question",
            "How do we run this operationally?",
            "--topic",
            "Ops",
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Question:" in output
    assert "Topic:" in output
    assert "Relevant active decisions:" in output
    assert "Historical decisions:" in output
    assert "Open decision candidates:" in output
    assert "Open decision suggestions:" in output
    assert "Decision alignment assessment:" in output
    assert "Challenge points:" in output
    assert "Strateg:" in output
    assert "Analyst:" in output
    assert "Operator:" in output
    assert "Governance:" in output
    assert "Combined recommendation:" in output
    assert "Likely requires new decision?:" in output
    assert "Suggested next step:" in output
