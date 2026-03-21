from __future__ import annotations

import json
import os
from typing import Mapping, Protocol
from urllib import error, request

from . import models


class LLMProvider(Protocol):
    name: str

    def is_available(self) -> bool:
        ...

    def generate_role_response(
        self,
        *,
        role: models.AdvisorRole,
        question: str,
        context: Mapping[str, object],
        assessment: models.DecisionAlignmentAssessment,
        fallback_response: str,
    ) -> str | None:
        ...


class NullLLMProvider:
    """Fallback provider that intentionally never generates content."""

    name = "heuristic"

    def is_available(self) -> bool:
        return False

    def generate_role_response(
        self,
        *,
        role: models.AdvisorRole,
        question: str,
        context: Mapping[str, object],
        assessment: models.DecisionAlignmentAssessment,
        fallback_response: str,
    ) -> str | None:
        return None


class OpenAIChatProvider:
    """Minimal OpenAI-backed provider.

    This is intentionally small and safe:
    - disabled unless explicitly selected via env
    - graceful fallback when key/network/response parsing is missing
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip() or "gpt-4o-mini"
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_role_response(
        self,
        *,
        role: models.AdvisorRole,
        question: str,
        context: Mapping[str, object],
        assessment: models.DecisionAlignmentAssessment,
        fallback_response: str,
    ) -> str | None:
        if not self.is_available():
            return None

        payload = {
            "model": self.model,
            "input": self._build_prompt(
                role=role,
                question=question,
                context=context,
                assessment=assessment,
                fallback_response=fallback_response,
            ),
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            "https://api.openai.com/v1/responses",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
        except (error.URLError, TimeoutError, OSError):
            return None

        text = _extract_openai_text(body)
        if not text:
            return None
        return text

    def _build_prompt(
        self,
        *,
        role: models.AdvisorRole,
        question: str,
        context: Mapping[str, object],
        assessment: models.DecisionAlignmentAssessment,
        fallback_response: str,
    ) -> str:
        active_count = len(context.get("active_decisions", []) if isinstance(context, dict) else [])
        candidate_count = len(context.get("open_candidates", []) if isinstance(context, dict) else [])
        suggestion_count = len(context.get("open_suggestions", []) if isinstance(context, dict) else [])
        challenge_points = assessment.challenge_points[:3]
        challenge_text = "; ".join(challenge_points) if challenge_points else "none"
        return (
            "You are generating one role-specific advisory line for a leadership decision panel.\n"
            f"Role: {role.name}\n"
            f"Role purpose: {role.purpose}\n"
            f"Output style: {role.output_style}\n"
            f"Question: {question}\n"
            f"Assessment alignment: {assessment.alignment}\n"
            f"Assessment reason: {assessment.reason}\n"
            f"Challenge points: {challenge_text}\n"
            f"Context counts: active_decisions={active_count}, open_candidates={candidate_count}, open_suggestions={suggestion_count}\n"
            "Constraints:\n"
            "- Keep it concise (max 3 sentences).\n"
            "- Focus on this role only; avoid repeating generic summary text.\n"
            "- If uncertain, stay conservative and suggest a clear next control/action.\n"
            f"Heuristic fallback reference: {fallback_response}\n"
        )


def _extract_openai_text(raw_body: str) -> str | None:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    output = payload.get("output")
    if not isinstance(output, list):
        return None
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def provider_from_env() -> LLMProvider:
    selected = os.getenv("MULTI_AGENT_APP_LLM_PROVIDER", "").strip().lower()
    if selected != "openai":
        return NullLLMProvider()
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return OpenAIChatProvider(api_key=api_key, model=model)


def provider_enabled_from_env() -> bool:
    return os.getenv("MULTI_AGENT_APP_LLM_PROVIDER", "").strip().lower() == "openai"


def apply_role_llm_overrides(
    *,
    provider: LLMProvider,
    roles: list[models.AdvisorRole],
    question: str,
    context: Mapping[str, object],
    assessment: models.DecisionAlignmentAssessment,
    heuristic_outputs: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    output = dict(heuristic_outputs)
    role_sources = {
        role.name: "heuristic"
        for role in roles
        if role.name in output
    }
    if not provider.is_available():
        return output, role_sources
    for role in roles:
        fallback = output.get(role.name, "")
        generated = provider.generate_role_response(
            role=role,
            question=question,
            context=context,
            assessment=assessment,
            fallback_response=fallback,
        )
        if generated:
            output[role.name] = generated
            role_sources[role.name] = "llm"
    return output, role_sources
