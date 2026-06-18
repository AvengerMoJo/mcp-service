"""
OAuth 2.1 Authorization Server endpoints.
  GET  /.well-known/oauth-authorization-server  — RFC 8414 metadata
  GET  /.well-known/oauth-protected-resource    — protected resource metadata
  POST /oauth/register                          — Dynamic Client Registration (RFC 7591)
  GET  /oauth/authorize                         — PKCE authorization (consent page or auto-approve)
  POST /oauth/authorize                         — process allow/deny
  POST /oauth/token                             — exchange code → tokens, refresh

All error responses follow RFC 6749 §5.2 envelopes (`error`, `error_description`,
`error_uri`, `state`) — see `mcp_service.errors`.
"""

import json
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from mcp_service.errors import oauth_error_response
from .models import AuthorizationServerMetadata, TokenResponse
from .pkce import is_valid_code_verifier, verify_code_challenge
from .storage import (
    get_authorization_code_store,
    get_client_registration_store,
    get_token_store,
)
from mcp_service.config import get_config

_log = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])


def _json(data: dict, status_code: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(content=body, status_code=status_code,
                    media_type="application/json; charset=utf-8")

_template_dir = Path(__file__).parent / "templates"
_template_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(_template_dir))


def _base_url(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _validate_redirect_uri(uri: str) -> bool:
    try:
        p = urlparse(uri)
        return bool(p.scheme) and bool(p.netloc) and p.scheme in ("http", "https", "app")
    except Exception:
        return False


# ── discovery ─────────────────────────────────────────────────────────────────

@router.get("/.well-known/oauth-authorization-server")
async def as_metadata(request: Request) -> Response:
    cfg = get_config()
    if not cfg.oauth.enabled or not cfg.oauth.enable_authorization_server:
        return oauth_error_response("server_error", "OAuth AS not enabled")
    base = _base_url(request)
    meta = AuthorizationServerMetadata(
        issuer=base,
        authorization_endpoint=f"{base}/oauth/authorize",
        token_endpoint=f"{base}/oauth/token",
        registration_endpoint=f"{base}/oauth/register",
        scopes_supported=cfg.oauth.supported_scopes,
    )
    return _json(meta.model_dump())


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request) -> Response:
    cfg = get_config()
    if not cfg.oauth.enabled:
        return oauth_error_response("server_error", "OAuth not enabled")
    base = _base_url(request)
    return _json(cfg.oauth.get_protected_resource_metadata(base))


# ── Dynamic Client Registration ───────────────────────────────────────────────

@router.post("/oauth/register")
async def register_client(request: Request) -> Response:
    cfg = get_config()
    if not cfg.oauth.enabled or not cfg.oauth.enable_authorization_server:
        return oauth_error_response("server_error", "OAuth AS not enabled")
    try:
        body = await request.json()
    except Exception:
        return oauth_error_response("invalid_request", "Invalid JSON body")

    redirect_uris = body.get("redirect_uris", [])
    if not redirect_uris:
        return oauth_error_response(
            "invalid_request",
            "redirect_uris is required (RFC 7591 §2)",
        )

    store = get_client_registration_store()
    client = store.register_client(
        client_name=body.get("client_name", "Unknown Client"),
        redirect_uris=redirect_uris,
        grant_types=body.get("grant_types", ["authorization_code"]),
        response_types=body.get("response_types", ["code"]),
        scope=body.get("scope", " ".join(cfg.oauth.supported_scopes)),
    )
    return _json({
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "response_types": client.response_types,
        "token_endpoint_auth_method": "none",
        "scope": client.scope,
    }, status_code=201)


# ── Authorization endpoint ────────────────────────────────────────────────────

@router.get("/oauth/authorize")
async def authorize_get(
    request: Request,
    response_type: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: Optional[str] = None,
    client_id: Optional[str] = None,
):
    cfg = get_config()
    if not cfg.oauth.enabled or not cfg.oauth.enable_authorization_server:
        return oauth_error_response("server_error", "OAuth AS not enabled")
    if response_type != "code":
        return RedirectResponse(
            f"{redirect_uri}?{urlencode({'error': 'unsupported_response_type', 'state': state})}"
        )
    if code_challenge_method != "S256":
        return RedirectResponse(
            f"{redirect_uri}?{urlencode({'error': 'invalid_request', 'error_description': 'Only S256 challenge method is supported', 'state': state})}"
        )
    if not _validate_redirect_uri(redirect_uri):
        return oauth_error_response("invalid_request", "Invalid redirect_uri")

    scope = scope or "mcp:read mcp:write"

    if cfg.oauth.auto_approve:
        return await _approve(request, client_id, redirect_uri, scope, state, code_challenge, code_challenge_method)

    return templates.TemplateResponse("authorize.html", {
        "request": request,
        "client_id": client_id or "MCP Client",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "scopes": scope.split(),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    })


