"""
Example MCP server using the :class:`MCPHandler` extensibility API.

Run:
    cp .env.example .env
    # edit .env: set MCP_PORT, MCP_API_KEY, OAUTH_ENABLED, etc.
    python example/main.py

Then test:
    curl -X POST http://localhost:8000/mcp \\
      -H 'Content-Type: application/json' \\
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

    # Service discovery document:
    curl http://localhost:8000/.well-known/mcp.json
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp_service import MCPHandler, run


class ExampleHandler(MCPHandler):
    """Minimal MCP server — exposes ``echo`` and ``ping`` tools."""

    name = "example-mcp-server"
    version = "0.1.0"
    description = "Echo + ping example server for mcp-service"
    protocol_version = "2024-11-05"

    @MCPHandler.register_tool(
        name="echo",
        description="Echo back the input message",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    def echo(self, args: dict) -> dict:
        return {"content": [{"type": "text",
                             "text": args.get("message", "")}]}

    @MCPHandler.register_tool(
        name="ping",
        description="Returns pong",
        input_schema={"type": "object", "properties": {}},
    )
    def ping(self, args: dict) -> dict:
        return {"content": [{"type": "text", "text": "pong"}]}

    @MCPHandler.register_method("whoami")
    def whoami(self, request: dict) -> dict:
        """Return the authenticated user_id (set by the server in _meta)."""
        user_id = (request.get("_meta") or {}).get("user_id", "anonymous")
        return self._ok(request, {"user_id": user_id})


if __name__ == "__main__":
    run(ExampleHandler(), title="Example MCP Server")