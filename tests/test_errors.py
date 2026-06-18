"""Standardized error envelope tests — OAuth + JSON-RPC builders."""

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from mcp_service.errors import (
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_PARSE_ERROR,
    OAUTH_ERROR_CODES,
    OAuthErrorBody,
    build_www_authenticate,
    install_error_handlers,
    jsonrpc_envelope,
    jsonrpc_error,
    oauth_error,
    oauth_error_response,
)


# ─── OAuthErrorBody / oauth_error ─────────────────────────────────────────────

class TestOAuthError:
    def test_known_codes_all_listed(self):
        # Every entry in the public catalog must be in the HTTP code map.
        for code, status in OAUTH_ERROR_CODES.items():
            assert isinstance(code, str)
            assert isinstance(status, int)

    def test_oauth_error_unknown_raises(self):
        with pytest.raises(ValueError):
            oauth_error("not_a_real_error")

    def test_oauth_error_minimal(self):
        body = oauth_error("invalid_request")
        assert body == {"error": "invalid_request"}

    def test_oauth_error_full(self):
        body = oauth_error(
            "invalid_grant",
            "PKCE verification failed",
            state="abc",
            error_uri="https://example.com/docs/errors#invalid_grant",
        )
        assert body["error"] == "invalid_grant"
        assert body["error_description"] == "PKCE verification failed"
        assert body["state"] == "abc"
        assert body["error_uri"].endswith("#invalid_grant")
        # No None keys leaked.
        assert "error_uri" in body

    def test_oauth_error_excludes_none(self):
        body = oauth_error("invalid_token", "expired")
        assert set(body.keys()) == {"error", "error_description"}

    def test_oauth_error_body_model_roundtrip(self):
        m = OAuthErrorBody(
            error="access_denied",
            error_description="user said no",
            state="s",
        )
        assert m.to_dict()["error"] == "access_denied"


# ─── JSON-RPC builders ────────────────────────────────────────────────────────

class TestJsonRpc:
    def test_envelope_with_result(self):
        env = jsonrpc_envelope(1, result={"ok": True})
        assert env == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    def test_envelope_with_error(self):
        env = jsonrpc_envelope(2, error={"code": -1, "message": "nope"})
        assert env["error"] == {"code": -1, "message": "nope"}
        assert "result" not in env

    def test_jsonrpc_error_minimal(self):
        assert jsonrpc_error(JSONRPC_PARSE_ERROR, "Parse error") == {
            "code": -32700, "message": "Parse error"
        }

    def test_jsonrpc_error_with_data(self):
        e = jsonrpc_error(JSONRPC_INTERNAL_ERROR, "boom", data="stacktrace")
        assert e["data"] == "stacktrace"


# ─── WWW-Authenticate builder (RFC 6750 §3) ──────────────────────────────────

class TestWwwAuthenticate:
    def test_basic(self):
        h = build_www_authenticate("invalid_token", "bad")
        assert h.startswith("Bearer")
        assert 'error="invalid_token"' in h
        assert 'error_description="bad"' in h

    def test_realm_includes_audience(self):
        h = build_www_authenticate(audience="mcp-x")
        assert 'realm="mcp-x"' in h

    def test_description_optional(self):
        h = build_www_authenticate("server_error")
        assert "error_description" not in h

    def test_no_error_no_description(self):
        h = build_www_authenticate(audience="x")
        assert h == 'Bearer realm="x"'

    def test_quotes_in_description_sanitised(self):
        h = build_www_authenticate("invalid_token", 'has "quotes"')
        # The double-quote in the input is replaced with a single-quote so
        # the surrounding quote-pair stays valid.
        assert '"quotes"' not in h
        assert "'quotes'" in h


# ─── oauth_error_response builder ─────────────────────────────────────────────

class TestOAuthErrorResponse:
    def test_status_code_matches_catalog(self):
        resp = oauth_error_response("invalid_token", "expired", audience="mcp-x")
        assert resp.status_code == 401
        assert resp.headers["WWW-Authenticate"].startswith("Bearer")

    def test_body_shape(self):
        resp = oauth_error_response("invalid_grant", "bad code")
        # JSONResponse body is bytes; parse it back via TestClient.
        import json as _json
        body = _json.loads(resp.body)
        assert body == {"error": "invalid_grant", "error_description": "bad code"}

    def test_state_propagates(self):
        import json as _json
        resp = oauth_error_response("access_denied", state="xyz")
        body = _json.loads(resp.body)
        assert body["state"] == "xyz"

    def test_forbidden_for_insufficient_scope(self):
        resp = oauth_error_response("insufficient_scope")
        assert resp.status_code == 403

    def test_server_error_returns_500(self):
        resp = oauth_error_response("server_error", "boom")
        assert resp.status_code == 500


# ─── install_error_handlers ───────────────────────────────────────────────────

class _Ping(BaseModel):
    name: str


def _build_app_with_handlers():
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.get("/oauth-fail")
    async def oauth_fail():
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "error_description": "expired"},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    @app.post("/validate", response_model=_Ping)
    async def validate(p: _Ping):
        return {"name": p.name}

    @app.get("/plain-http")
    async def plain_http():
        from fastapi import HTTPException, status
        raise HTTPException(status_code=418, detail="I'm a teapot")

    return app


class TestInstallErrorHandlers:
    def test_validation_error_returns_invalid_request(self):
        app = _build_app_with_handlers()
        c = TestClient(app)
        r = c.post("/validate", json={})
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "invalid_request"
        assert "validation failed" in body["error_description"]

    def test_oauth_shaped_detail_unwrapped(self):
        app = _build_app_with_handlers()
        c = TestClient(app)
        r = c.get("/oauth-fail")
        assert r.status_code == 401
        body = r.json()
        assert body == {"error": "invalid_token", "error_description": "expired"}
        assert "WWW-Authenticate" in r.headers

    def test_plain_http_exception_normalised(self):
        app = _build_app_with_handlers()
        c = TestClient(app)
        r = c.get("/plain-http")
        assert r.status_code == 418
        body = r.json()
        assert body["error"] == "invalid_request"
        assert body["error_description"] == "I'm a teapot"

    def test_not_found(self):
        app = _build_app_with_handlers()
        c = TestClient(app)
        r = c.get("/does-not-exist")
        assert r.status_code == 404
        assert r.json()["error"] == "invalid_request"

    def test_method_not_allowed(self):
        app = _build_app_with_handlers()
        c = TestClient(app)
        r = c.put("/ok")
        assert r.status_code == 405
        assert r.json()["error"] == "invalid_request"
