from __future__ import annotations
import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from reachy_mini_mcp.config import DEFAULT_BASE_URL, Settings
from reachy_mini_mcp.server import create_server

JOB_ID = "9122fb7f-07c7-4af7-9eee-a0565711df6e"
COMMANDS = [
    pytest.param(
        ("start_daemon", "/api/daemon/start", {"wake_up": True}),
        id="start-with-wake-up",
    ),
    pytest.param(
        ("start_daemon", "/api/daemon/start", {"wake_up": False}),
        id="start-without-wake-up",
    ),
    pytest.param(
        ("stop_daemon", "/api/daemon/stop", {"goto_sleep": True}), id="stop-with-sleep"
    ),
    pytest.param(
        ("stop_daemon", "/api/daemon/stop", {"goto_sleep": False}),
        id="stop-without-sleep",
    ),
    pytest.param(("restart_daemon", "/api/daemon/restart", {}), id="restart"),
]


@pytest.fixture(params=COMMANDS)
def command(request):
    return request.param


async def call_command(command, settings=None):
    name, _, arguments = command
    result = await create_server(settings or Settings()).call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    return result.structured_content


@respx.mock
async def test_command_posts_query_parameters_and_returns_job_acceptance(command):
    _, path, arguments = command
    route = respx.post(f"{DEFAULT_BASE_URL}{path}").respond(
        200, json={"job_id": JOB_ID}
    )

    result = await call_command(command)

    assert result == {"accepted": True, "job_id": JOB_ID, "error": None}
    assert route.call_count == 1
    request = route.calls.last.request
    assert dict(request.url.params) == {
        key: str(value).lower() for key, value in arguments.items()
    }
    assert request.content == b""
    # Acceptance must not trigger a second command or poll for completion.
    assert len(respx.calls) == 1


@respx.mock
async def test_commands_honor_custom_url_and_timeout(command):
    settings = Settings(base_url="http://reachy.test:9000", timeout_seconds=1.5)
    _, path, _ = command
    route = respx.post(f"{settings.base_url}{path}").respond(
        200, json={"job_id": JOB_ID}
    )

    await call_command(command, settings)

    assert route.call_count == 1
    assert set(route.calls.last.request.extensions["timeout"].values()) == {1.5}


@respx.mock
async def test_busy_daemon_reports_rejection_without_retrying(command):
    _, path, _ = command
    route = respx.post(f"{DEFAULT_BASE_URL}{path}").respond(
        409, json={"detail": "Daemon is busy."}
    )

    result = await call_command(command)

    assert result["accepted"] is False
    assert result["job_id"] is None
    assert "busy" in result["error"]
    assert "409" in result["error"]
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("status_code", "accepted"), [(307, None), (422, False), (500, None)]
)
@respx.mock
async def test_http_errors_do_not_claim_acceptance_or_retry(
    command, status_code, accepted
):
    _, path, _ = command
    route = respx.post(f"{DEFAULT_BASE_URL}{path}").respond(status_code)

    result = await call_command(command)

    assert result["accepted"] is accepted
    assert result["job_id"] is None
    assert str(status_code) in result["error"]
    if accepted is None:
        assert "get_daemon_status" in result["error"]
    assert route.call_count == 1


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
@respx.mock
async def test_transport_failure_reports_unknown_outcome_without_retry(
    command, error_type
):
    _, path, _ = command
    route = respx.post(f"{DEFAULT_BASE_URL}{path}").mock(
        side_effect=error_type("connection failed")
    )

    result = await call_command(command)

    assert result["accepted"] is None
    assert result["job_id"] is None
    assert "get_daemon_status" in result["error"]
    assert route.call_count == 1


@pytest.mark.parametrize(
    "payload", [{}, {"job_id": None}, {"job_id": " "}, {"job_id": 7}, []]
)
@respx.mock
async def test_invalid_job_response_reports_unknown_outcome(command, payload):
    _, path, _ = command
    route = respx.post(f"{DEFAULT_BASE_URL}{path}").respond(200, json=payload)

    result = await call_command(command)

    assert result["accepted"] is None
    assert result["job_id"] is None
    assert "get_daemon_status" in result["error"]
    assert route.call_count == 1


@respx.mock
async def test_non_json_response_reports_unknown_outcome(command):
    _, path, _ = command
    route = respx.post(f"{DEFAULT_BASE_URL}{path}").respond(200, text="not JSON")

    result = await call_command(command)

    assert result["accepted"] is None
    assert result["job_id"] is None
    assert "JSON" in result["error"]
    assert route.call_count == 1


@pytest.mark.parametrize("name", ["start_daemon", "stop_daemon"])
@respx.mock
async def test_motion_choice_is_required_before_sending_request(name):
    server = create_server(Settings())

    with pytest.raises(ToolError, match="Field required"):
        await server.call_tool(name, {})

    assert len(respx.calls) == 0


async def test_command_schemas_describe_inputs_results_and_side_effects():
    tools = {tool.name: tool for tool in await create_server(Settings()).list_tools()}

    for name, parameter in [
        ("start_daemon", "wake_up"),
        ("stop_daemon", "goto_sleep"),
        ("restart_daemon", None),
    ]:
        tool = tools[name]
        assert set(tool.input_schema["properties"]) == (
            {parameter} if parameter else set()
        )
        if parameter:
            assert tool.input_schema["required"] == [parameter]
            assert tool.input_schema["properties"][parameter]["type"] == "boolean"
        assert tool.output_schema is not None
        assert set(tool.output_schema["properties"]) == {"accepted", "job_id", "error"}
        assert set(tool.output_schema["required"]) == {"accepted", "job_id", "error"}
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True
        assert tool.annotations.idempotent_hint is False
