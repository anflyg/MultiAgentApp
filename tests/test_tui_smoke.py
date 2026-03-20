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
                "alignment": "clarification_needed",
                "reason": "Needs execution details.",
                "likely_requires_new_decision": "probably",
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
    assert "Per-role analysis:" in analysis_text
    assert "strateg: Stay aligned." in analysis_text
    assert "Reasoning items:" in analysis_text
    assert "[risk] (panel/private_context) Timeline may slip due to dependency sequencing." in analysis_text
    assert recommendation_text == "Proceed with staged rollout."
    assert "alignment: clarification_needed" in status_text
    assert "likely_requires_new_decision: probably" in status_text


def test_tui_build_question_detail_texts_handles_missing_case():
    pytest.importorskip("textual")
    from multi_agent_app.tui import MultiAgentTUI

    app = MultiAgentTUI(db_path=":memory:")
    analysis_text, recommendation_text, status_text = app._build_question_detail_texts(None)
    assert "not found" in analysis_text.lower()
    assert "No combined recommendation available." == recommendation_text
    assert "No decision status assessment available." == status_text


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
