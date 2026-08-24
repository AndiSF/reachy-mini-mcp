# reachy-mini-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes the
[Reachy Mini](https://huggingface.co/docs/reachy_mini) daemon to MCP clients.

The server talks to the daemon over its
[REST API](https://huggingface.co/docs/reachy_mini/API/rest-api) only — the
Python SDK is deliberately not a dependency.

## Status

Early work in progress. One tool is implemented:

| Tool                | Purpose                                                    |
| ------------------- | ---------------------------------------------------------- |
| `get_daemon_status` | Report whether the daemon is reachable and the robot ready |

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
server is then the one that gives up first, so an unresponsive daemon comes
back as a `reachable: false` result the client can explain, rather than as a
timeout the client cannot attribute.

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

| Field        | Type             | Meaning                                                                                  |
| ------------ | ---------------- | ---------------------------------------------------------------------------------------- |
| `reachable`  | `bool`           | The daemon process answered on its HTTP port                                             |
| `is_ready`   | `bool`           | The robot backend is running and can accept commands                                     |
| `state`      | `str \| null`    | `not_initialized`, `starting`, `running`, `stopping`, `stopped` or `error`               |
| `robot_name` | `str \| null`    | Configured robot name                                                                    |
| `version`    | `str \| null`    | Daemon version                                                                           |
| `error`      | `str \| null`    | Error reported by the daemon, or by this lookup when it failed                           |

`reachable` and `is_ready` are separate on purpose: the daemon process can be
up and answering while the robot backend is stopped, in which case the robot
will not move until the backend is started.

An unreachable daemon is reported as `reachable: false` with an `error` message
instead of raising, so the client can relay the situation to the user.

## Development

```bash
uv sync          # install dependencies, including the dev group
uv run pytest    # run the test suite
```

The tests mock the daemon's HTTP API, so no robot or running daemon is needed.

## Layout

```
src/reachy_mini_mcp/
├── config.py     # environment variable parsing and validation
├── daemon.py     # async REST client for the daemon; knows nothing about MCP
├── server.py     # MCP server factory, tool definitions and result mapping
└── __main__.py   # stdio entrypoint
```

## License

MIT
