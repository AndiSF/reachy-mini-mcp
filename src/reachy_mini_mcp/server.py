from __future__ import annotations
from typing import Any, TypedDict
from mcp.server.mcpserver import MCPServer
from . import __version__
from .config import SERVER_NAME, Settings
from .daemon_gateway import (
    DaemonGateway,
    DaemonResponseError,
    DaemonUnreachableError,
)

READY_STATE = "running"


class DaemonStatusResult(TypedDict):
    reachable: bool
    is_ready: bool
    state: str | None
    robot_name: str | None
    version: str | None
    error: str | None


def _build_status_result(
    daemon_status_payload: dict[str, Any],
) -> DaemonStatusResult:
    state = daemon_status_payload.get("state")
    return {
        "reachable": True,
        "is_ready": state == READY_STATE,
        "state": state,
        "robot_name": daemon_status_payload.get("robot_name"),
        "version": daemon_status_payload.get("version"),
        "error": daemon_status_payload.get("error"),
    }


def _build_error_result(*, reachable: bool, error: str) -> DaemonStatusResult:
    return {
        "reachable": reachable,
        "is_ready": False,
        "state": None,
        "robot_name": None,
        "version": None,
        "error": error,
    }


def create_server(settings: Settings) -> MCPServer:
    mcp = MCPServer(SERVER_NAME, version=__version__)
    gateway = DaemonGateway(settings)

    @mcp.tool()
    async def get_daemon_status() -> DaemonStatusResult:
        """Check Reachy Mini daemon reachability and robot backend readiness."""
        try:
            daemon_status_payload = await gateway.get_status()
        except DaemonUnreachableError as exc:
            return _build_error_result(
                reachable=False,
                error=f"Daemon is not reachable: {exc}",
            )
        except DaemonResponseError as exc:
            return _build_error_result(
                reachable=True,
                error=f"Daemon returned HTTP {exc.status_code}",
            )

        return _build_status_result(daemon_status_payload)

    return mcp
