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

    app = FastAPI(title=title, version="0.1.0",
                  description="MCP HTTP server with OAuth 2.1")

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

    @app.get("/health")
    async def health():
        return {"status": "ok", "server": title}

    # ── deep health ───────────────────────────────────────────────────────────

    @app.get("/healthz")
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

    @app.post("/oauth")
    async def mcp_oauth(raw: Request, token: RequiredOAuthToken):
        """MCP endpoint requiring a valid OAuth bearer token."""
        return await _dispatch(raw, handler, token.user_id)

    # ── Main MCP endpoint (/) — auth optional or enforced by MCP_REQUIRE_AUTH ─

    @app.post("/mcp")
    @app.post("/")
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

    @app.get("/mcp")
    @app.get("/")
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
    """CLI entry point — requires MCP_HANDLER env var pointing to a dotted import path."""
    import importlib
    handler_path = os.getenv("MCP_HANDLER")
    if not handler_path:
        print("Set MCP_HANDLER=module.path:function_name")
        raise SystemExit(1)
    module_path, _, fn_name = handler_path.partition(":")
    module = importlib.import_module(module_path)
    handler = getattr(module, fn_name)
    run(handler)
