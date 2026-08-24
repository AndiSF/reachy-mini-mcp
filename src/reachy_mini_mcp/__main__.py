from __future__ import annotations
import sys
from .config import SERVER_NAME, Settings
from .server import create_server

CONFIG_ERROR_EXIT_CODE = 2


def main() -> None:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        # stdout is reserved for MCP protocol messages.
        print(f"{SERVER_NAME}: configuration error: {exc}", file=sys.stderr)
        print(
            f"{SERVER_NAME}: check the env block of this server "
            "in your MCP client configuration.",
            file=sys.stderr,
        )
        raise SystemExit(CONFIG_ERROR_EXIT_CODE) from exc

    mcp = create_server(settings)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
