"""
Minimal example: a working MCP server using mcp-service.

Run:
    cp .env.example .env
    # edit .env: set MCP_PORT, MCP_API_KEY, OAUTH_ENABLED, etc.
    python example/main.py

Then test:
    curl -X POST http://localhost:5300/mcp \
      -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
"""

import sys
import os

# allow running directly from repo root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp_service import run

TOOLS = {
    "echo": {
        "description": "Echo back the input",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    "ping": {
        "description": "Returns pong",
        "inputSchema": {"type": "object", "properties": {}},
    },
}


def handler(request: dict) -> dict | None:
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    # ── MCP protocol methods ─────────────────────────────────────────────────
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "example-mcp-server", "version": "0.1.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # 204 notification, no response

    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": [{"name": k, **v} for k, v in TOOLS.items()]},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if tool_name == "echo":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": args.get("message", "")}]},
            }

        if tool_name == "ping":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": "pong"}]},
            }

    # Unknown method
    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


if __name__ == "__main__":
    run(handler, title="Example MCP Server")
