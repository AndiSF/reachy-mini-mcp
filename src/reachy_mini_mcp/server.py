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
    SoundValidationError,
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


class SoundUploadResult(TypedDict):
    uploaded: bool | None
    file: str | None
    error: str | None


class SoundActionResult(TypedDict):
    accepted: bool | None
    error: str | None


async def _run_audio_operation(
    operation: Awaitable[str | None],
) -> tuple[bool | None, str | None, str | None]:
    """Return confirmation, optional uploaded reference, and a safe error."""
    try:
        file = await operation
    except SoundValidationError as exc:
        return False, None, str(exc)
    except DaemonResponseError as exc:
        error = f"Daemon returned HTTP {exc.status_code}"
        if exc.backend_not_running:
            return False, None, f"{error}: Backend not running"
        if HTTPStatus.BAD_REQUEST <= exc.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
            return False, None, error
    except (DaemonUnreachableError, DaemonPayloadError) as exc:
        error = str(exc)
    else:
        return True, file, None
    return (
        None,
        None,
        f"Could not confirm audio operation: {error}. "
        "The operation may already have occurred. Do not automatically retry.",
    )


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

    @mcp_server.tool(annotations=command_annotations)
    async def upload_sound(file_path: str) -> SoundUploadResult:
        """Upload an absolute MCP-host audio path, at most 25 MiB, to the daemon.

        Returns file only on confirmed success; pass it to play_sound. The source
        is preserved. Daemon storage is temporary; matching basenames overwrite
        earlier uploads, so use unique filenames. TTS is external. An unknown
        outcome must not be automatically retried.
        """
        uploaded, file, error = await _run_audio_operation(
            gateway.upload_sound(file_path)
        )
        return {"uploaded": uploaded, "file": file, "error": error}

    @mcp_server.tool(annotations=command_annotations)
    async def play_sound(file: str) -> SoundActionResult:
        """Request speaker playback using a daemon-side file reference.

        Prefer file from upload_sound; daemon-local paths, built-in names and
        uploaded filenames also work. Requires a ready backend. Acceptance does
        not confirm audible playback or completion. No automatic retries.
        """
        accepted, _, error = await _run_audio_operation(gateway.play_sound(file))
        return {"accepted": accepted, "error": error}

    @mcp_server.tool(annotations=command_annotations)
    async def stop_sound() -> SoundActionResult:
        """Request stopping sound-file playback on a ready backend.

        Does not stop the backend or clear streaming-audio queues. Acceptance
        does not confirm completion. No automatic retries.
        """
        accepted, _, error = await _run_audio_operation(gateway.stop_sound())
        return {"accepted": accepted, "error": error}

    return mcp_server
