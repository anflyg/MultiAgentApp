from __future__ import annotations

import json
import os
from typing import Mapping, Protocol
from urllib import error, request

from . import models

try:
    import requests
except ImportError:  # pragma: no cover - handled by urllib fallback.
    requests = None

_SUPPORTED_PROVIDERS = {"openai", "gemini", "heuristic"}
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"


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
    model: str | None = None

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
        self.model = model.strip() or _OPENAI_DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        self.last_error: str | None = None

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
        self.last_error = None
        if not self.is_available():
            self.last_error = "provider_unavailable"
            return None

        prompt = self._build_prompt(
            role=role,
            question=question,
            context=context,
            assessment=assessment,
            fallback_response=fallback_response,
        )

        response_payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        }
        body = self._post_json("https://api.openai.com/v1/responses", response_payload)
        text = _extract_openai_text(body) if body else None
        if text:
            return text

        # Conservative fallback endpoint if responses parsing/shape fails.
        chat_payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        body = self._post_json("https://api.openai.com/v1/chat/completions", chat_payload)
        text = _extract_chat_completions_text(body) if body else None
        if text:
            return text

        if self.last_error is None:
            self.last_error = "empty_or_unparseable_response"
        return None

    def _post_json(self, url: str, payload: dict[str, object]) -> str | None:
        if requests is not None:
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "MultiAgentApp/alpha",
                    },
                    timeout=self.timeout_seconds,
                )
                if resp.status_code >= 400:
                    msg = _extract_openai_error(resp.text) or f"http_{resp.status_code}"
                    self.last_error = msg
                    return None
                return resp.text
            except requests.RequestException as exc:
                # Fall through to urllib as secondary path.
                self.last_error = f"network_error: {exc.__class__.__name__}"

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "MultiAgentApp/alpha",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.read().decode("utf-8")
        except error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")
            except Exception:
                body = ""
            msg = _extract_openai_error(body) or f"http_{exc.code}"
            self.last_error = msg
            return None
        except (error.URLError, TimeoutError, OSError) as exc:
            self.last_error = f"network_error: {exc.__class__.__name__}"
            return None

    def _build_prompt(
        self,
        *,
        role: models.AdvisorRole,
        question: str,
        context: Mapping[str, object],
        assessment: models.DecisionAlignmentAssessment,
        fallback_response: str,
    ) -> str:
        return _build_role_prompt(
            role=role,
            question=question,
            context=context,
            assessment=assessment,
            fallback_response=fallback_response,
        )


