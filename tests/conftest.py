"""Shared test fixtures for mcp_service."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import httpx
import pytest

# Force safe test defaults BEFORE any module reads config. We use direct
# assignment (not setdefault) so leaked shell env vars are overridden.
os.environ["OAUTH_ENABLED"] = "true"
os.environ["OAUTH_AUTO_APPROVE"] = "true"
os.environ["OAUTH_VERIFY_SIGNATURE"] = "false"
os.environ["MCP_REQUIRE_AUTH"] = "false"
os.environ["MCP_API_KEY"] = ""
os.environ["OAUTH_SUPPORTED_SCOPES"] = "mcp:read mcp:write mcp:admin"


@pytest.fixture()
def tmp_oauth_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect OAUTH_STORAGE_DIR to a fresh temp directory per test."""
    import mcp_service.config as config_mod

    config_mod._config = None
    d = Path(tempfile.mkdtemp(prefix="mcp_oauth_"))
    monkeypatch.setenv("OAUTH_STORAGE_DIR", str(d))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def reset_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset the cached AppConfig between tests so env changes take effect."""
    import mcp_service.config as config_mod

    config_mod._config = None
    yield
    config_mod._config = None


@pytest.fixture()
def reset_token_store() -> Iterator[None]:
    """Drop the singleton token store so each test gets a fresh instance."""
    import mcp_service.oauth.storage as storage_mod

    storage_mod._code_store = None
    storage_mod._token_store = None
    storage_mod._client_store = None
    yield
    storage_mod._code_store = None
    storage_mod._token_store = None
    storage_mod._client_store = None


@pytest.fixture()
def reset_validator() -> Iterator[None]:
    """Drop the cached TokenValidator singleton."""
    import mcp_service.oauth.middleware as mw

    mw._validator = None
    yield
    mw._validator = None


@pytest.fixture()
def app_config(tmp_oauth_dir, reset_config):
    """Provide a freshly built AppConfig pointing at a temp storage dir."""
    from mcp_service.config import get_config

    return get_config()


@pytest.fixture()
def handler():
    """Default JSON-RPC handler used by app/mcp tests."""

    def _handler(request: dict):
        method = request.get("method")
        req_id = request.get("id")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test", "version": "0.0.1"},
                },
            }
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}}
        if method == "notifications/initialized":
            return None
        if method == "raise":
            raise RuntimeError("handler exploded")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"},
        }

    return _handler


@pytest.fixture()
def app(handler, tmp_oauth_dir, reset_config, reset_token_store, reset_validator):
    """A FastAPI app instance with OAuth enabled and a default handler."""
    from mcp_service import create_app

    return create_app(handler, title="test-server")


@pytest.fixture()
async def client(app):
    """httpx.AsyncClient backed by an in-process ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()