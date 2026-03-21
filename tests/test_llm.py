from __future__ import annotations

from multi_agent_app import models
from multi_agent_app.cli import ask_decision_panel, create_decision, create_session
from multi_agent_app.llm import (
    NullLLMProvider,
    _extract_chat_completions_text,
    _extract_gemini_text,
    _extract_openai_error,
    _extract_openai_text,
    apply_role_llm_overrides,
    provider_from_env,
)
from multi_agent_app.panel import default_advisor_roles
from multi_agent_app.storage import Storage


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return True

    def generate_role_response(
        self,
        *,
        role: models.AdvisorRole,
        question: str,
        context: dict[str, object],
        assessment: models.DecisionAlignmentAssessment,
        fallback_response: str,
    ) -> str | None:
        self.calls.append(role.name)
        return f"{role.name.upper()} (LLM): {fallback_response}"


def test_provider_from_env_defaults_to_heuristic(monkeypatch):
    monkeypatch.delenv("MULTI_AGENT_APP_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = provider_from_env()
    assert provider.name == "heuristic"
    assert provider.is_available() is False


def test_provider_from_env_openai_without_key_is_unavailable(monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_APP_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = provider_from_env()
    assert provider.name == "openai"
    assert provider.is_available() is False


def test_provider_from_env_gemini_without_key_is_unavailable(monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_APP_LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    provider = provider_from_env()
    assert provider.name == "gemini"
    assert provider.is_available() is False


def test_apply_role_llm_overrides_keeps_heuristics_when_provider_disabled():
    roles = default_advisor_roles()
    assessment = models.DecisionAlignmentAssessment(
        alignment="clarification_needed",
        reason="Needs clarification.",
    )
    heuristic_outputs = {role.name: f"{role.name}-heuristic" for role in roles}
    context = {
        "active_decisions": [],
        "historical_decisions": [],
        "open_candidates": [],
        "open_suggestions": [],
        "decision_links": [],
    }
    output, role_sources, fallback_reasons = apply_role_llm_overrides(
        provider=NullLLMProvider(),
        roles=roles,
        question="How should we proceed?",
        context=context,
        assessment=assessment,
        heuristic_outputs=heuristic_outputs,
    )
    assert output == heuristic_outputs
    assert all(source == "heuristic" for source in role_sources.values())
    assert all(reason == "provider_unavailable" for reason in fallback_reasons.values())


def test_ask_decision_panel_accepts_provider_and_overrides_role_text(tmp_path):
    db_path = tmp_path / "panel_llm_provider.db"
    session = create_session(str(db_path), "Panel LLM Provider")
    create_decision(str(db_path), session.id, "Direction", "Ops", "Keep weekly release cadence.")

    provider = _FakeProvider()
    question, _, _, responses, _, _, _ = ask_decision_panel(
        db_path=str(db_path),
        question="How should we run this change?",
        topic="Ops",
        llm_provider=provider,
    )
    assert len(responses) == 4
    assert set(provider.calls) == {"strateg", "analyst", "operator", "governance"}
    assert all("(LLM):" in response.response_text for response in responses)
    storage = Storage(db_path=str(db_path))
    try:
        analysis = storage.get_panel_question_analysis(question.id)
        assert analysis is not None
        llm_status = analysis.decision_status_assessment.get("llm_status", {})
        assert llm_status.get("provider") == "fake"
        assert llm_status.get("provider_enabled") is True
        assert llm_status.get("provider_available") is True
        assert set(llm_status.get("llm_roles", [])) == {"strateg", "analyst", "operator", "governance"}
        assert llm_status.get("fallback_reasons", {}) == {}
    finally:
        storage.close()


def test_extract_openai_text_supports_output_text_list():
    raw = '{"output_text":["First line","Second line"]}'
    assert _extract_openai_text(raw) == "First line\nSecond line"


def test_extract_chat_completions_text_supports_string_content():
    raw = '{"choices":[{"message":{"content":"Role specific answer"}}]}'
    assert _extract_chat_completions_text(raw) == "Role specific answer"


def test_extract_openai_error_returns_message():
    raw = '{"error":{"message":"Invalid API key","type":"invalid_request_error"}}'
    assert _extract_openai_error(raw) == "Invalid API key"


def test_extract_gemini_text_returns_candidate_text():
    raw = '{"candidates":[{"content":{"parts":[{"text":"Gemini role answer"}]}}]}'
    assert _extract_gemini_text(raw) == "Gemini role answer"
