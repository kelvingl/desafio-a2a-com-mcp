"""Entrypoint: sobe o servidor MCP em Streamable HTTP."""

from __future__ import annotations

import os

from servidor_mcp.app import app


def main() -> None:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "7301"))
    app.run("streamable-http", host=host, port=port, streamable_http_path="/mcp")


if __name__ == "__main__":
    main()
