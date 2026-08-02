"""Tests for the daemon status lookup, with the daemon's HTTP API mocked."""

from __future__ import annotations

import httpx
import pytest
import respx

from reachy_mini_mcp.client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    STATUS_PATH,
    TIMEOUT_ENV,
    DaemonClientConfig,
)
from reachy_mini_mcp.server import get_daemon_status

STATUS_URL = f"{DEFAULT_BASE_URL}{STATUS_PATH}"


def build_daemon_payload(state: str) -> dict:
    """Return a daemon status payload as the real daemon v1.9.0 sends it."""
    return {
        "type": "daemon_status",
        "robot_name": "reachy_mini",
        "state": state,
        "wireless_version": False,
        "camera_specs_name": "lite",
        "backend_status": None,
        "error": None,
        "version": "1.9.0",
    }


@respx.mock
async def test_GetStatus_WhenDaemonRunning_ReturnsReadyStatus():
    # Arrange
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=build_daemon_payload("running"))
    )

    # Act
    result = await get_daemon_status()

    # Assert
    assert result["reachable"] is True
    assert result["is_ready"] is True
    assert result["state"] == "running"
    assert result["robot_name"] == "reachy_mini"
    assert result["version"] == "1.9.0"
    assert result["error"] is None


@respx.mock
async def test_GetStatus_WhenDaemonStopped_ReturnsNotReady():
    # Arrange
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=build_daemon_payload("stopped"))
    )

    # Act
    result = await get_daemon_status()

    # Assert
    assert result["reachable"] is True
    assert result["is_ready"] is False
    assert result["state"] == "stopped"


@respx.mock
async def test_GetStatus_WhenDaemonUnreachable_ReturnsUnreachableWithError():
    # Arrange
    respx.get(STATUS_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    # Act
    result = await get_daemon_status()

    # Assert
    assert result["reachable"] is False
    assert result["is_ready"] is False
    assert result["state"] is None
    assert "not reachable" in result["error"]


def test_FromEnv_WhenNoOverrides_UsesDefaults(monkeypatch):
    # Arrange
    monkeypatch.delenv(TIMEOUT_ENV, raising=False)

    # Act
    config = DaemonClientConfig.from_env()

    # Assert
    assert config.base_url == DEFAULT_BASE_URL
    assert config.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_FromEnv_WhenTimeoutNotANumber_RaisesValueError(monkeypatch):
    # Arrange
    monkeypatch.setenv(TIMEOUT_ENV, "soon")

    # Act / Assert
    with pytest.raises(ValueError, match=TIMEOUT_ENV):
        DaemonClientConfig.from_env()
