"""Vercel ASGI entrypoint for the fina-trade Streamable HTTP MCP server."""
from __future__ import annotations

from typing import Any

from fina_trade.mcp_server import app as _mcp_app


async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """Route Vercel's /api and /mcp paths to FastMCP's /mcp endpoint."""
    if scope.get("type") == "http":
        path = scope.get("path", "")
        if path in ("/api", "/api/", "/mcp", "/mcp/"):
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
        elif path.startswith("/api/"):
            suffix = path.removeprefix("/api")
            scope = {**scope, "path": "/mcp" + suffix, "raw_path": ("/mcp" + suffix).encode()}
    await _mcp_app(scope, receive, send)


__all__ = ["app"]
