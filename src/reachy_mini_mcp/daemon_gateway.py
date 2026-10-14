from __future__ import annotations
from typing import Any, Literal
import httpx
from .config import Settings

STATUS_PATH = "/api/daemon/status"
START_PATH = "/api/daemon/start"
STOP_PATH = "/api/daemon/stop"
RESTART_PATH = "/api/daemon/restart"


class DaemonUnreachableError(Exception):
    pass


class DaemonResponseError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class DaemonPayloadError(Exception):
    pass


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
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=self._settings.timeout_seconds,
        ) as client:
            try:
                response = await client.request(method, path, params=params)
            except httpx.RequestError as exc:
                raise DaemonUnreachableError(str(exc)) from exc

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise DaemonResponseError(exc.response.status_code) from exc

            try:
                payload = response.json()
            except ValueError as exc:
                raise DaemonPayloadError("Daemon response is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise DaemonPayloadError("Daemon response is not a JSON object")
            return payload
