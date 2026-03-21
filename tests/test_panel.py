import sys
from datetime import datetime, timedelta, timezone

from multi_agent_app import models
from multi_agent_app.cli import (
    _build_reasoning_items_from_panel,
    ask_decision_panel,
    create_decision,
    create_session,
    main,
)
from multi_agent_app.panel import (
    assess_question_against_active_decisions,
    build_panel_outcome,
    build_context_packet,
    combined_recommendation,
    default_advisor_roles,
    per_role_analysis,
    suggested_next_step,
)
from multi_agent_app.storage import Storage


def test_store_and_get_panel_question():
    storage = Storage(db_path=":memory:")
    question = models.ExecutiveQuestion(question_text="Should we change DB?", topic="Persistence")
    storage.add_panel_question(question)

    fetched = storage.get_panel_question(question.id)
    assert fetched is not None
    assert fetched.question_text == "Should we change DB?"
    assert fetched.topic == "Persistence"
    assert fetched.status == "open"
    storage.close()


def test_store_and_list_panel_responses():
    storage = Storage(db_path=":memory:")
    question = models.ExecutiveQuestion(question_text="What next?", topic="Roadmap")
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


def test_default_advisor_roles_are_domain_objects():
    roles = default_advisor_roles()
    assert [role.name for role in roles] == ["strateg", "analyst", "operator", "governance"]
    assert all(role.active for role in roles)
    assert all(role.is_default for role in roles)
    assert all(role.purpose for role in roles)
    assert all(role.output_style for role in roles)


def test_per_role_analysis_uses_active_roles_only():
    roles = default_advisor_roles()
    for role in roles:
        if role.name == "governance":
            role.active = False

    assessment = models.DecisionAlignmentAssessment(
        alignment="clarification_needed",
        reason="Needs clarification.",
        challenge_points=["Check alignment."],
    )
    context = {
        "active_decisions": [],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }
    outputs = per_role_analysis(
        question="How should we execute this?",
        context=context,
        assessment=assessment,
        roles=roles,
    )
    assert set(outputs.keys()) == {"strateg", "analyst", "operator"}


def test_per_role_analysis_role_outputs_are_differentiated():
    assessment = models.DecisionAlignmentAssessment(
        alignment="potential_deviation",
        reason="May diverge from active direction.",
        challenge_points=["Validate exception intent before change."],
    )
    context = {
        "active_decisions": [models.Decision(session_id="S1", title="Core Direction", topic="Ops", decision_text="Do X")],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }
    outputs = per_role_analysis(
        question="Can we shift this path?",
        context=context,
        assessment=assessment,
    )
    assert len(set(outputs.values())) == 4
    assert "direction" in outputs["strateg"].lower()
    assert "risk" in outputs["analyst"].lower() or "uncertainty" in outputs["analyst"].lower()
    assert "sequence" in outputs["operator"].lower()
    assert "governance status" in outputs["governance"].lower()


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
        stored_analysis = storage.get_panel_question_analysis(question.id)
        context_decision_ids = storage.list_panel_question_context_decision_ids(question.id)
        stored_case = storage.get_panel_question_case(question.id)
        assert stored_question is not None
        assert len(stored_responses) == 4
        assert stored_analysis is not None
        assert stored_analysis.combined_recommendation == combined
        assert stored_analysis.suggested_next_step == next_step
        assert stored_analysis.likely_requires_new_decision == likely_new_decision
        assert stored_analysis.question_interpretation
        assert stored_analysis.relevant_context
        assert stored_analysis.per_role_analysis
        assert "strateg" in stored_analysis.per_role_analysis
        assert "analyst" in stored_analysis.per_role_analysis
        assert "operator" in stored_analysis.per_role_analysis
        assert "governance" in stored_analysis.per_role_analysis
        assert isinstance(stored_analysis.tensions, list)
        assert stored_analysis.decision_status_assessment
        assert stored_analysis.decision_status_assessment["alignment"] == assessment.alignment
        assert stored_analysis.decision_status_assessment["decision_mode"] in {
            "execution_under_active_decision",
            "clarification_of_active_decision",
            "potential_deviation",
            "likely_new_decision_required",
        }
        assert stored_analysis.decision_status_assessment["formal_next_step"]
        assert stored_analysis.decision_status_assessment["automatic_formalization"] is False
        assert context_decision_ids
        assert all(decision_id in {decision.id for decision in context["active_decisions"]} for decision_id in context_decision_ids)
        assert stored_case is not None
        assert stored_case["question"].id == question.id
        assert stored_case["analysis"] is not None
        assert len(stored_case["responses"]) == 4
        assert stored_case["sections"]["question_interpretation"]
        assert stored_case["sections"]["relevant_context"]
        assert stored_case["sections"]["per_role_analysis"]
        assert "tensions" in stored_case["sections"]
        assert stored_case["sections"]["combined_recommendation"] == combined
        assert stored_case["sections"]["decision_status_assessment"]["alignment"] == assessment.alignment
        assert stored_case["sections"]["decision_status_assessment"]["formal_next_step"]

        reasoning_items = storage.list_reasoning_items_for_question(question.id)
        assert 1 <= len(reasoning_items) <= 4
        assert all(item.question_id == question.id for item in reasoning_items)
        assert all(item.source_type == "panel" for item in reasoning_items)
        assert all(
            item.memory_level in {"transient", "private_context", "formal_decision"}
            for item in reasoning_items
        )
        assert all(
            item.kind in {"open_question", "objection", "risk", "rationale", "assumption"}
            for item in reasoning_items
        )
    finally:
        storage.close()


def test_panel_outcome_distinguishes_decision_modes():
    empty_context = {
        "active_decisions": [],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }
    clarification_no_active = models.DecisionAlignmentAssessment(
        alignment="clarification_needed",
        reason="No active decision baseline.",
    )
    outcome_no_active = build_panel_outcome(empty_context, clarification_no_active)
    assert outcome_no_active.decision_mode == "likely_new_decision_required"
    assert outcome_no_active.likely_requires_new_decision == "yes"
    assert outcome_no_active.can_execute_now is False

    active_context = {
        "active_decisions": [models.Decision(session_id="S1", title="D1", topic="Ops", decision_text="Do X")],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }
    aligned = models.DecisionAlignmentAssessment(
        alignment="aligned",
        reason="Aligned with active direction.",
    )
    outcome_aligned = build_panel_outcome(active_context, aligned)
    assert outcome_aligned.decision_mode == "execution_under_active_decision"
    assert outcome_aligned.likely_requires_new_decision == "no"
    assert outcome_aligned.can_execute_now is True


def test_ask_decision_panel_deviation_creates_objection_or_risk_reasoning(tmp_path):
    db_path = tmp_path / "panel_reasoning_items_deviation.db"
    session = create_session(str(db_path), "Panel Reasoning")
    create_decision(
        str(db_path),
        session.id,
        "Rollout sequence",
        "Expansion",
        "Open Denmark only after Norway is stable.",
    )
    question, _, _, _, _, _, _ = ask_decision_panel(
        db_path=str(db_path),
        question="Ska vi öppna Danmark ändå trots att Norge är försenat?",
        topic="Expansion",
    )
    storage = Storage(db_path=str(db_path))
    try:
        items = storage.list_reasoning_items_for_question(question.id)
        assert 1 <= len(items) <= 4
        kinds = {item.kind for item in items}
        assert "objection" in kinds or "risk" in kinds
        assert all(item.question_id == question.id for item in items)
    finally:
        storage.close()


def test_reasoning_builder_has_fallback_for_likely_new_decision_case():
    question = models.ExecutiveQuestion(question_text="Should we override current direction?", topic="Expansion")
    context = {
        "active_decisions": [
            models.Decision(
                session_id="S1",
                title="Rollout policy",
                topic="Expansion",
                decision_text="Follow approved sequence.",
            )
        ]
    }
    assessment = models.DecisionAlignmentAssessment(
        alignment="likely_new_decision_required",
        reason="Question likely proposes exception against active direction.",
        challenge_points=[],
    )

    items = _build_reasoning_items_from_panel(
        panel_question=question,
        context=context,
        assessment=assessment,
        role_analysis_outputs={},
    )

    assert len(items) >= 1
    assert items[0].kind == "objection"
    assert items[0].question_id == question.id
    assert "exception" in items[0].content.lower() or "direction" in items[0].content.lower()


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
    assert "create/open new decision handling before execution" in combined.lower()
    assert "likely conflict with active governing direction" in combined.lower()


def test_combined_recommendation_is_action_plus_reason():
    context = {
        "active_decisions": [models.Decision(session_id="S1", title="D1", topic="Ops", decision_text="Do X")],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }
    assessment = models.DecisionAlignmentAssessment(
        alignment="clarification_needed",
        reason="Needs execution clarification.",
    )
    rec = combined_recommendation(
        question="How should we execute this?",
        context=context,
        assessment=assessment,
        role_analysis={"analyst": "Risk depends on sequencing assumptions."},
    )
    assert rec.startswith("Clarify before execution.")
    assert "Why:" in rec
    assert "missing clarification for execution details" in rec
    assert "risk/uncertainty requires explicit handling" in rec


