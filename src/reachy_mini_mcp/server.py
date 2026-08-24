"""MCP server exposing Reachy Mini daemon operations as tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import SERVER_NAME, Settings
from .daemon import DaemonClient, DaemonResponseError, DaemonUnreachableError

# The daemon reports this state once the robot backend is fully operational.
READY_STATE = "running"


def build_status_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw daemon status payload to the fields a caller acts on."""
    state = raw.get("state")
    return {
        "reachable": True,
        "is_ready": state == READY_STATE,
        "state": state,
        "robot_name": raw.get("robot_name"),
        "version": raw.get("version"),
        "error": raw.get("error"),
    }


def build_error_result(*, reachable: bool, error: str) -> dict[str, Any]:
    """Build a status result for a failed lookup.

    ``reachable`` stays true when the daemon answered but the answer was
    unusable, so callers can tell "process is down" from "process is broken".
    """
    return {
        "reachable": reachable,
        "is_ready": False,
        "state": None,
        "robot_name": None,
        "version": None,
        "error": error,
    }


def create_server(settings: Settings) -> MCPServer:
    """Create an MCP server configured for one daemon."""
    mcp = MCPServer(SERVER_NAME, version=__version__)
    client = DaemonClient(settings)

    @mcp.tool()
    async def get_daemon_status() -> dict[str, Any]:
        """Check whether the Reachy Mini daemon is reachable and the robot is ready.

        Returns a dict with:
          reachable  - the daemon process answered on its HTTP port
          is_ready   - the robot backend is running and can accept commands
          state      - daemon state: not_initialized, starting, running, stopping,
                       stopped or error (null when unreachable)
          robot_name - configured robot name
          version    - daemon version
          error      - error message from the daemon or from this lookup, else null

        A daemon that is reachable but not ready means the process is up while the
        robot backend is stopped; the robot will not move until it is started.
        """
        try:
            raw = await client.get_status()
        except DaemonUnreachableError as exc:
            return build_error_result(
                reachable=False,
                error=f"Daemon is not reachable: {exc}",
            )
        except DaemonResponseError as exc:
            return build_error_result(
                reachable=True,
                error=f"Daemon returned HTTP {exc.status_code}",
            )

        return build_status_result(raw)

    return mcp
