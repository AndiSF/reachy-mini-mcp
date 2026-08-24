from __future__ import annotations
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

SERVER_NAME = "reachy-mini"

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0

BASE_URL_ENV = "REACHY_MINI_DAEMON_URL"
TIMEOUT_ENV = "REACHY_MINI_TIMEOUT"


def _validate_base_url(base_url: str) -> None:
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
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> Settings:
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
