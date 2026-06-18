"""MCP server / dispatch tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "server": "test-server"}


@pytest.mark.asyncio
async def test_mcp_initialize(client):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert body["result"]["protocolVersion"] == "2024-11-05"


@pytest.mark.asyncio
async def test_mcp_tools_list(client):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
    )
    assert r.status_code == 200
    assert r.json()["result"] == {"tools": []}


@pytest.mark.asyncio
async def test_mcp_notification_returns_204(client):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_mcp_unknown_method_returns_error(client):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "no/such", "params": {}},
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_mcp_handler_exception_wrapped(client):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 9, "method": "raise", "params": {}},
    )
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == -32603


@pytest.mark.asyncio
async def test_mcp_invalid_json_returns_parse_error(client):
    r = await client.post(
        "/mcp",
        content="{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_mcp_non_jsonrpc_returns_invalid_request(client):
    r = await client.post("/mcp", json={"foo": "bar"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_mcp_accepts_root_path(client):
    r = await client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_mcp_get_returns_transport_info(client):
    r = await client.get("/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["transport"] == "http"


@pytest.mark.asyncio
async def test_mcp_requires_auth_when_enabled(handler, tmp_oauth_dir, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "true")
    monkeypatch.setenv("MCP_API_KEY", "")
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
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers


@pytest.mark.asyncio
async def test_mcp_api_key_passes_auth(handler, tmp_oauth_dir, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "true")
    monkeypatch.setenv("MCP_API_KEY", "k")
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
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"MCP-API-Key": "k"},
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_oauth_endpoint_requires_token(client):
    r = await client.post("/oauth", json={"jsonrpc": "2.0", "id": 1, "method": "x"})
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


@pytest.mark.asyncio
async def test_oauth_endpoint_accepts_token(client):
    from mcp_service.oauth.storage import get_token_store

    td = get_token_store().create_access_token("test-client", "mcp:read")
    r = await client.post(
        "/oauth",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Authorization": f"Bearer {td.token}"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_openapi_schema_available(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "test-server"
    assert "/mcp" in schema["paths"]


@pytest.mark.asyncio
async def test_docs_swagger_ui(client):
    r = await client.get("/docs")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]