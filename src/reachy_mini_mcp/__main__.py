"""Entrypoint running the MCP server over stdio."""

from .server import mcp


def main() -> None:
    """Run the server, communicating with the MCP client over stdin/stdout."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
