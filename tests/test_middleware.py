"""Middleware / token validator edge cases.

Targets the lines that are still missing in the coverage report:
- ``middleware._audience`` helper
- ``optional_oauth_token`` returning ``None`` on invalid tokens
- ``required_oauth_token`` raising ``HTTPException`` on invalid / missing tokens
- ``TokenValidator._validate_opaque`` exception path
- ``TokenValidator._validate_jwt`` paths (``PyJWT`` missing, signing-key errors,
  list-shaped ``scope`` claim)
- ``TokenValidator._get_signing_key`` with ``verify_signature=False``
"""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from mcp_service.config import OAuthConfig
from mcp_service.oauth.middleware import (
    OptionalOAuthToken,
    RequiredOAuthToken,
    optional_oauth_token,
    required_oauth_token,
    validated_oauth_token,
)
from mcp_service.oauth.token_validator import TokenValidationError, TokenValidator


def _cfg(**overrides) -> OAuthConfig:
    base = dict(
        enabled=True,
        enable_authorization_server=True,
        auto_approve=True,
        verify_signature=False,
        verify_audience=False,
        verify_issuer=False,
        verify_exp=True,
    )
    base.update(overrides)
    return OAuthConfig(**base)


# ─── _audience default ────────────────────────────────────────────────────────


class TestAudienceHelper:
    def test_audience_default(self, monkeypatch):
        """``_audience`` returns ``mcp_service`` when ``OAUTH_AUDIENCE`` is unset."""
        from mcp_service.oauth import middleware

        monkeypatch.delenv("OAUTH_AUDIENCE", raising=False)
        import mcp_service.config as config_mod
        config_mod._config = None
        assert middleware._audience() == "mcp_service"

    def test_audience_overridden(self, monkeypatch):
        from mcp_service.oauth import middleware

        monkeypatch.setenv("OAUTH_AUDIENCE", "my-realm")
        import mcp_service.config as config_mod
        config_mod._config = None
        assert middleware._audience() == "my-realm"


# ─── optional_oauth_token ─────────────────────────────────────────────────────


class TestOptionalOAuthToken:
    @pytest.mark.asyncio
    async def test_none_when_no_credentials(self):
        assert await optional_oauth_token(None) is None

    @pytest.mark.asyncio
    async def test_none_when_invalid_credentials(self):
        """Invalid Bearer tokens are silently swallowed (optional dep)."""
        token = await optional_oauth_token(_credentials("not-a-token"))
        assert token is None

    @pytest.mark.asyncio
    async def test_returns_token_when_valid(self, monkeypatch):
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        from mcp_service.oauth.storage import get_token_store

        td = get_token_store().create_access_token("c1", "mcp:read")
        token = await optional_oauth_token(_credentials(td.token))
        assert token is not None
        assert token.client_id == "c1"


# ─── validated_oauth_token ────────────────────────────────────────────────────


class TestValidatedOAuthToken:
    @pytest.mark.asyncio
    async def test_none_when_no_credentials(self):
        assert await validated_oauth_token(None) is None

    @pytest.mark.asyncio
    async def test_raises_http_exception_when_invalid(self):
        with pytest.raises(HTTPException) as exc_info:
            await validated_oauth_token(_credentials("garbage"))
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["error"] == "invalid_token"
        assert "WWW-Authenticate" in exc_info.value.headers


# ─── required_oauth_token ─────────────────────────────────────────────────────


class TestRequiredOAuthToken:
    @pytest.mark.asyncio
    async def test_raises_when_no_credentials(self):
        with pytest.raises(HTTPException) as exc_info:
            await required_oauth_token(None)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["error_description"] == "Bearer token required"
        assert "WWW-Authenticate" in exc_info.value.headers

    @pytest.mark.asyncio
    async def test_raises_on_invalid_token(self):
        with pytest.raises(HTTPException) as exc_info:
            await required_oauth_token(_credentials("nope"))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_token_on_valid(self, monkeypatch):
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        from mcp_service.oauth.storage import get_token_store

        td = get_token_store().create_access_token("c", "mcp:read")
        tok = await required_oauth_token(_credentials(td.token))
        assert tok.client_id == "c"


# ─── TokenValidator edge cases ────────────────────────────────────────────────


