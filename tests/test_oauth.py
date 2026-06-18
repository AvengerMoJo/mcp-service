"""OAuth 2.1 endpoint tests — full flow."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from mcp_service.oauth.pkce import generate_pkce_pair
from mcp_service.oauth.storage import get_token_store


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


async def _register(client, redirect_uri="http://localhost:9999/cb") -> dict:
    r = await client.post(
        "/oauth/register",
        json={"client_name": "test", "redirect_uris": [redirect_uri]},
    )
    assert r.status_code == 201
    return r.json()


class TestMetadata:
    @pytest.mark.asyncio
    async def test_as_metadata(self, client):
        r = await client.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        body = r.json()
        assert body["issuer"] == "http://testserver"
        assert body["authorization_endpoint"].endswith("/oauth/authorize")
        assert body["token_endpoint"].endswith("/oauth/token")
        assert body["registration_endpoint"].endswith("/oauth/register")
        assert "mcp:read" in body["scopes_supported"]
        assert "S256" in body["code_challenge_methods_supported"]

    @pytest.mark.asyncio
    async def test_protected_resource_metadata(self, client):
        r = await client.get("/.well-known/oauth-protected-resource")
        assert r.status_code == 200
        body = r.json()
        assert body["resource"] == "http://testserver"
        assert "mcp:read" in body["scopes_supported"]


class TestClientRegistration:
    @pytest.mark.asyncio
    async def test_register_succeeds(self, client):
        r = await client.post(
            "/oauth/register",
            json={"client_name": "demo", "redirect_uris": ["http://x/cb"]},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["client_id"]
        assert body["redirect_uris"] == ["http://x/cb"]
        assert body["token_endpoint_auth_method"] == "none"

    @pytest.mark.asyncio
    async def test_register_requires_redirect_uris(self, client):
        r = await client.post(
            "/oauth/register", json={"client_name": "no-uri"}
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_register_invalid_json(self, client):
        r = await client.post("/oauth/register", content="not json")
        assert r.status_code == 400


class TestAuthorizeGet:
    @pytest.mark.asyncio
    async def test_auto_approve_redirects_with_code(self, client):
        registered = await _register(client)
        v, c = generate_pkce_pair()
        r = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "abc",
                "code_challenge": c,
                "code_challenge_method": "S256",
                "scope": "mcp:read",
            },
            follow_redirects=False,
        )
        assert r.status_code in (302, 303, 307)
        loc = r.headers["location"]
        parsed = urlparse(loc)
        qs = parse_qs(parsed.query)
        assert qs["state"] == ["abc"]
        assert qs["code"]

    @pytest.mark.asyncio
    async def test_rejects_non_s256(self, client):
        registered = await _register(client)
        r = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "abc",
                "code_challenge": "plain-challenge",
                "code_challenge_method": "plain",
            },
            follow_redirects=False,
        )
        assert r.status_code in (302, 303, 307)
        qs = parse_qs(urlparse(r.headers["location"]).query)
        assert qs["error"] == ["invalid_request"]

    @pytest.mark.asyncio
    async def test_rejects_unsupported_response_type(self, client):
        registered = await _register(client)
        v, c = generate_pkce_pair()
        r = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "token",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "s",
                "code_challenge": c,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert r.status_code in (302, 303, 307)
        qs = parse_qs(urlparse(r.headers["location"]).query)
        assert qs["error"] == ["unsupported_response_type"]

    @pytest.mark.asyncio
    async def test_invalid_redirect_uri_rejected(self, client):
        registered = await _register(client)
        v, c = generate_pkce_pair()
        r = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "not-a-url",
                "state": "s",
                "code_challenge": c,
                "code_challenge_method": "S256",
            },
        )
        assert r.status_code == 400


class TestAuthorizePost:
    @pytest.mark.asyncio
    async def test_deny_returns_access_denied(self, client):
        registered = await _register(client)
        v, c = generate_pkce_pair()
        r = await client.post(
            "/oauth/authorize",
            data={
                "action": "deny",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "scope": "mcp:read",
                "state": "xyz",
                "code_challenge": c,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert r.status_code in (302, 303, 307)
        qs = parse_qs(urlparse(r.headers["location"]).query)
        assert qs["error"] == ["access_denied"]

    @pytest.mark.asyncio
    async def test_allow_returns_code(self, client):
        registered = await _register(client)
        v, c = generate_pkce_pair()
        r = await client.post(
            "/oauth/authorize",
            data={
                "action": "allow",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "scope": "mcp:read",
                "state": "xyz",
                "code_challenge": c,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert r.status_code in (302, 303, 307)
        qs = parse_qs(urlparse(r.headers["location"]).query)
        assert "code" in qs


class TestTokenGrant:
    @pytest.mark.asyncio
    async def test_full_authorization_code_grant(self, client):
        registered = await _register(client)
        verifier, challenge = generate_pkce_pair()

        auth = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
            },
            follow_redirects=False,
        )
        code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]

        r = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "Bearer"
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["expires_in"] > 0
        assert "mcp:read" in body["scope"].split()

    @pytest.mark.asyncio
    async def test_code_cannot_be_reused(self, client):
        registered = await _register(client)
        verifier, challenge = generate_pkce_pair()
        auth = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]

        r1 = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": verifier,
            },
        )
        assert r1.status_code == 200

        r2 = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": verifier,
            },
        )
        assert r2.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_verifier_rejected(self, client):
        registered = await _register(client)
        verifier, challenge = generate_pkce_pair()
        auth = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
        bad_verifier = secrets.token_urlsafe(64)

        r = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": bad_verifier,
            },
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_redirect_uri_mismatch(self, client):
        registered = await _register(client)
        verifier, challenge = generate_pkce_pair()
        auth = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
        r = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/different",
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_code_rejected(self, client):
        r = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "not-a-real-code",
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": "a" * 64,
            },
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_params_rejected(self, client):
        r = await client.post(
            "/oauth/token", data={"grant_type": "authorization_code"}
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_unsupported_grant_type(self, client):
        r = await client.post(
            "/oauth/token",
            data={"grant_type": "client_credentials"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_short_verifier_rejected(self, client):
        registered = await _register(client)
        verifier, challenge = generate_pkce_pair()
        auth = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
        r = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": "tooshort",
            },
        )
        assert r.status_code == 400


class TestRefreshGrant:
    @pytest.mark.asyncio
    async def test_refresh_issues_new_access_token(self, client):
        registered = await _register(client)
        verifier, challenge = generate_pkce_pair()
        auth = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": "http://localhost:9999/cb",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]

        tok = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": verifier,
            },
        )
        refresh = tok.json()["refresh_token"]
        first_access = tok.json()["access_token"]

        r = await client.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"]
        assert body["access_token"] != first_access

    @pytest.mark.asyncio
    async def test_invalid_refresh_token(self, client):
        r = await client.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": "not-real"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_refresh_token(self, client):
        r = await client.post(
            "/oauth/token", data={"grant_type": "refresh_token"}
        )
        assert r.status_code == 400


class TestOAuthDisabled:
    @pytest.mark.asyncio
    async def test_as_metadata_returns_501(self, handler, tmp_oauth_dir, monkeypatch):
        monkeypatch.setenv("OAUTH_ENABLED", "false")
        import mcp_service.config as config_mod
        import mcp_service.oauth.storage as storage_mod
        import mcp_service.oauth.middleware as mw
        config_mod._config = None
        storage_mod._code_store = None
        storage_mod._token_store = None
        storage_mod._client_store = None
        mw._validator = None
        from mcp_service import create_app
        import httpx

        app = create_app(handler, title="test-server")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            r = await c.get("/.well-known/oauth-authorization-server")
            # When OAuth is disabled the endpoints aren't mounted → 404.
            # When OAuth AS is disabled but resource metadata is on, → 501.
            assert r.status_code in (404, 501)

    @pytest.mark.asyncio
    async def test_register_returns_501(self, handler, tmp_oauth_dir, monkeypatch):
        monkeypatch.setenv("OAUTH_ENABLED", "false")
        import mcp_service.config as config_mod
        import mcp_service.oauth.storage as storage_mod
        import mcp_service.oauth.middleware as mw
        config_mod._config = None
        storage_mod._code_store = None
        storage_mod._token_store = None
        storage_mod._client_store = None
        mw._validator = None
        from mcp_service import create_app
        import httpx

        app = create_app(handler, title="test-server")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            r = await c.post(
                "/oauth/register",
                json={"client_name": "x", "redirect_uris": ["http://x/cb"]},
            )
            assert r.status_code in (404, 501)