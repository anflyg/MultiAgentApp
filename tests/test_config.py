from multi_agent_app.config import (
    AppConfig,
    ensure_app_config,
    load_app_config,
    resolve_config_path,
    write_app_config,
)


def test_load_app_config_returns_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config, path = load_app_config()
    assert isinstance(config, AppConfig)
    assert config.default_db_path == "multi_agent.db"
    assert path == resolve_config_path()
    assert not path.exists()


def test_write_and_load_app_config_roundtrip(tmp_path):
    config_path = tmp_path / "app_config.json"
    expected = AppConfig(
        default_db_path="custom.db",
        default_session_name="Session X",
        default_task_description="Task X",
        default_agent_name="planner",
    )
    write_app_config(expected, config_path=str(config_path))
    loaded, path = load_app_config(str(config_path))
    assert path == config_path.resolve()
    assert loaded == expected


def test_ensure_app_config_creates_file(tmp_path):
    config_path = tmp_path / "config.json"
    config, path, created = ensure_app_config(str(config_path))
    assert created is True
    assert path.exists()
    assert config.default_db_path == "multi_agent.db"

    _, _, created_again = ensure_app_config(str(config_path))
    assert created_again is False
