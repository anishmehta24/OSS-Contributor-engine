"""Sanity tests for Batch 1: scaffold loads, config parses, logging works."""
import pytest

from app.core.config import Settings, settings
from app.core.logging import configure_logging, get_logger


@pytest.mark.unit
def test_settings_loads_with_defaults(monkeypatch, tmp_path):
    """Settings falls back to defaults when no env file and no env vars exist."""
    for key in ("GITHUB_TOKEN", "GEMINI_API_KEY", "GROQ_API_KEY",
                "VOYAGE_API_KEY", "LOG_LEVEL", "DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    # Point at an empty file to override the project-level .env
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    s = Settings(_env_file=str(empty_env))
    assert s.github_token == ""
    assert s.gemini_api_key == ""
    assert s.log_level == "INFO"
    assert s.has_github is False
    assert s.has_any_llm is False


@pytest.mark.unit
def test_settings_singleton_is_settings_instance():
    assert isinstance(settings, Settings)


@pytest.mark.unit
def test_logging_configures_without_error():
    configure_logging()
    log = get_logger("test")
    log.info("test_event", value=42)
