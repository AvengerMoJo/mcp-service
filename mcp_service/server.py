"""
MCP Service — FastAPI server factory.

Usage:
    from mcp_service.server import create_app, run

    def my_handler(request: dict) -> dict | None:
        # your JSON-RPC logic here
        ...

    app = create_app(my_handler)          # for ASGI mounting
    run(my_handler)                       # blocking uvicorn entry point
    run(my_handler, port=5300)            # custom port

The handler receives a raw JSON-RPC dict and returns a response dict (or None
for notifications). All OAuth/auth plumbing is handled by the server.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Optional

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from mcp_service.config import get_config
from mcp_service.errors import (
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    build_www_authenticate,
    install_error_handlers,
    jsonrpc_envelope,
    jsonrpc_error,
    oauth_error_response,
)
from mcp_service.oauth.middleware import ValidatedOAuthToken, RequiredOAuthToken
from mcp_service.oauth import endpoints as oauth_endpoints
from mcp_service.oauth.storage import (
    get_client_registration_store,
    get_token_store,
)

__version__ = "0.1.0"

Handler = Callable[[dict], Optional[dict]]

_log = logging.getLogger(__name__)


def create_app(handler: Handler, title: str = "MCP Service") -> FastAPI:
    """
    Create a FastAPI application wrapping *handler*.

    handler(request: dict) -> dict | None
        Receives a raw JSON-RPC 2.0 request dict.
        Returns a response dict, or None for notifications (204).
    """
    cfg = get_config()

    app = FastAPI(
        title=title,
        version=__version__,
        description=(
            "Model Context Protocol HTTP server with built-in OAuth 2.1 "
            "Authorization Server (RFC 8414, 7636, 7591, 6749). "
            "Mount this under any ASGI server, or call `run()` to start the "
            "bundled uvicorn worker.\n\n"
            "**Quickstart:**\n"
            "```bash\n"
            "curl -X POST http://localhost:8000/mcp \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'\n"
            "```\n\n"
            "**OAuth flow:** see [ERRORS.md](https://github.com/AvengerMoJo/mcp-service/blob/main/docs/ERRORS.md) "
            "for the full error catalog."
        ),
        contact={"name": "AvengerMoJo", "url": "https://github.com/AvengerMoJo/mcp-service"},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        openapi_tags=[
            {"name": "mcp", "description": "JSON-RPC 2.0 endpoints — POST MCP requests here."},
            {"name": "oauth", "description": "OAuth 2.1 Authorization Server endpoints."},
            {"name": "health", "description": "Liveness / readiness probes."},
        ],
        swagger_ui_init_oauth={
            "clientId": "swagger-ui-preview-client",
            "usePkceWithAuthorizationCodeGrant": True,
        },
        servers=[
            {"url": "http://localhost:8000", "description": "Local development"},
        ],
    )

    # Carry the version through to the OpenAPI schema so external API clients
    # see exactly which version they are talking to.
    app.openapi_version = "3.1.0"

    # Trust X-Forwarded-Proto/Host from Cloudflare or any reverse proxy
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    # CORS — allow all origins so claude.ai and Claude Code can connect
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "Authorization", "mcp-session-id"],
    )

    # Standardize uncaught errors → OAuth / RFC 7807 envelopes
    install_error_handlers(app)

    # Mount OAuth AS endpoints (well-known + /oauth/*)
    if cfg.oauth.enabled and cfg.oauth.enable_authorization_server:
        app.include_router(oauth_endpoints.router)
        _log.info("OAuth 2.1 AS endpoints mounted")

    # ── health ────────────────────────────────────────────────────────────────

    @app.get(
        "/health",
        summary="Liveness probe",
        description="Returns 200 if the process is running. Use `/healthz` for a deep check.",
        tags=["health"],
        responses={
            200: {
                "description": "Process is up",
                "content": {"application/json": {"example": {"status": "ok", "server": title}}},
            },
        },
    )
    async def health():
        return {"status": "ok", "server": title}

    # ── deep health ───────────────────────────────────────────────────────────

    @app.get(
        "/healthz",
        summary="Readiness probe (deep)",
        description=(
            "Returns 200 with per-check details when all checks pass; 503 if any "
            "critical check fails (e.g. storage directory not writable)."
        ),
        tags=["health"],
        responses={
            200: {"description": "All checks passed"},
            503: {
                "description": "One or more checks failed",
                "content": {"application/json": {"example": {
                    "status": "degraded",
                    "server": title,
                    "checks": {"token_store": {"status": "error", "detail": "permission denied"}},
                }}},
            },
        },
    )
    async def healthz():
        """Deep health check — includes token store and client store status.

        Returns 200 with per-check details when all checks pass; 503 if any
        critical check fails (e.g. storage directory not writable)."""
        cfg = get_config()
        checks: dict = {"server": "ok"}
        critical_ok = True

        if cfg.oauth.enabled:
            try:
                store = get_token_store()
                checks["token_store"] = {
                    "status": "ok",
                    "path": str(store._path),
                    "writable": store._path.parent.exists(),
                }
            except Exception as e:
                checks["token_store"] = {"status": "error", "detail": str(e)}
                critical_ok = False
            try:
                cstore = get_client_registration_store()
                checks["client_store"] = {
                    "status": "ok",
                    "path": str(cstore._path),
                }
            except Exception as e:
                checks["client_store"] = {"status": "error", "detail": str(e)}
                critical_ok = False
        else:
            checks["oauth"] = {"status": "disabled"}

        body = {
            "status": "ok" if critical_ok else "degraded",
            "server": title,
            "checks": checks,
        }
        return _json_response(body, status_code=200 if critical_ok else 503)

    # ── OAuth-gated endpoint (/oauth POST) ────────────────────────────────────

    @app.post(
        "/oauth",
        summary="MCP endpoint (OAuth required)",
        description=(
            "Same JSON-RPC 2.0 contract as `/mcp`, but always requires a "
            "valid OAuth Bearer token. Returns 401 with a `WWW-Authenticate` "
            "challenge on missing/invalid tokens."
        ),
        tags=["mcp"],
        responses={
            200: {
                "description": "JSON-RPC 2.0 response (or 204 for notifications)",
                "content": {"application/json": {"example": {
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"tools": [{"name": "ping"}]},
                }}},
            },
            204: {"description": "Notification acknowledged (no body)"},
            401: {
                "description": "Bearer token missing or invalid",
                "headers": {"WWW-Authenticate": {"schema": {"type": "string"}}},
                "content": {"application/json": {"example": {
                    "error": "invalid_token",
                    "error_description": "Token has expired",
                }}},
            },
        },
    )
    async def mcp_oauth(raw: Request, token: RequiredOAuthToken):
        """MCP endpoint requiring a valid OAuth bearer token."""
        return await _dispatch(raw, handler, token.user_id)

    # ── Main MCP endpoint (/) — auth optional or enforced by MCP_REQUIRE_AUTH ─

    @app.post(
        "/mcp",
        summary="MCP endpoint (JSON-RPC 2.0)",
        description=(
            "Accepts JSON-RPC 2.0 requests (`initialize`, `tools/list`, "
            "`tools/call`, `notifications/initialized`, ...). Auth is "
            "optional by default; set `MCP_REQUIRE_AUTH=true` to enforce "
            "either a Bearer token or the `MCP-API-Key` header."
        ),
        tags=["mcp"],
        responses={
            200: {
                "description": "JSON-RPC 2.0 response",
                "content": {"application/json": {"examples": {
                    "result": {"summary": "Successful response",
                               "value": {"jsonrpc": "2.0", "id": 1,
                                         "result": {"tools": []}}},
                    "error": {"summary": "Handler-issued error",
                              "value": {"jsonrpc": "2.0", "id": 1,
                                        "error": {"code": -32601,
                                                  "message": "Method not found"}}},
                }}},
            },
            204: {"description": "Notification acknowledged (no body)"},
            400: {
                "description": "Parse / invalid-request error",
                "content": {"application/json": {"example": {
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }}},
            },
            401: {
                "description": "Bearer token missing or invalid",
                "headers": {"WWW-Authenticate": {"schema": {"type": "string"}}},
                "content": {"application/json": {"example": {
                    "error": "invalid_token",
                    "error_description": "Token has expired",
                }}},
            },
            500: {
                "description": "Handler raised an unhandled exception",
                "content": {"application/json": {"example": {
                    "jsonrpc": "2.0", "id": 1,
                    "error": {"code": -32603, "message": "Internal error",
                              "data": "Traceback ..."},
                }}},
            },
        },
    )
    @app.post("/", include_in_schema=False)
    async def mcp_main(
        raw: Request,
        token: ValidatedOAuthToken = None,
        mcp_api_key: Optional[str] = Header(None, alias="MCP-API-Key"),
        authorization: Optional[str] = Header(None),
    ):
        if cfg.require_auth:
            has_oauth = token is not None
            has_key = mcp_api_key and mcp_api_key == cfg.api_key
            if not has_oauth and not has_key:
                return oauth_error_response(
                    "invalid_token",
                    "Authentication required: Bearer token or MCP-API-Key",
                    audience=cfg.oauth.audience or "mcp_service",
                )
        user_id = token.user_id if token else None
        return await _dispatch(raw, handler, user_id)

    # ── SSE GET (keep-alive for MCP spec) ─────────────────────────────────────

    @app.get(
        "/mcp",
        summary="MCP transport info (HTTP hint)",
        description=(
            "GET returns the server's transport metadata. POST is the real "
            "JSON-RPC endpoint (see above). SSE streams are not currently "
            "supported — this server speaks HTTP request/response only."
        ),
        tags=["mcp"],
        responses={
            200: {"description": "Transport info",
                  "content": {"application/json": {"example": {
                      "transport": "http", "note": "POST to this endpoint",
                  }}}},
        },
    )
    @app.get("/", include_in_schema=False)
    async def mcp_sse_info():
        """Minimal SSE endpoint — tells clients this server uses HTTP transport."""
        return JSONResponse({"transport": "http", "note": "POST to this endpoint"})

    return app


def _json_response(data: dict, status_code: int = 200) -> JSONResponse:
    """JSONResponse with explicit UTF-8 encoding to avoid Content-Length mismatch."""
    from starlette.responses import Response
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(content=body, status_code=status_code,
                    media_type="application/json; charset=utf-8")


async def _dispatch(raw: Request, handler: Handler, user_id: Optional[str]) -> JSONResponse:
    try:
        body = await raw.json()
    except Exception:
        return _json_response(jsonrpc_envelope(None, error=jsonrpc_error(
            JSONRPC_PARSE_ERROR, "Parse error")), 400)

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or "method" not in body:
        req_id = body.get("id") if isinstance(body, dict) else None
        return _json_response(jsonrpc_envelope(req_id, error=jsonrpc_error(
            JSONRPC_INVALID_REQUEST, "Invalid Request")), 400)

    try:
        resp = handler(body)
    except Exception as e:
        _log.exception("handler error")
        return _json_response(jsonrpc_envelope(body.get("id"), error=jsonrpc_error(
            JSONRPC_INTERNAL_ERROR, "Internal error", data=str(e))), 500)

    if resp is None:
        from starlette.responses import Response
        return Response(status_code=204)
    return _json_response(resp)


def run(handler: Handler, host: str = "0.0.0.0", port: Optional[int] = None,
        title: str = "MCP Service") -> None:
    """Start the uvicorn server (blocking)."""
    import uvicorn
    cfg = get_config()
    p = port or cfg.port
    app = create_app(handler, title=title)
    _log.info("Starting %s on %s:%s", title, host, p)
    uvicorn.run(app, host=host, port=p, log_level="info")


def main() -> None:
    """CLI entry point.

    Resolution order for the handler:
      1. ``$MCP_HANDLER`` env var (``module.path:function_name``).
      2. Built-in ``example.main:handler`` (so `docker run mcp-service` works
         without extra config — useful for smoke-testing).
    """
    import importlib
    handler_path = os.getenv("MCP_HANDLER") or "example.main:handler"
    module_path, _, fn_name = handler_path.partition(":")
    if not fn_name:
        raise SystemExit(
            f"MCP_HANDLER={handler_path!r} must be of the form 'module.path:function'"
        )
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise SystemExit(
            f"Could not import handler module {module_path!r}: {e}. "
            "Set MCP_HANDLER to a module on PYTHONPATH."
        ) from e
    handler = getattr(module, fn_name, None)
    if handler is None:
        raise SystemExit(
            f"Module {module_path!r} has no attribute {fn_name!r}"
        )
    run(handler)
