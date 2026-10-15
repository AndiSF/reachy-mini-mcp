from __future__ import annotations
import asyncio
import os
import stat
from contextlib import suppress
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal
import httpx
from .config import Settings

STATUS_PATH = "/api/daemon/status"
START_PATH = "/api/daemon/start"
STOP_PATH = "/api/daemon/stop"
RESTART_PATH = "/api/daemon/restart"
UPLOAD_SOUND_PATH = "/api/media/sounds/upload"
PLAY_SOUND_PATH = "/api/media/play_sound"
STOP_SOUND_PATH = "/api/media/stop_sound"
ALLOWED_SOUND_EXTENSIONS = frozenset(
    {".wav", ".mp3", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac"}
)
MAX_SOUND_UPLOAD_BYTES = 25 * 1024 * 1024


class DaemonUnreachableError(Exception):
    pass


class DaemonResponseError(Exception):
    def __init__(self, status_code: int, *, backend_not_running: bool = False) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.backend_not_running = backend_not_running


class DaemonPayloadError(Exception):
    pass


class SoundValidationError(Exception):
    pass


def _read_sound_file(file_path: str) -> tuple[str, bytes]:
    """Read at most the upload limit plus one byte, outside the event loop."""
    path = Path(file_path)
    if not path.is_absolute():
        raise SoundValidationError("file_path must be an absolute path on the MCP host")
    if path.suffix.lower() not in ALLOWED_SOUND_EXTENSIONS:
        raise SoundValidationError("Unsupported audio extension")
    try:
        if not path.is_file():
            raise SoundValidationError("Audio source must be a readable regular file")
        with path.open("rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise SoundValidationError("Audio source must be a regular file")
            if metadata.st_size > MAX_SOUND_UPLOAD_BYTES:
                raise SoundValidationError(
                    "Audio source exceeds the 25 MiB upload limit"
                )
            content = source.read(MAX_SOUND_UPLOAD_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise SoundValidationError("Could not read the local audio file") from exc
    if len(content) > MAX_SOUND_UPLOAD_BYTES:
        raise SoundValidationError("Audio source exceeds the 25 MiB upload limit")
    return path.name, content


def _validate_audio_response(payload: dict[str, Any]) -> None:
    if payload.get("status") != "ok":
        raise DaemonPayloadError("Daemon audio response has no valid status: ok")


class DaemonGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_status(self) -> dict[str, Any]:
        return await self._request("GET", STATUS_PATH)

    async def start(self, *, wake_up: bool) -> str:
        return await self._submit_command(START_PATH, params={"wake_up": wake_up})

    async def stop(self, *, goto_sleep: bool) -> str:
        return await self._submit_command(STOP_PATH, params={"goto_sleep": goto_sleep})

    async def restart(self) -> str:
        return await self._submit_command(RESTART_PATH)

    async def upload_sound(self, file_path: str) -> str:
        filename, content = await asyncio.to_thread(_read_sound_file, file_path)
        payload = await self._request(
            "POST",
            UPLOAD_SOUND_PATH,
            files={"file": (filename, content, "application/octet-stream")},
        )
        _validate_audio_response(payload)
        file = payload.get("path")
        if not isinstance(file, str) or not file.strip() or "\x00" in file:
            raise DaemonPayloadError("Daemon upload response has no valid path")
        return file

    async def play_sound(self, file: str) -> None:
        if not file.strip():
            raise SoundValidationError("file must be a nonempty daemon-side reference")
        payload = await self._request("POST", PLAY_SOUND_PATH, json={"file": file})
        _validate_audio_response(payload)

    async def stop_sound(self) -> None:
        payload = await self._request("POST", STOP_SOUND_PATH)
        _validate_audio_response(payload)

    async def _submit_command(
        self, path: str, *, params: dict[str, bool] | None = None
    ) -> str:
        payload = await self._request("POST", path, params=params)
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise DaemonPayloadError("Daemon response has no valid job_id")
        return job_id

    async def _request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        params: dict[str, bool] | None = None,
        json: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=self._settings.timeout_seconds,
        ) as client:
            try:
                response = await client.request(
                    method, path, params=params, json=json, files=files
                )
            except httpx.RequestError as exc:
                raise DaemonUnreachableError(
                    f"Daemon request failed ({type(exc).__name__})"
                ) from exc

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                backend_not_running = False
                if response.status_code == HTTPStatus.SERVICE_UNAVAILABLE and path in {
                    PLAY_SOUND_PATH,
                    STOP_SOUND_PATH,
                }:
                    with suppress(ValueError):
                        backend_not_running = response.json() == {
                            "detail": "Backend not running"
                        }
                raise DaemonResponseError(
                    response.status_code, backend_not_running=backend_not_running
                ) from exc

            try:
                payload = response.json()
            except ValueError as exc:
                raise DaemonPayloadError("Daemon response is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise DaemonPayloadError("Daemon response is not a JSON object")
            return payload
