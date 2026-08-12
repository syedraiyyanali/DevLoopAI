import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_ignore_generic_debug_environment_variable(monkeypatch):
    monkeypatch.setenv("DEBUG", "release")
    monkeypatch.delenv("DEVLOOPAI_DEBUG", raising=False)

    settings = Settings(_env_file=None)

    assert settings.debug is True


def test_settings_read_devloopai_prefixed_environment_variable(monkeypatch):
    monkeypatch.setenv("DEBUG", "release")
    monkeypatch.setenv("DEVLOOPAI_DEBUG", "false")

    settings = Settings(_env_file=None)

    assert settings.debug is False


def test_settings_normalize_log_level(monkeypatch):
    monkeypatch.setenv("DEVLOOPAI_LOG_LEVEL", "warning")

    settings = Settings(_env_file=None)

    assert settings.log_level == "WARNING"


def test_settings_reject_invalid_log_level(monkeypatch):
    monkeypatch.setenv("DEVLOOPAI_LOG_LEVEL", "verbose")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
