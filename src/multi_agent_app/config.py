from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG_FILENAME = ".multi_agent_app_config.json"


@dataclass(frozen=True)
class AppConfig:
    """User-facing configuration values (not internal runtime state)."""

    default_db_path: str = "multi_agent.db"
    default_session_name: str = "Demo Session"
    default_task_description: str = "Write a welcome message"
    default_agent_name: str = "writer"
    llm_provider: str = "heuristic"
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_api_key: str = ""
    role_llm_overrides: dict[str, dict[str, str | None]] = field(default_factory=dict)


def _coerce_role_llm_overrides(raw: object) -> dict[str, dict[str, str | None]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict[str, str | None]] = {}
    for role_name, value in raw.items():
        if not isinstance(role_name, str):
            continue
        if not isinstance(value, dict):
            continue
        provider = value.get("provider")
        model = value.get("model")
        cleaned[role_name] = {
            "provider": str(provider).strip() if provider is not None else None,
            "model": str(model).strip() if model is not None else None,
        }
    return cleaned


def resolve_config_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path).expanduser().resolve()
    return (Path.cwd() / DEFAULT_CONFIG_FILENAME).resolve()


def _coerce_config(data: dict[str, object]) -> AppConfig:
    return AppConfig(
        default_db_path=str(data.get("default_db_path", AppConfig.default_db_path)),
        default_session_name=str(data.get("default_session_name", AppConfig.default_session_name)),
        default_task_description=str(
            data.get("default_task_description", AppConfig.default_task_description)
        ),
        default_agent_name=str(data.get("default_agent_name", AppConfig.default_agent_name)),
        llm_provider=str(data.get("llm_provider", AppConfig.llm_provider)),
        openai_model=str(data.get("openai_model", AppConfig.openai_model)),
        openai_api_key=str(data.get("openai_api_key", AppConfig.openai_api_key)),
        gemini_model=str(data.get("gemini_model", AppConfig.gemini_model)),
        gemini_api_key=str(data.get("gemini_api_key", AppConfig.gemini_api_key)),
        role_llm_overrides=_coerce_role_llm_overrides(
            data.get("role_llm_overrides", {})
        ),
    )


def load_app_config(config_path: str | None = None) -> tuple[AppConfig, Path]:
    path = resolve_config_path(config_path)
    if not path.exists():
        return AppConfig(), path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig(), path
    if not isinstance(payload, dict):
        return AppConfig(), path
    return _coerce_config(payload), path


def write_app_config(config: AppConfig, config_path: str | None = None) -> Path:
    path = resolve_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ensure_app_config(config_path: str | None = None) -> tuple[AppConfig, Path, bool]:
    config, path = load_app_config(config_path)
    if path.exists():
        return config, path, False
    write_app_config(config, config_path=str(path))
    return config, path, True
