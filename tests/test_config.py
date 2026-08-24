"""Tests for resolving server settings from the environment."""

from __future__ import annotations

import pytest

from reachy_mini_mcp.config import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_ENV,
    Settings,
)


class TestSettingsFromEnv:
    """Resolving settings from environment variables."""

    def test_uses_defaults_without_overrides(self, monkeypatch):
        # Arrange
        monkeypatch.delenv(TIMEOUT_ENV, raising=False)

        # Act
        settings = Settings.from_env()

        # Assert
        assert settings.base_url == DEFAULT_BASE_URL
        assert settings.timeout_seconds == DEFAULT_TIMEOUT_SECONDS

    def test_rejects_non_numeric_timeout(self, monkeypatch):
        # Arrange
        monkeypatch.setenv(TIMEOUT_ENV, "soon")

        # Act / Assert
        with pytest.raises(ValueError, match=TIMEOUT_ENV):
            Settings.from_env()
