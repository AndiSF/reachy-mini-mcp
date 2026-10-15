from __future__ import annotations
import json
import threading
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from pathlib import Path
import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from reachy_mini_mcp.config import DEFAULT_BASE_URL, Settings
from reachy_mini_mcp.daemon_gateway import MAX_SOUND_UPLOAD_BYTES
from reachy_mini_mcp.server import create_server

DAEMON_FILE = "/tmp/reachy_mini_sounds/speech-unique.wav"
AUDIO_BYTES = b"RIFF\x00\xffWAVE\r\nexample audio bytes"
OPERATIONS = [
    ("upload_sound", "/api/media/sounds/upload", "uploaded"),
    ("play_sound", "/api/media/play_sound", "accepted"),
    ("stop_sound", "/api/media/stop_sound", "accepted"),
]


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "speech-unique.wav"
    path.write_bytes(AUDIO_BYTES)
    return path


@pytest.fixture(params=OPERATIONS, ids=[item[0] for item in OPERATIONS])
def operation(request, audio_file):
    name, endpoint, field = request.param
    arguments = {
        "upload_sound": {"file_path": str(audio_file)},
        "play_sound": {"file": DAEMON_FILE},
        "stop_sound": {},
    }[name]
    return name, endpoint, field, arguments


async def call_audio(name, arguments, settings=None):
    result = await create_server(settings or Settings()).call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    return result.structured_content


def assert_one_request(route):
    assert route.call_count == 1
    # Also excludes implicit lifecycle, media, volume, and status calls.
    assert len(respx.calls) == 1


async def test_discovery_schemas_and_side_effects():
    tools = {tool.name: tool for tool in await create_server(Settings()).list_tools()}
    for name, parameter, field in [
        ("upload_sound", "file_path", "uploaded"),
        ("play_sound", "file", "accepted"),
        ("stop_sound", None, "accepted"),
    ]:
        tool = tools[name]
        assert set(tool.input_schema["properties"]) == (
            {parameter} if parameter else set()
        )
        assert tool.input_schema.get("required", []) == (
            [parameter] if parameter else []
        )
        if parameter:
            assert tool.input_schema["properties"][parameter]["type"] == "string"
        schema = tool.output_schema
        fields = {field, "error"} | ({"file"} if name == "upload_sound" else set())
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"][field]["anyOf"] == [
            {"type": "boolean"},
            {"type": "null"},
        ]
        for string_field in fields - {field}:
            assert schema["properties"][string_field]["anyOf"] == [
                {"type": "string"},
                {"type": "null"},
            ]
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True
        assert tool.annotations.idempotent_hint is False


@pytest.mark.parametrize("name", ["upload_sound", "play_sound"])
@respx.mock
async def test_missing_required_input_sends_no_request(name):
    with pytest.raises(ToolError, match="Field required"):
        await call_audio(name, {})
    assert len(respx.calls) == 0


@respx.mock
async def test_upload_sends_actual_multipart_and_preserves_source(audio_file):
    route = respx.post(f"{DEFAULT_BASE_URL}/api/media/sounds/upload").respond(
        200, json={"status": "ok", "path": DAEMON_FILE}
    )
    result = await call_audio("upload_sound", {"file_path": str(audio_file)})

    assert result == {"uploaded": True, "file": DAEMON_FILE, "error": None}
    assert_one_request(route)
    request = route.calls.last.request
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
        + request.content
    )
    assert message.get_content_type() == "multipart/form-data"
    parts = list(message.iter_parts())
    assert len(parts) == 1
    assert parts[0].get_param("name", header="content-disposition") == "file"
    assert parts[0].get_filename() == audio_file.name
    assert parts[0].get_payload(decode=True) == AUDIO_BYTES
    assert audio_file.read_bytes() == AUDIO_BYTES


@respx.mock
async def test_upload_reference_is_forwarded_to_playback(audio_file):
    respx.post(f"{DEFAULT_BASE_URL}/api/media/sounds/upload").respond(
        200, json={"status": "ok", "path": DAEMON_FILE}
    )
    play = respx.post(f"{DEFAULT_BASE_URL}/api/media/play_sound").respond(
        200, json={"status": "ok"}
    )
    upload = await call_audio("upload_sound", {"file_path": str(audio_file)})
    result = await call_audio("play_sound", {"file": upload["file"]})

    assert result == {"accepted": True, "error": None}
    assert json.loads(play.calls.last.request.content) == {"file": DAEMON_FILE}
    assert str(audio_file) != DAEMON_FILE
    assert [call.request.url.path for call in respx.calls] == [
        "/api/media/sounds/upload",
        "/api/media/play_sound",
    ]


