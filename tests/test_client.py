"""Tests for the daemon status tool, its configuration and the entrypoint.

The daemon's HTTP API is mocked throughout, so no robot or running daemon is
needed. Tests are grouped by the unit under test; the class name carries the
subject so each method name only has to state a condition and its outcome.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from reachy_mini_mcp.__main__ import CONFIG_ERROR_EXIT_CODE, main
from reachy_mini_mcp.config import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_ENV,
    Settings,
)
from reachy_mini_mcp.daemon import STATUS_PATH
from reachy_mini_mcp.server import create_server

STATUS_URL = f"{DEFAULT_BASE_URL}{STATUS_PATH}"
CUSTOM_BASE_URL = "http://reachy.test:9000"
STATUS_RESULT_FIELDS = {
    "reachable",
    "is_ready",
    "state",
    "robot_name",
    "version",
    "error",
}


def build_daemon_payload(state: str) -> dict:
    """Return a daemon status payload as the real daemon v1.9.0 sends it."""
    return {
        "type": "daemon_status",
        "robot_name": "reachy_mini",
        "state": state,
        "wireless_version": False,
        "camera_specs_name": "lite",
        "backend_status": None,
        "error": None,
        "version": "1.9.0",
    }


async def call_daemon_status_tool(settings: Settings) -> dict[str, Any]:
    """Call the daemon status tool through its public MCP interface."""
    server = create_server(settings)
    result = await server.call_tool("get_daemon_status", {})
    assert result.structured_content is not None
    return result.structured_content


class TestGetDaemonStatus:
    """The MCP tool reporting daemon reachability and robot readiness."""

    async def test_output_schema_describes_result_fields(self):
        # Arrange
        server = create_server(Settings())

        # Act
        tools = await server.list_tools()
        status_tool = next(tool for tool in tools if tool.name == "get_daemon_status")

        # Assert
        assert set(status_tool.output_schema["properties"]) == STATUS_RESULT_FIELDS
        assert set(status_tool.output_schema["required"]) == STATUS_RESULT_FIELDS

    @respx.mock
    async def test_running_daemon_is_ready(self):
        # Arrange
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(200, json=build_daemon_payload("running"))
        )

        # Act
        result = await call_daemon_status_tool(Settings())

        # Assert
        assert result["reachable"] is True
        assert result["is_ready"] is True
        assert result["state"] == "running"
        assert result["robot_name"] == "reachy_mini"
        assert result["version"] == "1.9.0"
        assert result["error"] is None

    @respx.mock
    async def test_stopped_daemon_is_not_ready(self):
        # Arrange
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(200, json=build_daemon_payload("stopped"))
        )

        # Act
        result = await call_daemon_status_tool(Settings())

        # Assert
        assert result["reachable"] is True
        assert result["is_ready"] is False
        assert result["state"] == "stopped"

    @respx.mock
    async def test_unreachable_daemon_reports_error(self):
        # Arrange
        respx.get(STATUS_URL).mock(side_effect=httpx.ConnectError("connection refused"))

        # Act
        result = await call_daemon_status_tool(Settings())

        # Assert
        assert result["reachable"] is False
        assert result["is_ready"] is False
        assert result["state"] is None
        assert "not reachable" in result["error"]

    @respx.mock
    async def test_http_error_keeps_daemon_reachable(self):
        # Arrange
        respx.get(STATUS_URL).mock(return_value=httpx.Response(500))

        # Act
        result = await call_daemon_status_tool(Settings())

        # Assert
        assert result["reachable"] is True
        assert result["is_ready"] is False
        assert result["error"] == "Daemon returned HTTP 500"

    @respx.mock
    async def test_custom_base_url_is_used(self):
        # Arrange
        settings = Settings(base_url=CUSTOM_BASE_URL)
        route = respx.get(f"{CUSTOM_BASE_URL}{STATUS_PATH}").mock(
            return_value=httpx.Response(
                200,
                json=build_daemon_payload("running"),
            )
        )

        # Act
        await call_daemon_status_tool(settings)

        # Assert
        assert route.called


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
