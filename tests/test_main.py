"""Tests for the stdio entrypoint."""

from __future__ import annotations
import pytest
from reachy_mini_mcp.__main__ import CONFIG_ERROR_EXIT_CODE, main
from reachy_mini_mcp.config import TIMEOUT_ENV


class TestMain:
    """The stdio entrypoint."""

    def test_exits_with_config_error_on_stderr(self, monkeypatch, capsys):
        # Arrange
        monkeypatch.setenv(TIMEOUT_ENV, "soon")

        # Act
        with pytest.raises(SystemExit) as exit_info:
            main()

        # Assert
        assert exit_info.value.code == CONFIG_ERROR_EXIT_CODE
        captured = capsys.readouterr()
        assert TIMEOUT_ENV in captured.err
        assert "soon" in captured.err
        assert captured.out == ""
