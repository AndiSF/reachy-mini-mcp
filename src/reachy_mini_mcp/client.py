"""Async HTTP client for the Reachy Mini daemon REST API.

This module knows nothing about MCP. It is a thin, typed wrapper around the
daemon's HTTP endpoints so the MCP layer can stay free of transport concerns.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0

BASE_URL_ENV = "REACHY_MINI_DAEMON_URL"
TIMEOUT_ENV = "REACHY_MINI_TIMEOUT"

STATUS_PATH = "/api/daemon/status"


class DaemonUnreachableError(Exception):
    """The daemon process did not answer at all (down, wrong port, timeout)."""


@dataclass(frozen=True)
class DaemonClientConfig:
    """Connection settings for the daemon REST API."""

    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> DaemonClientConfig:
        """Build a config from environment variables, falling back to defaults.

        Invalid values raise immediately rather than being silently ignored:
        a misconfigured server should fail at startup, not on first tool call.
        """
        base_url = os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL).strip()
        if not base_url:
            raise ValueError(f"{BASE_URL_ENV} must not be empty")

        raw_timeout = os.getenv(TIMEOUT_ENV)
        if raw_timeout is None:
            return cls(base_url=base_url)

        try:
            timeout_seconds = float(raw_timeout)
        except ValueError as exc:
            raise ValueError(
                f"{TIMEOUT_ENV} must be a number, got {raw_timeout!r}"
            ) from exc
        if timeout_seconds <= 0:
            raise ValueError(f"{TIMEOUT_ENV} must be positive, got {timeout_seconds}")

        return cls(base_url=base_url, timeout_seconds=timeout_seconds)


class DaemonClient:
    """Talks to the Reachy Mini daemon over HTTP."""

    def __init__(self, config: DaemonClientConfig | None = None) -> None:
        self._config = config or DaemonClientConfig()

    async def get_status(self) -> dict[str, Any]:
        """Return the raw daemon status payload.

        Raises:
            DaemonUnreachableError: the daemon did not answer.
            httpx.HTTPStatusError: the daemon answered with an error status.
        """
        async with httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
        ) as client:
            try:
                response = await client.get(STATUS_PATH)
            except httpx.RequestError as exc:
                raise DaemonUnreachableError(str(exc)) from exc

            response.raise_for_status()
            return response.json()