@router.post("/oauth/authorize")
async def authorize_post(
    request: Request,
    action: str = Form(...),
    client_id: Optional[str] = Form(None),
    redirect_uri: str = Form(...),
    scope: str = Form(...),
    state: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
):
    if action == "deny":
        return RedirectResponse(
            f"{redirect_uri}?{urlencode({'error': 'access_denied', 'state': state})}"
        )
    return await _approve(request, client_id, redirect_uri, scope, state, code_challenge, code_challenge_method)


async def _approve(request, client_id, redirect_uri, scope, state, code_challenge, code_challenge_method):
    cfg = get_config()
    code_data = get_authorization_code_store().create(
        client_id=client_id, redirect_uri=redirect_uri, scope=scope,
        code_challenge=code_challenge, code_challenge_method=code_challenge_method,
        ttl=cfg.oauth.authorization_code_ttl,
    )
    callback_url = f"{redirect_uri}?{urlencode({'code': code_data.code, 'state': state})}"

    # Server-side relay for localhost Claude Code CLI
    parsed = urlparse(redirect_uri)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=5.0) as c:
                await c.get(callback_url)
            return HTMLResponse(
                "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                "<h2>Authentication complete</h2>"
                "<p>MCP server authorized. You can close this tab.</p>"
                "</body></html>"
            )
        except Exception as e:
            _log.warning("Localhost relay failed (%s), falling back to redirect", e)

    return RedirectResponse(url=callback_url, status_code=303)


# ── Token endpoint ─────────────────────────────────────────────────────────────

@router.post("/oauth/token")
async def token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
):
    cfg = get_config()
    if not cfg.oauth.enabled or not cfg.oauth.enable_authorization_server:
        return oauth_error_response("server_error", "OAuth AS not enabled")

    if grant_type == "authorization_code":
        return await _auth_code_grant(code, redirect_uri, code_verifier, client_id, cfg)
    if grant_type == "refresh_token":
        return await _refresh_grant(refresh_token, client_id, cfg)
    return oauth_error_response("unsupported_grant_type", f"grant_type {grant_type!r} is not supported")


async def _auth_code_grant(code, redirect_uri, code_verifier, client_id, cfg):
    if not code or not redirect_uri or not code_verifier:
        return oauth_error_response(
            "invalid_request",
            "authorization_code grant requires code, redirect_uri, code_verifier",
        )
    code_store = get_authorization_code_store()
    code_data = code_store.get(code)
    if not code_data or not code_data.is_valid():
        return oauth_error_response("invalid_grant", "Invalid or expired authorization code")
    if code_data.redirect_uri != redirect_uri:
        return oauth_error_response("invalid_grant", "Redirect URI mismatch")
    if not is_valid_code_verifier(code_verifier):
        return oauth_error_response("invalid_grant", "Invalid code_verifier format")
    if not verify_code_challenge(code_verifier, code_data.code_challenge, code_data.code_challenge_method):
        return oauth_error_response("invalid_grant", "PKCE verification failed")
    code_store.mark_used(code)
    td = get_token_store().create_access_token(
        client_id=code_data.client_id, scope=code_data.scope,
        ttl=cfg.oauth.access_token_ttl, refresh_token_ttl=cfg.oauth.refresh_token_ttl,
    )
    return _json(TokenResponse(
        access_token=td.token, token_type="Bearer",
        expires_in=td.get_expires_in(), refresh_token=td.refresh_token,
        scope=code_data.scope,
    ).model_dump())


async def _refresh_grant(refresh_token, client_id, cfg):
    if not refresh_token:
        return oauth_error_response("invalid_request", "refresh_token is required")
    rd = get_token_store().get_refresh_token(refresh_token)
    if not rd:
        return oauth_error_response("invalid_grant", "Invalid or expired refresh token")
    td = get_token_store().create_access_token(
        client_id=rd.client_id, scope=rd.scope,
        ttl=cfg.oauth.access_token_ttl, create_refresh_token=False,
    )
    return _json(TokenResponse(
        access_token=td.token, token_type="Bearer",
        expires_in=td.get_expires_in(), refresh_token=refresh_token,
        scope=rd.scope,
    ).model_dump())
