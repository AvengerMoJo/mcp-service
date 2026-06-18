"""
Standardized error responses for mcp-service.

Two parallel contracts share this module:

1. **OAuth / HTTP errors** — RFC 6749 §5.2 + RFC 6750 §3.1 envelopes:
       {"error": "...", "error_description": "...", "error_uri": "...", "state": "..."}
   Returned on `/oauth/*` endpoints and on `401`/`403` responses elsewhere.
   Always carry a `WWW-Authenticate: Bearer ...` header on 401.

2. **JSON-RPC 2.0 errors** — wrapped inside the MCP dispatch:
       {"jsonrpc": "2.0", "id": ..., "error": {"code": ..., "message": ..., "data": ...}}

Use the helpers below rather than constructing dicts by hand so the contracts
stay consistent across the codebase.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

# ─── OAuth error catalog (RFC 6749 §5.2 + RFC 6750) ───────────────────────────

OAUTH_ERROR_CODES = {
    "invalid_request":           400,
    "invalid_client":            401,
    "invalid_grant":             400,
    "invalid_token":             401,
    "invalid_scope":             400,
    "unauthorized_client":       403,
    "unsupported_grant_type":    400,
    "unsupported_response_type": 400,
    "access_denied":             400,
    "server_error":              500,
    "temporarily_unavailable":   503,
    "insufficient_scope":        403,
    "oauth_disabled":            401,
}


class OAuthErrorBody(BaseModel):
    """RFC 6749 §5.2 error envelope."""

    error: str
    error_description: Optional[str] = None
    error_uri: Optional[str] = None
    state: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


def oauth_error(
    code: str,
    description: Optional[str] = None,
    *,
    state: Optional[str] = None,
    error_uri: Optional[str] = None,
) -> dict:
    """Build an RFC 6749 §5.2 error body dict for a known OAuth error code."""
    if code not in OAUTH_ERROR_CODES:
        raise ValueError(f"unknown OAuth error code: {code!r}")
    body = OAuthErrorBody(
        error=code,
        error_description=description,
        error_uri=error_uri,
        state=state,
    ).to_dict()
    return body


# ─── JSON-RPC 2.0 error catalog ───────────────────────────────────────────────

# Standard JSON-RPC 2.0 error codes (https://www.jsonrpc.org/specification)
JSONRPC_PARSE_ERROR      = -32700
JSONRPC_INVALID_REQUEST  = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS   = -32602
JSONRPC_INTERNAL_ERROR   = -32603

# MCP-specific reserved range (-32000 to -32099) — server-defined
JSONRPC_SERVER_ERROR     = -32000
JSONRPC_AUTH_REQUIRED    = -32001
JSONRPC_FORBIDDEN        = -32002
JSONRPC_RATE_LIMITED     = -32003


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


def jsonrpc_error(code: int, message: str, *, data: Any = None) -> dict:
    body: dict = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return body


def jsonrpc_envelope(
    id: Any,
    *,
    result: Optional[dict] = None,
    error: Optional[dict] = None,
) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": id}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    return body


# ─── HTTP response builders ───────────────────────────────────────────────────

def _encode(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def oauth_error_response(
    code: str,
    description: Optional[str] = None,
    *,
    state: Optional[str] = None,
    error_uri: Optional[str] = None,
    audience: Optional[str] = None,
) -> "JSONResponse":
    """Build a `JSONResponse` carrying an OAuth error with the right status code
    and a `WWW-Authenticate` header."""
    from starlette.responses import JSONResponse as _JR

    status_code = OAUTH_ERROR_CODES.get(code, 400)
    body = oauth_error(code, description, state=state, error_uri=error_uri)
    www = build_www_authenticate(code, description, audience=audience)
    return _JR(
        status_code=status_code,
        content=body,
        headers={"WWW-Authenticate": www} if www else {},
        media_type="application/json; charset=utf-8",
    )


def build_www_authenticate(
    error: Optional[str] = None,
    description: Optional[str] = None,
    *,
    audience: Optional[str] = None,
) -> str:
    """Build a `WWW-Authenticate: Bearer ...` header per RFC 6750 §3.

    Header values must be ASCII (RFC 7230 §3.2.6). Non-ASCII characters in
    the description are transliterated to `?` so we never raise a
    UnicodeEncodeError at response-build time.

    Parts are space-separated (which RFC 7235 §2.1 permits) so single-param
    challenges like `Bearer realm="mcp_service"` stay readable.
    """
    parts = ["Bearer"]
    if audience:
        parts.append(f'realm="{_ascii(audience)}"')
    if error:
        parts.append(f'error="{_ascii(error)}"')
    if description:
        safe = description.replace('"', "'")
        parts.append(f'error_description="{_ascii(safe)}"')
    return " ".join(parts)


def _ascii(value: str) -> str:
    """Force a string to ASCII, replacing any non-ASCII character with `?`."""
    return value.encode("ascii", "replace").decode("ascii")


# ─── FastAPI exception handler glue ──────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def install_error_handlers(app: FastAPI) -> None:
    """Register exception handlers so all uncaught errors return the documented
    envelope (with `WWW-Authenticate` on auth failures)."""

    @app.exception_handler(RequestValidationError)
    async def _on_validation(request: Request, exc: RequestValidationError):
        return _JSON(
            {"error": "invalid_request",
             "error_description": f"Request validation failed: {exc.errors()}"},
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def _on_http(request: Request, exc: HTTPException):
        """If an HTTPException was raised with an OAuth-shaped detail dict,
        unwrap it into the standard envelope. Otherwise fall back to
        `{"detail": "..."}` for backward compat."""
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return _JSON(exc.detail, status_code=exc.status_code,
                         headers=exc.headers or None)
        return _JSON(
            {"error": "invalid_request", "error_description": str(exc.detail)},
            status_code=exc.status_code,
            headers=exc.headers or None,
        )

    @app.exception_handler(404)
    async def _on_404(request: Request, exc):
        return _JSON(
            {"error": "invalid_request", "error_description": "Not found"},
            status_code=404,
        )

    @app.exception_handler(405)
    async def _on_405(request: Request, exc):
        return _JSON(
            {"error": "invalid_request",
             "error_description": f"Method {request.method} not allowed"},
            status_code=405,
        )


def _JSON(body: dict, status_code: int, headers=None) -> JSONResponse:
    return JSONResponse(
        content=body,
        status_code=status_code,
        headers=headers,
        media_type="application/json; charset=utf-8",
    )


__all__ = [
    "OAUTH_ERROR_CODES",
    "OAuthErrorBody",
    "oauth_error",
    "oauth_error_response",
    "build_www_authenticate",
    "JsonRpcError",
    "jsonrpc_error",
    "jsonrpc_envelope",
    "install_error_handlers",
    "JSONRPC_PARSE_ERROR",
    "JSONRPC_INVALID_REQUEST",
    "JSONRPC_METHOD_NOT_FOUND",
    "JSONRPC_INVALID_PARAMS",
    "JSONRPC_INTERNAL_ERROR",
    "JSONRPC_SERVER_ERROR",
    "JSONRPC_AUTH_REQUIRED",
    "JSONRPC_FORBIDDEN",
    "JSONRPC_RATE_LIMITED",
]
