"""Central configuration for the MCP server.

Everything a user can tune lives here: the defaults, the environment variable
names that override them, and the parsing that rejects bad values.

Constants that describe the daemon's protocol -- REST paths, daemon state
names -- are deliberately *not* here. They are not settings: changing one is
only correct if the daemon changed too, so they stay next to the code that
speaks that protocol.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

# Name this server reports to MCP clients during initialization.
SERVER_NAME = "reachy-mini"

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0

BASE_URL_ENV = "REACHY_MINI_DAEMON_URL"
TIMEOUT_ENV = "REACHY_MINI_TIMEOUT"


def _validate_base_url(base_url: str) -> None:
    """Reject values that cannot be an unambiguous daemon API base URL."""
    try:
        parsed_url = urlsplit(base_url)
        _ = parsed_url.port
    except ValueError as exc:
        raise ValueError(
            f"{BASE_URL_ENV} must be a valid HTTP(S) base URL, got {base_url!r}"
        ) from exc

    if (
        parsed_url.scheme not in {"http", "https"}
        or parsed_url.hostname is None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path not in {"", "/"}
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ValueError(
            f"{BASE_URL_ENV} must be an HTTP(S) origin without credentials, "
            f"path, query, or fragment, got {base_url!r}"
        )


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one run of the server."""

    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables, falling back to defaults.

        Invalid values raise immediately rather than being silently ignored:
        a misconfigured server should fail at startup, not on first tool call.
        """
        base_url = os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL).strip()
        if not base_url:
            raise ValueError(f"{BASE_URL_ENV} must not be empty")
        _validate_base_url(base_url)

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