class GeminiProvider:
    """Minimal Gemini-backed provider using generateContent."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = _GEMINI_DEFAULT_MODEL,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip() or _GEMINI_DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        self.last_error: str | None = None

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
        self.last_error = None
        if not self.is_available():
            self.last_error = "provider_unavailable"
            return None

        prompt = _build_role_prompt(
            role=role,
            question=question,
            context=context,
            assessment=assessment,
            fallback_response=fallback_response,
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ]
        }
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = self._post_json(url, payload)
        text = _extract_gemini_text(body) if body else None
        if text:
            return text
        if self.last_error is None:
            self.last_error = "empty_or_unparseable_response"
        return None

    def _post_json(self, url: str, payload: dict[str, object]) -> str | None:
        if requests is not None:
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "MultiAgentApp/alpha",
                    },
                    timeout=self.timeout_seconds,
                )
                if resp.status_code >= 400:
                    msg = _extract_openai_error(resp.text) or f"http_{resp.status_code}"
                    self.last_error = msg
                    return None
                return resp.text
            except requests.RequestException as exc:
                self.last_error = f"network_error: {exc.__class__.__name__}"

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "MultiAgentApp/alpha",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.read().decode("utf-8")
        except error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")
            except Exception:
                body = ""
            msg = _extract_openai_error(body) or f"http_{exc.code}"
            self.last_error = msg
            return None
        except (error.URLError, TimeoutError, OSError) as exc:
            self.last_error = f"network_error: {exc.__class__.__name__}"
            return None


def _build_role_prompt(
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
    if isinstance(output_text, list):
        lines = [item.strip() for item in output_text if isinstance(item, str) and item.strip()]
        if lines:
            return "\n".join(lines)
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


def _extract_chat_completions_text(raw_body: str) -> str | None:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        segments: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                segments.append(text.strip())
        if segments:
            return "\n".join(segments)
    return None


def _extract_openai_error(raw_body: str) -> str | None:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    err = payload.get("error")
    if not isinstance(err, dict):
        return None
    message = err.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    code = err.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return None


def _extract_gemini_text(raw_body: str) -> str | None:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    first = candidates[0]
    if not isinstance(first, dict):
        return None
    content = first.get("content")
    if not isinstance(content, dict):
        return None
    parts = content.get("parts")
    if not isinstance(parts, list):
        return None
    segments: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            segments.append(text.strip())
    if not segments:
        return None
    return "\n".join(segments)


def _normalize_provider(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in _SUPPORTED_PROVIDERS:
        return normalized
    return "heuristic"


def _role_env_suffix(role_name: str) -> str:
    return role_name.strip().upper()


def resolve_role_provider_and_model(role_name: str) -> tuple[str, str | None]:
    role_suffix = _role_env_suffix(role_name)
    raw_role_provider = os.getenv(f"LLM_PROVIDER_{role_suffix}")
    global_provider = _normalize_provider(os.getenv("MULTI_AGENT_APP_LLM_PROVIDER"))
    role_provider = _normalize_provider(raw_role_provider)
    selected_provider = role_provider if role_provider != "heuristic" or global_provider == "heuristic" else global_provider
    if (raw_role_provider or "").strip().lower() == "heuristic":
        selected_provider = "heuristic"
    if selected_provider == "openai":
        return (
            "openai",
            os.getenv(f"OPENAI_MODEL_{role_suffix}") or os.getenv("OPENAI_MODEL", _OPENAI_DEFAULT_MODEL),
        )
    if selected_provider == "gemini":
        return (
            "gemini",
            os.getenv(f"GEMINI_MODEL_{role_suffix}") or os.getenv("GEMINI_MODEL", _GEMINI_DEFAULT_MODEL),
        )
    return "heuristic", None


def _provider_from_selection(provider_name: str, model: str | None) -> LLMProvider:
    if provider_name == "openai":
        return OpenAIChatProvider(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=model or _OPENAI_DEFAULT_MODEL,
        )
    if provider_name == "gemini":
        return GeminiProvider(
            api_key=os.getenv("GEMINI_API_KEY"),
            model=model or _GEMINI_DEFAULT_MODEL,
        )
    return NullLLMProvider()


def _compact_reason(reason: str | None, max_length: int = 40) -> str:
    text = (reason or "").strip()
    if not text:
        return "unknown"
    lower = text.lower()
    if text == "heuristic_configured":
        return "heuristic"
    if text == "provider_unavailable":
        return "no_api_key"
    if lower.startswith("network_error"):
        return "network"
    if text == "empty_or_unparseable_response":
        return "empty_response"
    if "quota" in lower:
        return "quota"
    if "rate limit" in lower or "http_429" in lower:
        return "rate_limited"
    if "api key" in lower or "http_401" in lower or "http_403" in lower or "permission" in lower:
        return "auth"
    if lower.startswith("http_5"):
        return "provider_error"
    if lower.startswith("http_4"):
        return "request_error"
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def summarize_fallback_notes(
    fallback_reasons: Mapping[str, str],
    *,
    max_items: int = 4,
) -> str:
    if not fallback_reasons:
        return "-"
    pairs = sorted((role, _compact_reason(reason)) for role, reason in fallback_reasons.items())
    visible = [f"{role}={reason}" for role, reason in pairs[:max_items]]
    remaining = len(pairs) - len(visible)
    if remaining > 0:
        visible.append(f"+{remaining} more")
    return ", ".join(visible)


def _compact_model_name(model: str | None, max_length: int = 26) -> str | None:
    if not model:
        return None
    text = model.strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def summarize_role_provider_map(
    role_provider_config: Mapping[str, Mapping[str, str | None]],
    *,
    max_items: int = 4,
) -> str:
    if not role_provider_config:
        return "-"
    pairs: list[str] = []
    for role, cfg in sorted(role_provider_config.items()):
        provider = (cfg.get("provider") or "heuristic").strip()
        model = _compact_model_name(cfg.get("model"))
        if model:
            pairs.append(f"{role}={provider}/{model}")
        else:
            pairs.append(f"{role}={provider}")
    visible = pairs[:max_items]
    remaining = len(pairs) - len(visible)
    if remaining > 0:
        visible.append(f"+{remaining} more")
    return ", ".join(visible)


def role_generation_mode_label(
    *,
    provider: str,
    model: str | None,
    enabled: bool,
    available: bool,
) -> str:
    provider_text = provider
    if provider == "mixed":
        provider_text = "mixed-per-role"
    if model == "mixed":
        provider_text = f"{provider_text} (model per role)"
    elif model:
        provider_text = f"{provider_text} ({_compact_model_name(model)})"
    return (
        f"provider={provider_text} | enabled={'yes' if enabled else 'no'} | "
        f"available={'yes' if available else 'no'}"
    )


def provider_key_status_label(
    *,
    provider: str,
    enabled: bool,
    available: bool,
    role_provider_config: Mapping[str, Mapping[str, str | None]] | None = None,
) -> str:
    configured_providers: set[str] = set()
    if role_provider_config:
        for cfg in role_provider_config.values():
            provider_name = (cfg.get("provider") or "heuristic").strip()
            if provider_name in {"openai", "gemini"}:
                configured_providers.add(provider_name)
    if not configured_providers and provider in {"openai", "gemini"}:
        configured_providers.add(provider)

    env_by_provider = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    expected_keys = ", ".join(env_by_provider[p] for p in sorted(configured_providers))

    if not enabled:
        return (
            "heuristic mode only. Set MULTI_AGENT_APP_LLM_PROVIDER=openai|gemini "
            "to enable provider calls."
        )
    if available:
        if expected_keys:
            return f"provider key detected ({expected_keys})."
        return "provider key detected."
    if expected_keys:
        return f"provider enabled but key missing ({expected_keys}); using heuristic fallback."
    return "provider enabled but key missing; using heuristic fallback."


def provider_from_env() -> LLMProvider:
    selected = os.getenv("MULTI_AGENT_APP_LLM_PROVIDER", "").strip().lower()
    if selected == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL", _OPENAI_DEFAULT_MODEL)
        return OpenAIChatProvider(api_key=api_key, model=model)
    if selected == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", _GEMINI_DEFAULT_MODEL)
        return GeminiProvider(api_key=api_key, model=model)
    return NullLLMProvider()


def provider_enabled_from_env() -> bool:
    selected = _normalize_provider(os.getenv("MULTI_AGENT_APP_LLM_PROVIDER"))
    if selected in {"openai", "gemini"}:
        return True
    for role in ("strateg", "analyst", "operator", "governance"):
        role_provider, _ = resolve_role_provider_and_model(role)
        if role_provider in {"openai", "gemini"}:
            return True
    return False


def apply_role_llm_overrides(
    *,
    provider: LLMProvider | None,
    roles: list[models.AdvisorRole],
    question: str,
    context: Mapping[str, object],
    assessment: models.DecisionAlignmentAssessment,
    heuristic_outputs: Mapping[str, str],
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, dict[str, str | None]],
    dict[str, bool],
]:
    output = dict(heuristic_outputs)
    role_sources = {
        role.name: "heuristic"
        for role in roles
        if role.name in output
    }
    fallback_reasons = {
        role.name: "heuristic_default"
        for role in roles
        if role.name in output
    }
    role_provider_config: dict[str, dict[str, str | None]] = {}
    role_provider_available: dict[str, bool] = {}

    for role in roles:
        if provider is None:
            provider_name, model = resolve_role_provider_and_model(role.name)
            role_provider = _provider_from_selection(provider_name, model)
        else:
            provider_name = provider.name
            model = getattr(provider, "model", None)
            role_provider = provider

        role_provider_config[role.name] = {
            "provider": provider_name,
            "model": model,
        }
        available = role_provider.is_available()
        role_provider_available[role.name] = available

        if provider_name == "heuristic":
            fallback_reasons[role.name] = "heuristic_configured"
            continue
        if not available:
            fallback_reasons[role.name] = "provider_unavailable"
            continue

        fallback = output.get(role.name, "")
        generated = role_provider.generate_role_response(
            role=role,
            question=question,
            context=context,
            assessment=assessment,
            fallback_response=fallback,
        )
        if generated:
            output[role.name] = generated
            role_sources[role.name] = "llm"
            fallback_reasons.pop(role.name, None)
            continue
        error_reason = getattr(role_provider, "last_error", None) or "empty_or_unparseable_response"
        fallback_reasons[role.name] = str(error_reason)
    return output, role_sources, fallback_reasons, role_provider_config, role_provider_available
