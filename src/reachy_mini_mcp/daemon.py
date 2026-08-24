"""Async HTTP client for the Reachy Mini daemon REST API.

This module knows nothing about MCP. It is a thin, typed wrapper around the
daemon's HTTP endpoints so the MCP layer can stay free of transport concerns.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings

# Daemon REST API surface, fixed by the daemon rather than by configuration.
STATUS_PATH = "/api/daemon/status"


class DaemonUnreachableError(Exception):
    """The daemon process did not answer at all (down, wrong port, timeout)."""


class DaemonResponseError(Exception):
    """The daemon answered, but with an error status."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class DaemonClient:
    """Talks to the Reachy Mini daemon over HTTP."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_status(self) -> dict[str, Any]:
        """Return the raw daemon status payload.

        Raises:
            DaemonUnreachableError: the daemon did not answer.
            DaemonResponseError: the daemon answered with an error status.
        """
        async with httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=self._settings.timeout_seconds,
        ) as client:
            try:
                response = await client.get(STATUS_PATH)
            except httpx.RequestError as exc:
                raise DaemonUnreachableError(str(exc)) from exc

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise DaemonResponseError(exc.response.status_code) from exc

            return response.json()
