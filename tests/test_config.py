from __future__ import annotations
import pytest
from reachy_mini_mcp.config import (
    BASE_URL_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_ENV,
    Settings,
)


class TestSettingsFromEnv:
    def test_uses_defaults_without_overrides(self, monkeypatch):
        # Arrange
        monkeypatch.delenv(BASE_URL_ENV, raising=False)
        monkeypatch.delenv(TIMEOUT_ENV, raising=False)

        # Act
        settings = Settings.from_env()

        # Assert
        assert settings.base_url == DEFAULT_BASE_URL
        assert settings.timeout_seconds == DEFAULT_TIMEOUT_SECONDS

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://localhost:8000",
            "https://reachy.local",
            "http://127.0.0.1:8000/",
            "http://[::1]:8000",
        ],
    )
    def test_accepts_valid_base_url(self, monkeypatch, base_url):
        # Arrange
        monkeypatch.setenv(BASE_URL_ENV, base_url)

        # Act
        settings = Settings.from_env()

        # Assert
        assert settings.base_url == base_url

    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "localhost:8000",
            "ftp://reachy.local",
            "https:///api",
            "http://user:password@reachy.local",
            "http://reachy.local/api",
            "http://reachy.local?mode=test",
            "http://reachy.local#status",
            "http://reachy.local:70000",
        ],
    )
    def test_rejects_invalid_base_url(self, monkeypatch, base_url):
        # Arrange
        monkeypatch.setenv(BASE_URL_ENV, base_url)

        # Act / Assert
        with pytest.raises(ValueError, match=BASE_URL_ENV):
            Settings.from_env()

    def test_rejects_non_numeric_timeout(self, monkeypatch):
        # Arrange
        monkeypatch.setenv(TIMEOUT_ENV, "soon")

        # Act / Assert
        with pytest.raises(ValueError, match=TIMEOUT_ENV):
            Settings.from_env()
