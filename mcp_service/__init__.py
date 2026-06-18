"""mcp-service — Reusable MCP HTTP server with OAuth 2.1."""

from mcp_service.handler import MCPHandler, as_handler
from mcp_service.server import create_app, run

__all__ = ["create_app", "run", "MCPHandler", "as_handler"]
__version__ = "0.1.0"