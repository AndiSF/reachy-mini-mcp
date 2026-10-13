"""Exercise the MCP stdio server against a real, already-running MuJoCo daemon."""

import sys
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from reachy_mini_mcp.config import BASE_URL_ENV, TIMEOUT_ENV, Settings
from reachy_mini_mcp.daemon_gateway import STATUS_PATH


@pytest.mark.integration
async def test_get_daemon_status_over_stdio_with_mujoco():
    # Confirm that the daemon is running MuJoCo rather than a physical robot
    # or the mockup backend; the MCP tool does not expose these simulator flags.
    settings = Settings.from_env()
    async with httpx.AsyncClient(
        base_url=settings.base_url,
        timeout=settings.timeout_seconds,
        trust_env=False,
    ) as client:
        response = await client.get(STATUS_PATH)
        response.raise_for_status()
        daemon_status = response.json()

    assert daemon_status["simulation_enabled"] is True, daemon_status
    assert daemon_status["mockup_sim_enabled"] is False, daemon_status
    assert daemon_status["state"] == "running", daemon_status
    assert daemon_status["error"] is None, daemon_status

    # Use the pytest interpreter and the package's stdio entrypoint on every OS.
    # Explicitly pass settings because the MCP SDK sanitizes the child environment.
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "reachy_mini_mcp"],
        env={
            BASE_URL_ENV: settings.base_url,
            TIMEOUT_ENV: str(settings.timeout_seconds),
        },
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(
            reader, writer, read_timeout_seconds=settings.timeout_seconds + 10
        ) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        assert "get_daemon_status" in {tool.name for tool in tools.tools}

        result = await session.call_tool("get_daemon_status", {})
        assert not result.is_error, result
        status = result.structured_content
        assert status is not None, result
        assert status["is_reachable"] is True, status
        assert status["is_ready"] is True, status
        assert status["state"] == "running", status
        assert status["error"] is None, status
        assert status["robot_name"] == daemon_status["robot_name"], status
        assert status["version"] == daemon_status["version"], status
