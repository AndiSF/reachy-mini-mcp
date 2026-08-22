"""Tests for the daemon status lookup, with the daemon's HTTP API mocked."""

from __future__ import annotations

import httpx
import pytest
import respx

from reachy_mini_mcp.__main__ import CONFIG_ERROR_EXIT_CODE, main
from reachy_mini_mcp.config import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_ENV,
    Settings,
)
from reachy_mini_mcp.daemon import STATUS_PATH
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
    settings = Settings.from_env()

    # Assert
    assert settings.base_url == DEFAULT_BASE_URL
    assert settings.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_FromEnv_WhenTimeoutNotANumber_RaisesValueError(monkeypatch):
    # Arrange
    monkeypatch.setenv(TIMEOUT_ENV, "soon")

    # Act / Assert
    with pytest.raises(ValueError, match=TIMEOUT_ENV):
        Settings.from_env()


def test_Main_WhenTimeoutInvalid_ExitsWithMessageOnStderr(monkeypatch, capsys):
    # Arrange
    monkeypatch.setenv(TIMEOUT_ENV, "soon")

    # Act
    with pytest.raises(SystemExit) as exit_info:
        main()

    # Assert
    assert exit_info.value.code == CONFIG_ERROR_EXIT_CODE
    captured = capsys.readouterr()
    assert TIMEOUT_ENV in captured.err
    assert "soon" in captured.err
    assert captured.out == ""
