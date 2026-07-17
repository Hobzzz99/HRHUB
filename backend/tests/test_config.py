"""Config parsing tests."""

from __future__ import annotations

from app.core.config import Settings


def test_cors_origins_parses_comma_separated_env(monkeypatch):
    # Regression: pydantic-settings must NOT try to JSON-decode this list field.
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, http://b.com")
    settings = Settings()
    assert settings.cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_default():
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://localhost:3000"]


def test_ai_enabled_requires_key_and_flag(monkeypatch):
    monkeypatch.setenv("AI_MATCHING", "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert Settings().ai_enabled is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert Settings().ai_enabled is True
