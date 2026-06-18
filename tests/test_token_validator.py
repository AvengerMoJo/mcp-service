"""Token validator tests — opaque tokens, JWTs, API key."""

from __future__ import annotations

import time

import jwt
import pytest

from mcp_service.config import OAuthConfig
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


class TestApiKey:
    @pytest.mark.asyncio
    async def test_valid_api_key_returns_token(self, monkeypatch):
        monkeypatch.setenv("MCP_API_KEY", "secret-key")
        v = TokenValidator(_cfg())
        tok = await v.validate_token("secret-key")
        assert tok.client_id == "api_key"
        assert "mcp:read" in tok.scopes

    @pytest.mark.asyncio
    async def test_wrong_api_key_falls_through(self, monkeypatch):
        monkeypatch.setenv("MCP_API_KEY", "secret-key")
        v = TokenValidator(_cfg())
        with pytest.raises(TokenValidationError):
            await v.validate_token("not-the-key")


class TestOpaqueToken:
    @pytest.mark.asyncio
    async def test_valid_opaque(self, monkeypatch, tmp_oauth_dir):
        monkeypatch.setenv("OAUTH_STORAGE_DIR", str(tmp_oauth_dir))
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        from mcp_service.oauth.storage import get_token_store

        td = get_token_store().create_access_token("c1", "mcp:read mcp:write")
        v = TokenValidator(_cfg())
        tok = await v.validate_token(td.token)
        assert tok.client_id == "c1"
        assert "mcp:read" in tok.scopes
        assert "mcp:write" in tok.scopes
        assert tok.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_expired_opaque_rejected(self, monkeypatch, tmp_oauth_dir):
        monkeypatch.setenv("OAUTH_STORAGE_DIR", str(tmp_oauth_dir))
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        from mcp_service.oauth.storage import get_token_store

        td = get_token_store().create_access_token("c", "s", ttl=1)
        time.sleep(1.1)
        v = TokenValidator(_cfg())
        with pytest.raises(TokenValidationError):
            await v.validate_token(td.token)


class TestJwt:
    @pytest.mark.asyncio
    async def test_valid_hs256(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "shhh")
        cfg = _cfg(
            algorithm="HS256",
            verify_signature=True,
            verify_audience=False,
            verify_issuer=False,
        )
        token = jwt.encode(
            {
                "sub": "u1",
                "client_id": "c1",
                "scope": "mcp:read",
                "exp": int(time.time()) + 60,
                "iat": int(time.time()),
            },
            "shhh",
            algorithm="HS256",
        )
        v = TokenValidator(cfg)
        tok = await v.validate_token(token)
        assert tok.user_id == "u1"
        assert tok.client_id == "c1"
        assert "mcp:read" in tok.scopes

    @pytest.mark.asyncio
    async def test_expired_rejected(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "shhh")
        cfg = _cfg(algorithm="HS256", verify_signature=True)
        token = jwt.encode(
            {"sub": "u", "scope": "s", "exp": int(time.time()) - 60},
            "shhh",
            algorithm="HS256",
        )
        v = TokenValidator(cfg)
        with pytest.raises(TokenValidationError):
            await v.validate_token(token)

    @pytest.mark.asyncio
    async def test_signature_failure(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "right-secret")
        cfg = _cfg(algorithm="HS256", verify_signature=True)
        token = jwt.encode(
            {"sub": "u", "exp": int(time.time()) + 60},
            "wrong-secret",
            algorithm="HS256",
        )
        v = TokenValidator(cfg)
        with pytest.raises(TokenValidationError):
            await v.validate_token(token)

    @pytest.mark.asyncio
    async def test_audience_enforced(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "shhh")
        cfg = _cfg(
            algorithm="HS256",
            verify_signature=True,
            verify_audience=True,
            audience="mcp_service",
        )
        token = jwt.encode(
            {
                "sub": "u",
                "aud": "wrong-audience",
                "exp": int(time.time()) + 60,
            },
            "shhh",
            algorithm="HS256",
        )
        v = TokenValidator(cfg)
        with pytest.raises(TokenValidationError):
            await v.validate_token(token)

    @pytest.mark.asyncio
    async def test_issuer_enforced(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "shhh")
        cfg = _cfg(
            algorithm="HS256",
            verify_signature=True,
            verify_issuer=True,
            issuer="expected-iss",
        )
        token = jwt.encode(
            {
                "sub": "u",
                "iss": "wrong-iss",
                "exp": int(time.time()) + 60,
            },
            "shhh",
            algorithm="HS256",
        )
        v = TokenValidator(cfg)
        with pytest.raises(TokenValidationError):
            await v.validate_token(token)

    @pytest.mark.asyncio
    async def test_malformed_token_rejected(self):
        v = TokenValidator(_cfg())
        with pytest.raises(TokenValidationError):
            await v.validate_token("not-a-jwt")

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self):
        v = TokenValidator(_cfg())
        with pytest.raises(TokenValidationError):
            await v.validate_token("")

    @pytest.mark.asyncio
    async def test_scope_parsing(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "shhh")
        cfg = _cfg(algorithm="HS256", verify_signature=True)
        token = jwt.encode(
            {
                "sub": "u",
                "scope": "mcp:read mcp:admin",
                "exp": int(time.time()) + 60,
            },
            "shhh",
            algorithm="HS256",
        )
        v = TokenValidator(cfg)
        tok = await v.validate_token(token)
        assert tok.scopes == ["mcp:read", "mcp:admin"]
        assert tok.scope == "mcp:read mcp:admin"


class TestWwwAuthenticate:
    def test_basic(self):
        v = TokenValidator(_cfg())
        h = v.create_www_authenticate_header("invalid_token", "bad")
        assert h.startswith("Bearer")
        assert 'error="invalid_token"' in h
        assert 'error_description="bad"' in h

    def test_realm_includes_audience(self):
        v = TokenValidator(_cfg(audience="mcp-x"))
        h = v.create_www_authenticate_header()
        assert 'realm="mcp-x"' in h

    def test_description_optional(self):
        v = TokenValidator(_cfg())
        h = v.create_www_authenticate_header("server_error")
        assert "error_description" not in h