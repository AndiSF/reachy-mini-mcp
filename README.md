# reachy-mini-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes the
[Reachy Mini](https://huggingface.co/docs/reachy_mini) daemon to MCP clients.

The server talks to the daemon over its
[REST API](https://huggingface.co/docs/reachy_mini/API/rest-api) only — the
Python SDK is deliberately not a dependency.

## Status

Early work in progress. Seven tools are implemented:

| Tool                | Purpose                                                    |
| ------------------- | ---------------------------------------------------------- |
| `get_daemon_status` | Report whether the daemon is reachable and the robot ready |
| `start_daemon` | Start the robot backend, optionally with the wake-up motion |
| `stop_daemon` | Stop the robot backend, optionally with the sleep motion |
| `restart_daemon` | Reinitialize the robot backend with its previous start settings |
| `upload_sound` | Upload an audio file from the MCP host to temporary daemon storage |
| `play_sound` | Request sound-file playback through the robot speaker |
| `stop_sound` | Request stopping sound-file playback |

## Requirements

- Python 3.12
- A running Reachy Mini daemon (tested against v1.9.0), reachable over HTTP
- [uv](https://docs.astral.sh/uv/) for dependency management

## Installation

```bash
git clone <repository-url> reachy-mini-mcp
cd reachy-mini-mcp
uv sync
```

## Usage

The server speaks MCP over stdio and is normally started by an MCP client
rather than by hand:

```bash
uv run reachy-mini-mcp
```

### Client configuration

The schema differs per client. Both examples below launch the same process.

OpenClaw, in `~/.openclaw/openclaw.json`:

```json
{
  "mcp": {
    "servers": {
      "reachy-mini": {
        "command": "uv",
        "args": ["run", "reachy-mini-mcp"],
        "cwd": "/absolute/path/to/reachy-mini-mcp",
        "timeout": 10
      }
    }
  }
}
```

Clients using the `mcpServers` schema, such as Claude Desktop, where the
working directory is passed to `uv` instead:

```json
{
  "mcpServers": {
    "reachy-mini": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/reachy-mini-mcp", "run", "reachy-mini-mcp"]
    }
  }
}
```

Keep any client-side timeout above `REACHY_MINI_TIMEOUT` (see below). The
server is then the one that gives up first and returns a structured error:
`is_reachable: false` for status, or an unknown outcome for commands whose
response was lost.

## Configuration

Both variables are optional.

| Variable                  | Default                 | Meaning                          |
| ------------------------- | ----------------------- | -------------------------------- |
| `REACHY_MINI_DAEMON_URL`  | `http://localhost:8000` | Base URL of the daemon REST API  |
| `REACHY_MINI_TIMEOUT`     | `5.0`                   | HTTP request timeout in seconds  |

The daemon URL must be an absolute HTTP or HTTPS origin with a host and an
optional port. Credentials, non-root paths, query strings, and fragments are
not accepted.

Set them in the `env` block of the server entry, next to `command` and `args`:

```json
{
  "reachy-mini": {
    "command": "uv",
    "args": ["--directory", "/absolute/path/to/reachy-mini-mcp", "run", "reachy-mini-mcp"],
    "env": {
      "REACHY_MINI_DAEMON_URL": "http://reachy.local:8000"
    }
  }
}
```

Exporting the variables in a shell is not enough. The client starts the server
as a child process, often with a sanitized environment that drops them.

An invalid value is reported on stderr and the server exits with code 2 rather
than starting with a setting it cannot honor. Clients write the server's
stderr to their own log file, which is where that message appears; the client
UI itself usually reports no more than a failed start.

Defaults, variable names and their parsing all live in
`src/reachy_mini_mcp/config.py`.

## Tools

### `get_daemon_status`

Takes no arguments. Returns:

| Field          | Type             | Meaning                                                                                  |
| -------------- | ---------------- | ---------------------------------------------------------------------------------------- |
| `is_reachable` | `bool`           | The daemon process answered on its HTTP port                                             |
| `is_ready`     | `bool`           | The robot backend is running and can accept commands                                     |
| `state`        | `str \| null`    | `not_initialized`, `starting`, `running`, `stopping`, `stopped` or `error`               |
| `robot_name`   | `str \| null`    | Configured robot name                                                                    |
| `version`      | `str \| null`    | Daemon version                                                                           |
| `error`        | `str \| null`    | Error reported by the daemon, or by this lookup when it failed                           |

`is_reachable` and `is_ready` are separate on purpose: the daemon process can be
up and answering while the robot backend is stopped, in which case the robot
will not move until the backend is started.

An unreachable daemon is reported as `is_reachable: false` with an `error`
message instead of raising, so the client can relay the situation to the user.

### `start_daemon`, `stop_daemon`, `restart_daemon`

These tools submit background jobs to the daemon REST API:

| Tool | Endpoint | Required arguments |
| ---- | -------- | ------------------ |
| `start_daemon` | `POST /api/daemon/start` | `wake_up: bool` |
| `stop_daemon` | `POST /api/daemon/stop` | `goto_sleep: bool` |
| `restart_daemon` | `POST /api/daemon/restart` | None |

The start and stop flags are sent as query parameters, as required by the API.
They have no defaults: the caller must explicitly choose whether to request
the wake-up or sleep motion. For example, `start_daemon(wake_up=false)` starts
the backend without requesting the wake-up motion.

Start and stop control the robot backend; the daemon's HTTP API stays available.
In daemon v1.9.0, restart stops and starts the backend using its previous
settings, including the simulation mode, serial port, scene and media setting.
It does not restart the HTTP server or the computer, and does not request the
sleep or wake-up motions. This does not guarantee that no physical movement
occurs during reinitialization. An already stopped backend stays stopped when
restart is requested; use `start_daemon` to start it.

All three tools return the same fields:

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `accepted` | `bool \| null` | `true`: job accepted; `false`: request rejected; `null`: acceptance could not be determined |
| `job_id` | `str \| null` | Background job ID returned by the daemon, when confirmed |
| `error` | `str \| null` | Request error or explanation of the uncertain outcome |

An accepted job has **not necessarily completed or succeeded**. Use
`get_daemon_status` to inspect the backend state afterward: start normally leads
to `running`, stop to `stopped`, and restart returns an active backend to
`running`. The backend can also report `error`. A single status snapshot,
especially `running` immediately after a restart request, does not prove that
the submitted job has completed. These tools do not wait for job completion.

HTTP 409 means the daemon is busy and rejected the command. Transport failures,
timeouts, server errors or invalid success responses leave acceptance unknown:
the daemon may already have started the operation. Commands are never
automatically retried. Check the state before deciding whether to retry.

### Audio output: `upload_sound`, `play_sound`, `stop_sound`

Speech synthesis stays outside this MCP server. An agent uses its own TTS
component to generate an audio file on the **machine running the MCP server**,
uploads it, and requests playback through Reachy Mini's speaker:

```text
External TTS -> MCP-host audio file -> upload_sound -> play_sound -> robot speaker
```

| Tool | Endpoint | Required arguments |
| ---- | -------- | ------------------ |
| `upload_sound` | `POST /api/media/sounds/upload` | `file_path: str`, an absolute local path on the MCP host |
| `play_sound` | `POST /api/media/play_sound` | `file: str`, a nonempty daemon-side reference |
| `stop_sound` | `POST /api/media/stop_sound` | None |

`upload_sound` reads an existing regular file without modifying or deleting it.
A URL, base64 payload, browser attachment identifier, or a path on a remote
client's computer is not an upload source. Supported extensions are `.wav`,
`.mp3`, `.ogg`, `.oga`, `.opus`, `.flac`, `.m4a`, and `.aac`, case-insensitively.
Files larger than 25 MiB are rejected locally before any HTTP request. File
reads run outside the async event loop and are bounded to the upload limit.
The file bytes are sent as multipart field `file`, using only the basename;
the daemon validates the actual audio content.

The upload result is:

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `uploaded` | `bool \| null` | `true`: upload confirmed; `false`: local validation failed or the daemon rejected it; `null`: upload outcome unknown |
| `file` | `str \| null` | Daemon-side path, returned only on confirmed success, for use with `play_sound` |
| `error` | `str \| null` | Failure or uncertain-outcome explanation |

The daemon stores uploads temporarily (v1.9.0 uses `/tmp/reachy_mini_sounds`).
**An upload with the same basename can overwrite an earlier upload.** Use unique
filenames for generated speech. This increment does not list, delete, or clean
up uploaded files; operators must manage temporary storage separately.

Example MCP tool arguments and structured results (paths are illustrative):

```text
upload_sound({"file_path": "/srv/tts/speech-a71f.wav"})
-> {"uploaded": true, "file": "/tmp/reachy_mini_sounds/speech-a71f.wav", "error": null}

play_sound({"file": "/tmp/reachy_mini_sounds/speech-a71f.wav"})
-> {"accepted": true, "error": null}

stop_sound({})
-> {"accepted": true, "error": null}
```

Prefer the `file` returned by `upload_sound` for playback. The daemon also
accepts its own local paths, built-in sound names, and uploaded filenames.
These refer to the **daemon's filesystem**, which can differ from the MCP host's
filesystem. `play_sound` sends JSON `{"file": "..."}`; it does not upload a file.
`stop_sound` sends a POST with no request body.

Playback and stopping return:

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `accepted` | `bool \| null` | `true`: API accepted the request; `false`: validation failed or request rejected; `null`: acceptance unknown |
| `error` | `str \| null` | Failure or uncertain-outcome explanation |

`accepted: true` confirms API acceptance only. It does **not** prove audible
playback, successful interruption, or completion. Audio tools do not return
background job IDs or expose a playback-completion endpoint. `get_daemon_status`
can check backend readiness, but cannot confirm playback completion.

Both `play_sound` and `stop_sound` require a ready robot backend. The documented
HTTP 503 `Backend not running` response is a rejection; these tools never start
the backend automatically. `stop_sound` stops sound-file playback; it does not
stop the backend or clear every streaming-audio queue. Audio tools do not change
volume or enable motion, tracking, or wobbling.

HTTP 4xx rejections are failures and include the status code. Timeouts,
connection errors, ambiguous server failures, and malformed success responses
leave the outcome unknown (`null`): the effect may already have occurred.
There are no automatic retries; retrying playback could speak twice. All three
tools are annotated as side-effecting and unsuitable for safe automatic replay.

### Manual audio acceptance checklist

Run these steps separately with an operator present; automated tests do not
perform hardware actions:

1. With the robot ready, place a short externally generated WAV on the MCP host.
2. Call `upload_sound` and capture its confirmed daemon-side `file` reference.
3. Call `play_sound` with that reference and have the operator confirm sound
   comes from the robot speaker, not the computer speaker.
4. Upload and play a longer clip; verify `stop_sound` interrupts it.
5. With the backend stopped, verify `play_sound` returns a clear
   `Backend not running` error and leaves the backend stopped.

## Development

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

The unit tests mock the daemon's HTTP API, so no robot or running daemon is needed.
Audio tests use temporary files and mocked HTTP; they do not validate physical
speaker output or use an external TTS service.

### Integration test with MuJoCo

The integration test is skipped by default. It uses the actual MCP stdio protocol
to check `get_daemon_status` against a running MuJoCo simulator, and verifies that
the daemon uses simulation rather than the mockup backend. It does not start or
stop the simulator, and an unavailable or unready simulator fails the opted-in test.

First, in the separate `reachy-mini-sim` checkout, install its dependencies with
`uv sync` and start the daemon:

```bash
uv run reachy-mini-daemon --sim --headless --no-media
```

On macOS, use MuJoCo's launcher instead:

```bash
uv run mjpython -m reachy_mini.daemon.app.main --sim --headless --no-media
```

Wait until the simulator is running. Then, in `reachy-mini-mcp`, run only the
integration test or include it with the unit tests:

```bash
uv run pytest --run-integration -m integration
uv run pytest --run-integration
```

The default daemon URL is `http://localhost:8000`. To use another host or port,
set `REACHY_MINI_DAEMON_URL` in your shell before running pytest. The test passes
this setting and `REACHY_MINI_TIMEOUT` to the MCP subprocess explicitly.
It launches the server with pytest's Python interpreter, so the test works on
Linux, Windows, and macOS without platform-specific executable paths.

## Layout

```
src/reachy_mini_mcp/
├── config.py          # environment variable parsing and validation
├── daemon_gateway.py  # gateway to the daemon REST API; knows nothing about MCP
├── server.py          # MCP server factory, tool definitions and result mapping
└── __main__.py        # stdio entrypoint
```

## License

MIT
