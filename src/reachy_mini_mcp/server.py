from __future__ import annotations
from collections.abc import Awaitable
from http import HTTPStatus
from typing import Any, TypedDict
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from . import __version__
from .config import SERVER_NAME, Settings
from .daemon_gateway import (
    DaemonGateway,
    DaemonPayloadError,
    DaemonResponseError,
    DaemonUnreachableError,
)

READY_STATE = "running"


class DaemonStatusResult(TypedDict):
    is_reachable: bool
    is_ready: bool
    state: str | None
    robot_name: str | None
    version: str | None
    error: str | None


class DaemonCommandResult(TypedDict):
    """Job acceptance, not completion; None means acceptance is unknown."""

    accepted: bool | None
    job_id: str | None
    error: str | None


async def _run_daemon_command(command: Awaitable[str]) -> DaemonCommandResult:
    try:
        job_id = await command
    except DaemonResponseError as exc:
        if exc.status_code == HTTPStatus.CONFLICT:
            error = "Daemon is busy (HTTP 409); command was not accepted."
        else:
            error = f"Daemon returned HTTP {exc.status_code}"
        if HTTPStatus.BAD_REQUEST <= exc.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
            return {"accepted": False, "job_id": None, "error": error}
    except (DaemonUnreachableError, DaemonPayloadError) as exc:
        error = str(exc)
    else:
        return {"accepted": True, "job_id": job_id, "error": None}

    return {
        "accepted": None,
        "job_id": None,
        "error": f"Could not confirm command acceptance: {error}. "
        "Check get_daemon_status before retrying.",
    }


def _build_status_result(
    daemon_status_payload: dict[str, Any],
) -> DaemonStatusResult:
    state = daemon_status_payload.get("state")
    return {
        "is_reachable": True,
        "is_ready": state == READY_STATE,
        "state": state,
        "robot_name": daemon_status_payload.get("robot_name"),
        "version": daemon_status_payload.get("version"),
        "error": daemon_status_payload.get("error"),
    }


def _build_error_result(*, is_reachable: bool, error: str) -> DaemonStatusResult:
    return {
        "is_reachable": is_reachable,
        "is_ready": False,
        "state": None,
        "robot_name": None,
        "version": None,
        "error": error,
    }


def create_server(settings: Settings) -> MCPServer:
    mcp_server = MCPServer(SERVER_NAME, version=__version__)
    gateway = DaemonGateway(settings)

    @mcp_server.tool()
    async def get_daemon_status() -> DaemonStatusResult:
        """Check Reachy Mini daemon reachability and robot backend readiness."""
        try:
            daemon_status_payload = await gateway.get_status()
        except DaemonUnreachableError as exc:
            return _build_error_result(
                is_reachable=False,
                error=f"Daemon is not reachable: {exc}",
            )
        except DaemonResponseError as exc:
            return _build_error_result(
                is_reachable=True,
                error=f"Daemon returned HTTP {exc.status_code}",
            )
        except DaemonPayloadError as exc:
            return _build_error_result(is_reachable=True, error=str(exc))

        return _build_status_result(daemon_status_payload)

    command_annotations = ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=False
    )

    @mcp_server.tool(annotations=command_annotations)
    async def start_daemon(wake_up: bool) -> DaemonCommandResult:
        """Start the robot backend; wake_up explicitly opts into the wake-up motion.

        Returns job acceptance, not completion. Use get_daemon_status to check
        for running or error. Do not automatically retry an uncertain result.
        """
        return await _run_daemon_command(gateway.start(wake_up=wake_up))

    @mcp_server.tool(annotations=command_annotations)
    async def stop_daemon(goto_sleep: bool) -> DaemonCommandResult:
        """Stop the robot backend; goto_sleep opts into the sleep motion.

        The HTTP API stays available. Returns job acceptance, not completion.
        Use get_daemon_status to check for stopped or error. Do not automatically
        retry an uncertain result.
        """
        return await _run_daemon_command(gateway.stop(goto_sleep=goto_sleep))

    @mcp_server.tool(annotations=command_annotations)
    async def restart_daemon() -> DaemonCommandResult:
        """Reinitialize the robot backend using its previous start settings.

        Does not restart the HTTP server or computer, or request sleep/wake-up
        motions. This does not guarantee no physical movement. In daemon v1.9.0,
        a stopped backend stays stopped; use start_daemon to start it.
        Returns job acceptance, not completion. Use get_daemon_status to check
        the state. Do not automatically retry an uncertain result.
        """
        return await _run_daemon_command(gateway.restart())

    return mcp_server
