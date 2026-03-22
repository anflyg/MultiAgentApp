from __future__ import annotations

from multi_agent_app import models
from multi_agent_app.cli import ask_decision_panel, create_decision, create_session
from multi_agent_app.config import AppConfig
from multi_agent_app.llm import (
    NullLLMProvider,
    _extract_chat_completions_text,
    _extract_gemini_text,
    _extract_openai_error,
    _extract_openai_text,
    apply_role_llm_overrides,
    provider_key_status_label,
    provider_from_env,
    resolve_role_provider_and_model,
    role_generation_mode_label,
    summarize_fallback_notes,
    summarize_role_provider_map,
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
    output, role_sources, fallback_reasons, role_provider_config, role_provider_available = apply_role_llm_overrides(
        provider=NullLLMProvider(),
        roles=roles,
        question="How should we proceed?",
        context=context,
        assessment=assessment,
        heuristic_outputs=heuristic_outputs,
    )
    assert output == heuristic_outputs
    assert all(source == "heuristic" for source in role_sources.values())
    assert all(reason == "heuristic_configured" for reason in fallback_reasons.values())
    assert all(config["provider"] == "heuristic" for config in role_provider_config.values())
    assert all(available is False for available in role_provider_available.values())


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
    assert len(responses) >= 2
    assert set(provider.calls) == {"operator", "governance"}
    assert all("(LLM):" in response.response_text for response in responses)
    storage = Storage(db_path=str(db_path))
    try:
        analysis = storage.get_panel_question_analysis(question.id)
        assert analysis is not None
        llm_status = analysis.decision_status_assessment.get("llm_status", {})
        assert llm_status.get("provider") == "fake"
        assert llm_status.get("provider_enabled") is True
        assert llm_status.get("provider_available") is True
        assert set(llm_status.get("llm_roles", [])) == {"operator", "governance"}
        assert set(llm_status.get("active_roles", [])) == {"operator", "governance"}
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


def test_resolve_role_provider_and_model_uses_new_gemini_default(monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_APP_LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL_STRATEG", raising=False)

    provider_name, model = resolve_role_provider_and_model("strateg")
    assert provider_name == "gemini"
    assert model == "gemini-2.0-flash"


def test_resolve_role_provider_and_model_prefers_role_override(monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_APP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROVIDER_ANALYST", "gemini")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-1.5-flash")
    monkeypatch.setenv("GEMINI_MODEL_ANALYST", "gemini-1.5-pro")

    provider_name, model = resolve_role_provider_and_model("analyst")
    assert provider_name == "gemini"
    assert model == "gemini-1.5-pro"

    provider_name_other, model_other = resolve_role_provider_and_model("strateg")
    assert provider_name_other == "openai"
    assert model_other == "gpt-4o-mini"


def test_apply_role_llm_overrides_role_specific_heuristic_override(monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_APP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROVIDER_STRATEG", "heuristic")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

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
    _, _, fallback_reasons, role_provider_config, _ = apply_role_llm_overrides(
        provider=None,
        roles=roles,
        question="How should we proceed?",
        context=context,
        assessment=assessment,
        heuristic_outputs=heuristic_outputs,
    )
    assert role_provider_config["strateg"]["provider"] == "heuristic"
    assert fallback_reasons["strateg"] == "heuristic_configured"
    assert fallback_reasons["analyst"] == "provider_unavailable"


def test_summarize_helpers_keep_status_compact():
    fallback = {
        "strateg": "network_error: URLError",
        "analyst": "Invalid API key provided for this request",
        "operator": "http_429",
        "governance": "provider_unavailable",
    }
    notes = summarize_fallback_notes(fallback)
    assert "strateg=network" in notes
    assert "analyst=auth" in notes
    assert "operator=rate_limited" in notes
    assert "governance=no_api_key" in notes

    provider_map = summarize_role_provider_map(
        {
            "strateg": {"provider": "openai", "model": "gpt-4o-mini"},
            "analyst": {"provider": "gemini", "model": "gemini-2.0-flash"},
            "operator": {"provider": "heuristic", "model": None},
            "governance": {"provider": "openai", "model": "gpt-4.1-mini-super-long-model-name"},
        }
    )
    assert "strateg=openai/gpt-4o-mini" in provider_map
    assert "operator=heuristic" in provider_map
    assert "governance=openai/gpt-4.1-mini-super-long..." in provider_map

    mode = role_generation_mode_label(
        provider="mixed",
        model="mixed",
        enabled=True,
        available=True,
    )
    assert "provider=mixed-per-role (model per role)" in mode


def test_provider_key_status_label_is_clear_for_missing_key():
    text = provider_key_status_label(
        provider="openai",
        enabled=True,
        available=False,
        role_provider_config={"operator": {"provider": "openai", "model": "gpt-4o-mini"}},
    )
    assert "key missing" in text
    assert "OPENAI_API_KEY" in text
    assert "heuristic fallback" in text


def test_provider_from_env_uses_config_gemini_when_env_missing(monkeypatch):
    monkeypatch.delenv("MULTI_AGENT_APP_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = AppConfig(
        llm_provider="gemini",
        gemini_model="gemini-2.0-flash",
        gemini_api_key="gemini-config-key",
    )
    provider = provider_from_env(config)
    assert provider.name == "gemini"
    assert provider.is_available() is True
    assert getattr(provider, "model", None) == "gemini-2.0-flash"


def test_resolve_role_provider_and_model_uses_config_role_override(monkeypatch):
    monkeypatch.delenv("MULTI_AGENT_APP_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_ANALYST", raising=False)
    monkeypatch.delenv("GEMINI_MODEL_ANALYST", raising=False)
    config = AppConfig(
        llm_provider="gemini",
        gemini_model="gemini-2.0-flash",
        role_llm_overrides={
            "analyst": {"provider": "openai", "model": "gpt-4o-mini"},
        },
    )

    provider_name, model = resolve_role_provider_and_model("analyst", app_config=config)
    assert provider_name == "openai"
    assert model == "gpt-4o-mini"


def test_ask_decision_panel_uses_config_role_provider_mapping(tmp_path, monkeypatch):
    monkeypatch.delenv("MULTI_AGENT_APP_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    db_path = tmp_path / "panel_config_providers.db"
    session = create_session(str(db_path), "Panel Config Provider")
    create_decision(str(db_path), session.id, "Direction", "Ops", "Keep weekly release cadence.")
    config = AppConfig(
        llm_provider="gemini",
        gemini_model="gemini-2.0-flash",
        role_llm_overrides={
            "operator": {"provider": "heuristic", "model": None},
        },
    )

    question, _, _, _, _, _, _ = ask_decision_panel(
        db_path=str(db_path),
        question="How should we run this change?",
        topic="Ops",
        app_config=config,
    )
    storage = Storage(db_path=str(db_path))
    try:
        analysis = storage.get_panel_question_analysis(question.id)
        assert analysis is not None
        llm_status = analysis.decision_status_assessment.get("llm_status", {})
        role_provider_config = llm_status.get("role_provider_config", {})
        assert role_provider_config.get("strateg", {}).get("provider") == "gemini"
        assert role_provider_config.get("operator", {}).get("provider") == "heuristic"
    finally:
        storage.close()