class TestValidatorEdgeCases:
    def test_jwks_uri_sets_up_client(self):
        """When ``jwks_uri`` is configured, ``PyJWKClient`` is constructed."""
        v = TokenValidator(_cfg(jwks_uri="https://example.com/.well-known/jwks.json"))
        assert v.jwks_client is not None

    def test_no_jwks_uri_leaves_client_none(self):
        v = TokenValidator(_cfg())
        assert v.jwks_client is None

    @pytest.mark.asyncio
    async def test_opaque_lookup_exception_swallowed(self, monkeypatch):
        """If the token store raises during opaque lookup, the validator
        falls through to JWT validation rather than crashing."""
        monkeypatch.setenv("JWT_SECRET", "shh")
        monkeypatch.delenv("MCP_API_KEY", raising=False)

        from mcp_service.oauth import storage
        from mcp_service.oauth import token_validator as tv_mod

        original = storage.get_token_store

        def _broken():
            class _Broken:
                def get_access_token(self_inner, _token):
                    raise RuntimeError("storage exploded")

            return _Broken()

        monkeypatch.setattr(storage, "get_token_store", _broken)
        # Force the import-local lookup to use our patched function too.
        monkeypatch.setattr(tv_mod, "get_token_store", _broken, raising=False)

        token = jwt.encode(
            {"sub": "u", "exp": int(time.time()) + 60}, "shh", algorithm="HS256"
        )
        v = TokenValidator(_cfg(algorithm="HS256", verify_signature=True))
        tok = await v.validate_token(token)
        assert tok.sub == "u"

    @pytest.mark.asyncio
    async def test_jwt_list_scope(self, monkeypatch):
        """``scope`` claim may be a list — should be accepted as-is."""
        monkeypatch.setenv("JWT_SECRET", "shh")
        token = jwt.encode(
            {
                "sub": "u",
                "scope": ["mcp:read", "mcp:write"],
                "exp": int(time.time()) + 60,
            },
            "shh",
            algorithm="HS256",
        )
        v = TokenValidator(_cfg(algorithm="HS256", verify_signature=True))
        tok = await v.validate_token(token)
        assert sorted(tok.scopes) == ["mcp:read", "mcp:write"]
        assert tok.scope == "mcp:read mcp:write"

    @pytest.mark.asyncio
    async def test_get_signing_key_returns_empty_when_verify_disabled(
        self, monkeypatch
    ):
        """``verify_signature=False`` short-circuits to an empty key."""
        v = TokenValidator(_cfg(verify_signature=False))
        # _get_signing_key is private — exercise via the public flow.
        # With verify_signature=False, jwt.decode accepts an empty key.
        monkeypatch.setenv("JWT_SECRET", "ignored")
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        token = jwt.encode(
            {"sub": "u", "exp": int(time.time()) + 60}, "anything", algorithm="HS256"
        )
        tok = await v.validate_token(token)
        assert tok.sub == "u"

    @pytest.mark.asyncio
    async def test_no_signing_key_available_raises(self, monkeypatch):
        """Without JWKS, JWT secret, or API key, validation fails cleanly."""
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        token = jwt.encode(
            {"sub": "u", "exp": int(time.time()) + 60}, "anything", algorithm="HS256"
        )
        v = TokenValidator(_cfg(verify_signature=True))
        with pytest.raises(TokenValidationError):
            await v.validate_token(token)

    @pytest.mark.asyncio
    async def test_jwks_fallback_to_api_key_secret(self, monkeypatch):
        """Without JWKS or JWT_SECRET, MCP_API_KEY is used as HMAC secret."""
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("MCP_API_KEY", "shared-secret")
        v = TokenValidator(_cfg(algorithm="HS256", verify_signature=True))
        token = jwt.encode(
            {"sub": "u", "exp": int(time.time()) + 60},
            "shared-secret",
            algorithm="HS256",
        )
        tok = await v.validate_token(token)
        assert tok.sub == "u"

    def test_create_www_authenticate_no_audience(self):
        v = TokenValidator(_cfg())
        v.config.audience = None
        h = v.create_www_authenticate_header(error=None, description=None)
        assert h == "Bearer"


# ─── Middleware integration via FastAPI ──────────────────────────────────────


def _credentials(token):
    """Build a minimal HTTPAuthorizationCredentials for the dependency fns."""
    from fastapi.security import HTTPAuthorizationCredentials

    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _build_dep_app():
    app = FastAPI()

    @app.get("/opt")
    async def opt(token: OptionalOAuthToken):
        return {"t": token.client_id if token else None}

    @app.get("/req")
    async def req(token: RequiredOAuthToken):
        return {"t": token.client_id}

    return app


class TestMiddlewareInApp:
    def test_optional_returns_none_without_token(self):
        c = TestClient(_build_dep_app())
        r = c.get("/opt")
        assert r.status_code == 200
        assert r.json() == {"t": None}

    def test_optional_returns_none_for_bad_token(self):
        c = TestClient(_build_dep_app())
        r = c.get("/opt", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 200
        assert r.json() == {"t": None}

    def test_required_401_without_token(self):
        c = TestClient(_build_dep_app())
        r = c.get("/req")
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers