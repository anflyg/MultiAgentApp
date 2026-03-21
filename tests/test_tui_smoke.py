import pytest

from multi_agent_app import models


def test_tui_smoke_import_and_init():
    pytest.importorskip("textual")
    from multi_agent_app.tui import MultiAgentTUI

    app = MultiAgentTUI(db_path=":memory:")
    assert app.db_path == ":memory:"
    assert hasattr(app, "_refresh_dashboard")
    assert hasattr(app, "_render_question_analysis")


def test_tui_build_question_detail_texts_uses_sections_when_available():
    pytest.importorskip("textual")
    from multi_agent_app.tui import MultiAgentTUI

    app = MultiAgentTUI(db_path=":memory:")
    case = {
        "question": models.ExecutiveQuestion(
            question_text="How should we execute this rollout?",
            topic="Release",
            status="open",
        ),
        "analysis": models.ExecutiveQuestionAnalysis(
            question_id="Q1",
            assessment_alignment="clarification_needed",
            assessment_reason="Needs execution details.",
            challenge_points=["Clarify sequencing."],
            combined_recommendation="Proceed with staged rollout.",
            suggested_next_step="Assign owner.",
            likely_requires_new_decision="probably",
        ),
        "sections": {
            "question_interpretation": "Execution clarification under current direction.",
            "relevant_context": {
                "active_decision_ids": ["D1"],
                "historical_decision_ids": ["D0"],
            },
            "per_role_analysis": {
                "strateg": "Stay aligned.",
                "analyst": "Watch risk.",
                "operator": "Assign tasks.",
                "governance": "Within current policy.",
            },
            "tensions": ["Clarify sequencing."],
            "combined_recommendation": "Proceed with staged rollout.",
            "decision_status_assessment": {
                "decision_mode": "clarification_of_active_decision",
                "alignment": "clarification_needed",
                "reason": "Needs execution details.",
                "likely_requires_new_decision": "probably",
                "formal_next_step": "Document clarification before execution.",
                "suggested_next_step": "Document owner and sequence.",
            },
        },
        "reasoning_items": [
            models.ReasoningItem(
                question_id="Q1",
                kind="risk",
                content="Timeline may slip due to dependency sequencing.",
                source_type="panel",
            ),
        ],
    }
    analysis_text, recommendation_text, status_text = app._build_question_detail_texts(case)
    assert "Interpretation: Execution clarification under current direction." in analysis_text
    assert "Advisor perspectives:" in analysis_text
    assert "strateg: Stay aligned." in analysis_text
    assert "Context and memory signals:" in analysis_text
    assert "Key reasoning notes:" in analysis_text
    assert (
        "Risk signal: Timeline may slip due to dependency sequencing. "
        "(panel analysis; private context)" in analysis_text
    )
    assert recommendation_text == "Proceed with staged rollout."
    assert "assessment: Needs clarification before execution" in status_text
    assert "handling mode: Clarify current decision before execution" in status_text
    assert "formal_next_step: Document clarification before execution." in status_text
    assert "suggested_next_step: Document owner and sequence." in status_text
    assert "new decision likelihood: Probably" in status_text


def test_tui_build_question_detail_texts_handles_missing_case():
    pytest.importorskip("textual")
    from multi_agent_app.tui import MultiAgentTUI

    app = MultiAgentTUI(db_path=":memory:")
    analysis_text, recommendation_text, status_text = app._build_question_detail_texts(None)
    assert "not found" in analysis_text.lower()
    assert "No recommendation available yet." == recommendation_text
    assert "No decision guidance available yet." == status_text


def test_tui_resolve_select_value_handles_string_and_blank():
    pytest.importorskip("textual")
    from textual.widgets import Select

    from multi_agent_app.tui import MultiAgentTUI

    app = MultiAgentTUI(db_path=":memory:")
    assert app._resolve_select_value("Q1") == "Q1"
    assert app._resolve_select_value("") is None
    assert app._resolve_select_value(Select.BLANK) is None


def test_tui_pick_question_id_after_refresh_prefers_previous_selection():
    pytest.importorskip("textual")
    from multi_agent_app.tui import MultiAgentTUI

    app = MultiAgentTUI(db_path=":memory:")
    app._selected_question_id = "Q2"
    assert app._pick_question_id_after_refresh(["Q1", "Q2", "Q3"]) == "Q2"
    assert app._pick_question_id_after_refresh(["Q1", "Q3"]) == "Q1"
    assert app._pick_question_id_after_refresh([]) is None
