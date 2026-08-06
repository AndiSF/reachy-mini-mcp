"""Entrypoint running the MCP server over stdio."""

from __future__ import annotations

import sys

from .config import SERVER_NAME, Settings
from .server import configure, mcp

# Exit code used when the server refuses to start because of bad configuration.
CONFIG_ERROR_EXIT_CODE = 2


def main() -> None:
    """Run the server, communicating with the MCP client over stdin/stdout.

    Configuration is resolved first: stdout carries the MCP protocol, so a bad
    setting is reported on stderr -- where MCP clients collect server logs --
    and the process exits instead of serving tools that could never work.
    """
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"{SERVER_NAME}: configuration error: {exc}", file=sys.stderr)
        print(
            f"{SERVER_NAME}: check the env block of this server "
            "in your MCP client configuration.",
            file=sys.stderr,
        )
        raise SystemExit(CONFIG_ERROR_EXIT_CODE) from exc

    configure(settings)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
