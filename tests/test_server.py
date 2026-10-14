from __future__ import annotations
from typing import Any
import httpx
import pytest
import respx
from mcp.types import CallToolResult
from reachy_mini_mcp.config import DEFAULT_BASE_URL, Settings
from reachy_mini_mcp.daemon_gateway import STATUS_PATH
from reachy_mini_mcp.server import create_server

STATUS_URL = f"{DEFAULT_BASE_URL}{STATUS_PATH}"
CUSTOM_BASE_URL = "http://reachy.test:9000"
STATUS_RESULT_FIELDS = {
    "is_reachable",
    "is_ready",
    "state",
    "robot_name",
    "version",
    "error",
}


def build_daemon_status_payload(state: str) -> dict:
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
    server = create_server(settings)
    result = await server.call_tool("get_daemon_status", {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    return result.structured_content


class TestGetDaemonStatus:
    @pytest.mark.parametrize("payload", ["not JSON", "[]"])
    @respx.mock
    async def test_invalid_payload_reports_reachable_but_not_ready(self, payload):
        respx.get(STATUS_URL).respond(200, text=payload)

        result = await call_daemon_status_tool(Settings())

        assert result["is_reachable"] is True
        assert result["is_ready"] is False
        assert result["error"] is not None

    async def test_output_schema_describes_result_fields(self):
        # Arrange
        server = create_server(Settings())

        # Act
        tools = await server.list_tools()
        status_tool = next(tool for tool in tools if tool.name == "get_daemon_status")
        output_schema = status_tool.output_schema

        # Assert
        assert output_schema is not None
        assert set(output_schema["properties"]) == STATUS_RESULT_FIELDS
        assert set(output_schema["required"]) == STATUS_RESULT_FIELDS

    @respx.mock
    async def test_running_daemon_is_ready(self):
        # Arrange
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(
                200,
                json=build_daemon_status_payload("running"),
            )
        )

        # Act
        result = await call_daemon_status_tool(Settings())

        # Assert
        assert result["is_reachable"] is True
        assert result["is_ready"] is True
        assert result["state"] == "running"
        assert result["robot_name"] == "reachy_mini"
        assert result["version"] == "1.9.0"
        assert result["error"] is None

    @respx.mock
    async def test_stopped_daemon_is_not_ready(self):
        # Arrange
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(
                200,
                json=build_daemon_status_payload("stopped"),
            )
        )

        # Act
        result = await call_daemon_status_tool(Settings())

        # Assert
        assert result["is_reachable"] is True
        assert result["is_ready"] is False
        assert result["state"] == "stopped"

    @respx.mock
    async def test_unreachable_daemon_reports_error(self):
        # Arrange
        respx.get(STATUS_URL).mock(side_effect=httpx.ConnectError("connection refused"))

        # Act
        result = await call_daemon_status_tool(Settings())

        # Assert
        assert result["is_reachable"] is False
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
        assert result["is_reachable"] is True
        assert result["is_ready"] is False
        assert result["error"] == "Daemon returned HTTP 500"

    @respx.mock
    async def test_custom_base_url_is_used(self):
        # Arrange
        settings = Settings(base_url=CUSTOM_BASE_URL)
        route = respx.get(f"{CUSTOM_BASE_URL}{STATUS_PATH}").mock(
            return_value=httpx.Response(
                200,
                json=build_daemon_status_payload("running"),
            )
        )

        # Act
        await call_daemon_status_tool(settings)

        # Assert
        assert route.called