@respx.mock
async def test_success_uses_configured_url_timeout_and_only_one_command(operation):
    name, endpoint, field, arguments = operation
    settings = Settings(base_url="https://reachy.test:9000", timeout_seconds=1.25)
    route = respx.post(f"{settings.base_url}{endpoint}").respond(
        200, json={"status": "ok", "path": DAEMON_FILE}
    )
    result = await call_audio(name, arguments, settings)

    assert result[field] is True
    assert result["error"] is None
    assert_one_request(route)
    request = route.calls.last.request
    assert set(request.extensions["timeout"].values()) == {1.25}
    assert not request.url.params
    if name == "play_sound":
        assert json.loads(request.content) == {"file": DAEMON_FILE}
        assert request.headers["content-type"] == "application/json"
    elif name == "stop_sound":
        assert request.content == b""
        assert "content-type" not in request.headers


@pytest.mark.parametrize(
    "reference", ["built-in.wav", "uploaded.wav", "/daemon/clip.wav"]
)
@respx.mock
async def test_play_supports_daemon_references(reference):
    route = respx.post(f"{DEFAULT_BASE_URL}/api/media/play_sound").respond(
        200, json={"status": "ok"}
    )
    assert (await call_audio("play_sound", {"file": reference}))["accepted"] is True
    assert json.loads(route.calls.last.request.content) == {"file": reference}
    assert_one_request(route)


@pytest.mark.parametrize("reference", ["", " \t\n"])
@respx.mock
async def test_empty_play_reference_is_rejected_locally(reference):
    result = await call_audio("play_sound", {"file": reference})
    assert result["accepted"] is False
    assert result["error"]
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    "source",
    [
        "",
        "relative.wav",
        "https://example.test/file.wav",
        "missing.wav",
        "directory.wav",
        "bad.txt",
        "large.wav",
    ],
)
@respx.mock
async def test_invalid_upload_is_rejected_before_http(source, tmp_path):
    path = tmp_path / source
    if source == "directory.wav":
        path.mkdir()
    elif source == "bad.txt":
        path.write_bytes(AUDIO_BYTES)
    elif source == "large.wav":
        with path.open("wb") as handle:
            handle.truncate(MAX_SOUND_UPLOAD_BYTES + 1)
    file_path = (
        source if source in {"", "relative.wav"} or "://" in source else str(path)
    )
    result = await call_audio("upload_sound", {"file_path": file_path})
    assert result["uploaded"] is False
    assert result["file"] is None
    assert result["error"]
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    "extension", [".WAV", ".mp3", ".OGG", ".oga", ".opus", ".flac", ".m4a", ".aac"]
)
@respx.mock
async def test_allowed_extensions(extension, tmp_path):
    path = tmp_path / f"speech{extension}"
    path.write_bytes(AUDIO_BYTES)
    respx.post(f"{DEFAULT_BASE_URL}/api/media/sounds/upload").respond(
        200, json={"status": "ok", "path": DAEMON_FILE}
    )
    assert (await call_audio("upload_sound", {"file_path": str(path)}))[
        "uploaded"
    ] is True


@pytest.mark.parametrize("failure", ["open", "read"])
@respx.mock
async def test_upload_read_errors_close_handles_and_send_no_request(
    failure, audio_file, monkeypatch
):
    handles = []
    original_open = Path.open

    class UnreadableFile:
        def __enter__(self):
            self.handle = original_open(audio_file, "rb")
            handles.append(self.handle)
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, size):
            raise OSError("sensitive file contents")

    def open_source(*args, **kwargs):
        if failure == "open":
            raise PermissionError("sensitive file contents")
        return UnreadableFile()

    monkeypatch.setattr(Path, "open", open_source)
    result = await call_audio("upload_sound", {"file_path": str(audio_file)})
    assert result == {
        "uploaded": False,
        "file": None,
        "error": "Could not read the local audio file",
    }
    if failure == "read":
        assert handles
        assert all(handle.closed for handle in handles)
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    ("status", "payload", "confirmed"),
    [
        (400, {"detail": "sensitive data"}, False),
        (401, None, False),
        (413, None, False),
        (422, None, False),
        (503, {"detail": "Backend not running"}, False),
        (503, {"detail": "Service unavailable"}, None),
        (500, {"detail": "sensitive data"}, None),
        (502, None, None),
        (307, None, None),
    ],
)
@respx.mock
async def test_http_errors_and_backend_rejection(operation, status, payload, confirmed):
    name, endpoint, field, arguments = operation
    route = respx.post(f"{DEFAULT_BASE_URL}{endpoint}").respond(status, json=payload)
    result = await call_audio(name, arguments)
    if name == "upload_sound" and status == HTTPStatus.SERVICE_UNAVAILABLE:
        confirmed = None
    assert result[field] is confirmed
    assert str(status) in result["error"]
    assert "sensitive data" not in result["error"]
    if name == "upload_sound":
        assert result["file"] is None
    if confirmed is None:
        assert "Do not automatically retry" in result["error"]
    elif status == HTTPStatus.SERVICE_UNAVAILABLE:
        assert "Backend not running" in result["error"]
    assert_one_request(route)


