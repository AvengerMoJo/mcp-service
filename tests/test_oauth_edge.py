"""OAuth endpoints edge cases — paths still missing in coverage:

* AS metadata when OAuth is disabled
* Protected resource metadata when OAuth is disabled
* Register endpoint with invalid JSON body
* Authorize POST with ``deny`` action → redirect with ``access_denied``
* Authorize GET when ``auto_approve=False`` → renders consent template
* Authorize GET with non-S256 challenge method → redirect with error
* Authorize GET with invalid redirect URI → 400 invalid_request
* Localhost relay success HTML page (line 205)
* Token endpoint when OAuth is disabled
* Token endpoint missing fields for authorization_code grant
"""

from __future__ import annotations

import httpx
import pytest


# ── Disabled-OAuth paths ─────────────────────────────────────────────────────


class TestDisabledOAuth:
    @pytest.mark.asyncio
    async def test_oauth_routes_not_mounted_when_disabled(
        self, tmp_oauth_dir, reset_config, reset_token_store, reset_validator,
        monkeypatch
    ):
        """When ``OAUTH_ENABLED=false`` the OAuth router is not mounted, so
        the discovery / register / token endpoints return 404."""
        monkeypatch.setenv("OAUTH_ENABLED", "false")
        import mcp_service.config as cm
        cm._config = None
        from mcp_service import create_app

        def h(req):
            return {}

        app = create_app(h, title="t")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            for path in ("/.well-known/oauth-authorization-server",
                          "/.well-known/oauth-protected-resource",
                          "/oauth/register",
                          "/oauth/token",
                          "/oauth/authorize"):
                r = await c.get(path) if path != "/oauth/register" \
                                       and path != "/oauth/token" else \
                    await c.post(path, data={"grant_type": "x"},
                                 json={"redirect_uris": ["x"]}
                                 if "register" in path else None)
                assert r.status_code == 404, f"{path} should 404 when disabled"


# ── Register: invalid JSON body ──────────────────────────────────────────────


class TestRegisterEdgeCases:
    @pytest.mark.asyncio
    async def test_register_invalid_json(self, client):
        r = await client.post("/oauth/register",
                              content="not json",
                              headers={"Content-Type": "application/json"})
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"


# ── Authorize POST deny / GET paths ──────────────────────────────────────────


class TestAuthorizePaths:
    @pytest.mark.asyncio
    async def test_authorize_get_renders_consent_when_auto_approve_disabled(
        self, tmp_oauth_dir, reset_config, reset_token_store, reset_validator,
        monkeypatch
    ):
        monkeypatch.setenv("OAUTH_AUTO_APPROVE", "false")
        import mcp_service.config as cm
        cm._config = None
        from mcp_service import create_app

        def h(req):
            return {}

        app = create_app(h, title="t")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r = await c.get("/oauth/authorize", params={
                "response_type": "code",
                "redirect_uri": "http://localhost/cb",
                "state": "s",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "scope": "mcp:read",
            }, follow_redirects=False)
            # Consent template rendered — returns 200 HTML
            assert r.status_code == 200
            assert "text/html" in r.headers["content-type"]

    @pytest.mark.asyncio
    async def test_authorize_get_rejects_non_s256(self, client):
        r = await client.get("/oauth/authorize", params={
            "response_type": "code",
            "redirect_uri": "http://localhost/cb",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "plain",
        }, follow_redirects=False)
        assert r.status_code in (302, 307, 303)
        loc = r.headers["location"]
        assert "invalid_request" in loc

    @pytest.mark.asyncio
    async def test_authorize_get_invalid_redirect_uri(self, client):
        r = await client.get("/oauth/authorize", params={
            "response_type": "code",
            "redirect_uri": "not-a-url",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_authorize_post_deny(self, client):
        r = await client.post("/oauth/authorize", data={
            "action": "deny",
            "client_id": "x",
            "redirect_uri": "http://localhost/cb",
            "scope": "mcp:read",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        }, follow_redirects=False)
        assert r.status_code in (302, 303, 307)
        loc = r.headers["location"]
        assert "access_denied" in loc
        assert "state=s" in loc


# ── Token endpoint edge cases ────────────────────────────────────────────────


class TestTokenEdgeCases:
    @pytest.mark.asyncio
    async def test_auth_code_grant_missing_fields(self, client):
        r = await client.post("/oauth/token", data={
            "grant_type": "authorization_code",
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_auth_code_grant_redirect_uri_mismatch(self, client, tmp_oauth_dir):
        from mcp_service.oauth.storage import get_authorization_code_store
        from mcp_service.oauth.pkce import (
            generate_code_verifier, generate_code_challenge,
        )
        store = get_authorization_code_store()
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        cd = store.create(
            client_id="c1", redirect_uri="http://localhost/cb",
            scope="mcp:read", code_challenge=challenge,
            code_challenge_method="S256",
        )
        r = await client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": cd.code,
            "redirect_uri": "http://attacker.example/cb",
            "code_verifier": verifier,
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    @pytest.mark.asyncio
    async def test_auth_code_grant_invalid_verifier_format(self, client, tmp_oauth_dir):
        from mcp_service.oauth.storage import get_authorization_code_store
        store = get_authorization_code_store()
        cd = store.create(
            client_id="c1", redirect_uri="http://localhost/cb",
            scope="mcp:read", code_challenge="abc",
            code_challenge_method="S256",
        )
        r = await client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": cd.code,
            "redirect_uri": "http://localhost/cb",
            "code_verifier": "x",  # too short
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    @pytest.mark.asyncio
    async def test_refresh_token_missing(self, client):
        r = await client.post("/oauth/token", data={
            "grant_type": "refresh_token",
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_refresh_token_invalid(self, client):
        r = await client.post("/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": "fake-token",
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    @pytest.mark.asyncio
    async def test_refresh_token_valid_returns_access_token(self, client, tmp_oauth_dir):
        from mcp_service.oauth.storage import get_token_store
        ts = get_token_store()
        td = ts.create_access_token("c1", "mcp:read")
        rt = td.refresh_token
        assert rt is not None
        r = await client.post("/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": rt,
        })
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        # Refresh token should be returned unchanged (rotation policy is
        # server-specific).
        assert body.get("refresh_token") == rt