"""Server-level edge cases — healthz failures, discovery variants, CLI entry.

These tests cover the small handful of statements still uncovered in
``mcp_service.server`` after the core suite runs:

* healthz degrades to 503 when the token / client store raises
* ``/.well-known/mcp.json`` surfaces the API-key scheme when ``MCP_API_KEY`` is set
* ``run()`` defers to uvicorn (patched so it doesn't actually bind)
* ``main()`` resolves ``MCP_HANDLER`` from the environment and falls back to
  ``example.main:handler`` when unset
* ``main()`` raises ``SystemExit`` with a helpful message on bad handler paths
* handler ``teardown`` errors are logged but do not propagate (line 98-99)
"""

from __future__ import annotations

import logging
import sys

import pytest


# ─── healthz failure paths ────────────────────────────────────────────────────


class TestHealthzFailures:
    @pytest.mark.asyncio
    async def test_token_store_failure_reports_503(self, client, monkeypatch):
        import mcp_service.server as server_mod

        def _broken():
            raise RuntimeError("disk full")

        monkeypatch.setattr(server_mod, "get_token_store", _broken)
        r = await client.get("/healthz")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["token_store"]["status"] == "error"
        assert "disk full" in body["checks"]["token_store"]["detail"]
        # client_store is still ok in this test (only token_store broken).
        assert body["checks"]["client_store"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_client_store_failure_reports_503(self, client, monkeypatch):
        import mcp_service.server as server_mod

        def _broken():
            raise RuntimeError("clients gone")

        monkeypatch.setattr(server_mod, "get_client_registration_store", _broken)
        r = await client.get("/healthz")
        assert r.status_code == 503
        body = r.json()
        assert body["checks"]["client_store"]["status"] == "error"
        assert "clients gone" in body["checks"]["client_store"]["detail"]


# ─── Discovery: api-key scheme + api-key only ────────────────────────────────


class TestDiscoveryApiKey:
    @pytest.mark.asyncio
    async def test_api_key_scheme_listed_when_configured(
        self, tmp_oauth_dir, reset_config, reset_token_store, reset_validator
    ):
        import mcp_service.config as config_mod

        config_mod._config = None
        from mcp_service import create_app
        import httpx

        def h(req):
            return {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}

        monkeypatch_api_key = "test-key"
        import os as _os
        _os.environ["MCP_API_KEY"] = monkeypatch_api_key

        app = create_app(h, title="t")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r = await c.get("/.well-known/mcp.json")
            assert r.status_code == 200
            body = r.json()
            schemes = body["auth"]["schemes"]
            api_key_scheme = next(s for s in schemes if s["type"] == "api-key")
            assert api_key_scheme["header"] == "MCP-API-Key"
        _os.environ.pop("MCP_API_KEY", None)


# ─── run() — patched uvicorn so no socket is opened ──────────────────────────


class TestRunFunction:
    def test_run_invokes_uvicorn(self, monkeypatch):
        """``run`` should call ``uvicorn.run(app, host=..., port=..., log_level=...)``."""
        import uvicorn

        captured: dict = {}

        def _fake_run(app, host, port, log_level):
            captured["app"] = app
            captured["host"] = host
            captured["port"] = port
            captured["log_level"] = log_level

        monkeypatch.setattr(uvicorn, "run", _fake_run)

        from mcp_service import run as svc_run

        def h(req):
            return {}

        svc_run(h, host="127.0.0.1", port=9999, title="test")
        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 9999
        assert captured["log_level"] == "info"
        # The app returned should be the FastAPI instance from create_app.
        from fastapi import FastAPI
        assert isinstance(captured["app"], FastAPI)

    def test_run_uses_configured_port_when_unspecified(self, monkeypatch):
        import uvicorn

        captured: dict = {}

        def _fake_run(app, host, port, log_level):
            captured["port"] = port

        monkeypatch.setattr(uvicorn, "run", _fake_run)

        from mcp_service import run as svc_run
        from mcp_service.config import get_config
        cfg = get_config()
        cfg.port = 5555

        svc_run(lambda r: {})
        assert captured["port"] == 5555


# ─── main() CLI entry ─────────────────────────────────────────────────────────


class TestMainCli:
    def test_main_resolves_mcp_handler_env(self, monkeypatch):
        """``main()`` imports the module referenced by ``MCP_HANDLER``."""
        import uvicorn

        captured: dict = {}
        monkeypatch.setattr(uvicorn, "run",
                            lambda app, host, port, log_level: captured.setdefault("ran", True))

        def _h(req):
            return {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}

        # Provide a handler via MCP_HANDLER — use example.main which exists.
        monkeypatch.setenv("MCP_HANDLER", "example.main:handler")
        from mcp_service.server import main
        main()
        assert captured.get("ran") is True

    def test_main_falls_back_to_example_when_unset(self, monkeypatch):
        import uvicorn

        captured: dict = {}
        monkeypatch.setattr(uvicorn, "run",
                            lambda app, host, port, log_level: captured.setdefault("ran", True))
        monkeypatch.delenv("MCP_HANDLER", raising=False)

        from mcp_service.server import main
        main()
        assert captured.get("ran") is True

    def test_main_exits_on_missing_colon(self, monkeypatch):
        monkeypatch.setenv("MCP_HANDLER", "no_colon_here")
        from mcp_service.server import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert "must be of the form" in str(exc_info.value)

    def test_main_exits_on_unimportable_module(self, monkeypatch):
        monkeypatch.setenv("MCP_HANDLER", "no_such_module_xyz:fn")
        from mcp_service.server import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert "Could not import" in str(exc_info.value)

    def test_main_exits_when_attribute_missing(self, monkeypatch):
        monkeypatch.setenv("MCP_HANDLER", "sys:no_such_attr_xyz123")
        from mcp_service.server import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert "no attribute" in str(exc_info.value)


# ─── handler teardown error path ──────────────────────────────────────────────


class TestHandlerTeardownError:
    @pytest.mark.asyncio
    async def test_teardown_exception_logged_not_raised(self, caplog):
        from mcp_service import MCPHandler, create_app

        class H(MCPHandler):
            async def teardown(self):
                raise RuntimeError("teardown blew up")

        app = create_app(H())
        with caplog.at_level(logging.ERROR, logger="mcp_service.server"):
            async with app.router.lifespan_context(app):
                pass
        # ``_log.exception`` writes "handler.teardown() failed" + the
        # exception in the traceback. Verify both the log record and the
        # exception info are present.
        assert any("handler.teardown() failed" in rec.getMessage()
                   for rec in caplog.records)
        assert any(rec.exc_info is not None
                   and "teardown blew up" in str(rec.exc_info[1])
                   for rec in caplog.records)


# ─── Discovery: schemes include bearer only when api key unset ───────────────


class TestDiscoverySchemes:
    @pytest.mark.asyncio
    async def test_only_bearer_when_no_api_key(self, client):
        body = (await client.get("/.well-known/mcp.json")).json()
        scheme_types = {s["type"] for s in body["auth"]["schemes"]}
        assert "bearer" in scheme_types
        # No api-key scheme unless MCP_API_KEY is set
        assert "api-key" not in scheme_types