@pytest.mark.parametrize(
    "exception", [httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout]
)
@respx.mock
async def test_transport_failures_are_unknown_and_not_retried(operation, exception):
    name, endpoint, field, arguments = operation
    route = respx.post(f"{DEFAULT_BASE_URL}{endpoint}").mock(
        side_effect=exception("secret credential and file content")
    )
    result = await call_audio(name, arguments)
    assert result[field] is None
    assert "Do not automatically retry" in result["error"]
    assert "secret" not in result["error"]
    if name == "upload_sound":
        assert result["file"] is None
    assert_one_request(route)


@pytest.mark.parametrize(
    "body",
    [
        "not JSON",
        "[]",
        "null",
        "{}",
        '{"status": "error"}',
        '{"status": true}',
        '{"status": "OK"}',
    ],
)
@respx.mock
async def test_malformed_success_response_is_unknown(operation, body):
    name, endpoint, field, arguments = operation
    route = respx.post(f"{DEFAULT_BASE_URL}{endpoint}").respond(200, text=body)
    result = await call_audio(name, arguments)
    assert result[field] is None
    assert result["error"]
    if name == "upload_sound":
        assert result["file"] is None
    assert_one_request(route)


@pytest.mark.parametrize("path", [None, "", "  ", 42, [], {}, "bad\x00path"])
@respx.mock
async def test_invalid_upload_path_is_not_returned(audio_file, path):
    route = respx.post(f"{DEFAULT_BASE_URL}/api/media/sounds/upload").respond(
        200, json={"status": "ok", "path": path}
    )
    result = await call_audio("upload_sound", {"file_path": str(audio_file)})
    assert result["uploaded"] is None
    assert result["file"] is None
    assert result["error"]
    assert_one_request(route)


@respx.mock
async def test_upload_file_io_runs_off_event_loop_and_handle_closes(
    audio_file, monkeypatch
):
    loop_thread = threading.get_ident()
    open_original = Path.open
    handles = []

    def open_source(path, *args, **kwargs):
        assert threading.get_ident() != loop_thread
        handle = open_original(path, *args, **kwargs)
        handles.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", open_source)

    def response(request):
        assert all(handle.closed for handle in handles)
        return httpx.Response(200, json={"status": "ok", "path": DAEMON_FILE})

    respx.post(f"{DEFAULT_BASE_URL}/api/media/sounds/upload").mock(side_effect=response)
    assert (await call_audio("upload_sound", {"file_path": str(audio_file)}))[
        "uploaded"
    ]
    assert handles


@respx.mock
async def test_missing_upload_path_is_unknown(audio_file):
    respx.post(f"{DEFAULT_BASE_URL}/api/media/sounds/upload").respond(
        200, json={"status": "ok"}
    )
    result = await call_audio("upload_sound", {"file_path": str(audio_file)})
    assert result["uploaded"] is None
    assert result["file"] is None
    assert "path" in result["error"]


@respx.mock
async def test_upload_size_limit_is_inclusive(tmp_path):
    path = tmp_path / "limit.wav"
    with path.open("wb") as handle:
        handle.truncate(MAX_SOUND_UPLOAD_BYTES)
    route = respx.post(f"{DEFAULT_BASE_URL}/api/media/sounds/upload").respond(
        200, json={"status": "ok", "path": DAEMON_FILE}
    )
    result = await call_audio("upload_sound", {"file_path": str(path)})
    assert result["uploaded"] is True
    assert_one_request(route)