def test_suggested_next_step_is_operational_per_mode():
    active_decision = models.Decision(session_id="S1", title="D1", topic="Ops", decision_text="Do X")
    base_context = {
        "active_decisions": [active_decision],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }

    clarification = models.DecisionAlignmentAssessment(
        alignment="clarification_needed",
        reason="Need scope clarification.",
    )
    clarification_step = suggested_next_step("How execute?", base_context, clarification)
    assert "Document a clarification note against active decision" in clarification_step
    assert "owner" in clarification_step.lower()

    deviation = models.DecisionAlignmentAssessment(
        alignment="potential_deviation",
        reason="Potential deviation.",
    )
    deviation_step = suggested_next_step("Can we deviate?", base_context, deviation)
    assert "Pause scope changes" in deviation_step
    assert "Open/update a decision candidate" in deviation_step

    no_active_context = {
        "active_decisions": [],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }
    new_decision_needed = models.DecisionAlignmentAssessment(
        alignment="clarification_needed",
        reason="No active baseline.",
    )
    new_decision_step = suggested_next_step("What now?", no_active_context, new_decision_needed)
    assert "Pause implementation changes" in new_decision_step
    assert "Create a new decision candidate" in new_decision_step


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
    assert "Active decisions in scope:" in output
    assert "Previous related decisions:" in output
    assert "Pending decision candidates:" in output
    assert "Pending decision suggestions:" in output
    assert "Assessment:" in output
    assert "Decision summary:" in output
    assert "Decision context at a glance:" in output
    assert "Key concerns:" in output
    assert "Strateg:" in output
    assert "Analyst:" in output
    assert "Operator:" in output
    assert "Governance:" in output
    assert "Combined recommendation:" in output
    assert "New decision likely?:" in output
    assert "Recommended next step:" in output


def test_show_panel_question_command_loads_saved_case(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "panel_show_case_cli.db"
    session = create_session(str(db_path), "Panel Show Case")
    create_decision(str(db_path), session.id, "Direction", "Ops", "Keep weekly release.")

    question, _, _, _, _, _, _ = ask_decision_panel(
        db_path=str(db_path),
        question="Hur ska vi utföra detta?",
        topic="Ops",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "show-panel-question",
            "--question-id",
            question.id,
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Question:" in output
    assert "Active decision references:" in output
    assert "Assessment:" in output
    assert "Decision summary:" in output
    assert "Decision context at a glance:" in output
    assert "Combined recommendation:" in output
    assert "Strateg:" in output
    assert "Key reasoning notes:" in output
    assert "Reasoning summary:" in output


def test_panel_cli_outputs_manual_candidate_draft_for_new_decision_case(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "panel_cli_candidate_draft.db"
    session = create_session(str(db_path), "Panel Candidate Draft")
    create_decision(
        str(db_path),
        session.id,
        "Nordic sequencing",
        "Expansion",
        "Open Denmark only after Norway is stable.",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "ask-decision-panel",
            "--question",
            "Ska vi öppna Danmark ändå trots att Norge är försenat?",
            "--topic",
            "Expansion",
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Handling mode: New decision handling required" in output
    assert "Decision candidate draft (manual):" in output
    assert "title: Expansion: decision update from panel question" in output
    assert "Manual action:" in output


def test_show_panel_question_outputs_manual_candidate_draft_for_deviation_case(
    tmp_path, capsys, monkeypatch
):
    db_path = tmp_path / "panel_show_candidate_draft.db"
    session = create_session(str(db_path), "Panel Show Candidate Draft")
    create_decision(str(db_path), session.id, "Direction", "Ops", "Keep weekly release cadence.")

    question, _, _, _, _, _, _ = ask_decision_panel(
        db_path=str(db_path),
        question="Kan vi byta riktning och pausa release till nästa kvartal?",
        topic="Ops",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "show-panel-question",
            "--question-id",
            question.id,
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Handling mode: Exception/deviation handling needed" in output
    assert "Decision candidate draft (manual):" in output
    assert "title: Ops: decision update from panel question" in output


def test_storage_list_panel_questions_returns_latest_first(tmp_path):
    db_path = tmp_path / "panel_list_storage.db"

    storage = Storage(db_path=str(db_path))
    try:
        session = models.Session(name="Panel List Storage")
        storage.add_session(session)
        earlier = datetime.now(timezone.utc) - timedelta(minutes=1)
        later = datetime.now(timezone.utc)
        first = models.ExecutiveQuestion(
            question_text="First panel question for storage listing.",
            topic="Ops",
            session_id=session.id,
            created_at=earlier,
        )
        second = models.ExecutiveQuestion(
            question_text="Second panel question for storage listing.",
            topic="Ops",
            session_id=session.id,
            created_at=later,
        )
        storage.add_panel_question(first)
        storage.add_panel_question(second)

        questions = storage.list_panel_questions(topic="Ops", limit=10)
        assert len(questions) == 2
        assert questions[0].id == second.id
        assert questions[1].id == first.id
        assert questions[0].status == "open"
    finally:
        storage.close()


def test_list_panel_questions_command_prints_structured_rows(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "panel_list_cli.db"
    create_session(str(db_path), "Panel List CLI")
    long_question = (
        "How should we execute this cross-team rollout in detail while keeping dependencies stable "
        "and avoiding hidden delivery risks in the next sprint?"
    )
    question, _, _, _, _, _, _ = ask_decision_panel(
        db_path=str(db_path),
        question=long_question,
        topic="Delivery",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--db-path",
            str(db_path),
            "list-panel-questions",
            "--topic",
            "Delivery",
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "Panel questions: 1" in output
    assert question.id in output
    assert "[open]" in output
    assert "topic=Delivery" in output
    assert "How should we execute this cross-team rollout in detail" in output
    assert "..." in output
