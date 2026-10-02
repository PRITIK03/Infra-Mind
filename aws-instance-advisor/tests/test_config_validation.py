"""
Tests for fail-fast startup configuration validation.

Validates that missing required variables fail immediately at startup with a
consolidated error message rather than failing late or deep in graph execution.
"""

from __future__ import annotations

import os
import pytest

from app.config import ConfigError, validate_startup_config


def test_validate_startup_config_passes_when_all_required_set(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("VANTAGE_API_KEY", "test-vantage-key")

    # Should not raise
    validate_startup_config()


def test_validate_startup_config_fails_single_missing(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.delenv("VANTAGE_API_KEY", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        validate_startup_config()

    assert "Missing required environment variable(s): VANTAGE_API_KEY" in str(exc_info.value)


def test_validate_startup_config_consolidates_multiple_missing(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("VANTAGE_API_KEY", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        validate_startup_config()

    err = str(exc_info.value)
    assert "Missing required environment variable(s):" in err
    assert "API_KEY" in err
    assert "BASE_URL" in err
    assert "MODEL_NAME" in err
    assert "VANTAGE_API_KEY" in err
