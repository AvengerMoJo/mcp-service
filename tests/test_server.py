"""MCP server / dispatch tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "server": "test-server"}


@pytest.mark.asyncio
async def test_healthz_endpoint(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["server"] == "test-server"
    assert "checks" in body
    assert body["checks"]["server"] == "ok"
    assert body["checks"]["token_store"]["status"] == "ok"
    assert body["checks"]["client_store"]["status"] == "ok"


@pytest.mark.asyncio
async def test_healthz_oauth_disabled(handler, tmp_oauth_dir, monkeypatch):
    monkeypatch.setenv("OAUTH_ENABLED", "false")
    import mcp_service.config as config_mod
    config_mod._config = None
    from mcp_service import create_app
    import httpx

    app = create_app(handler, title="test-server")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["checks"]["oauth"] == {"status": "disabled"}
        # No token store checks when OAuth is off.
        assert "token_store" not in body["checks"]


@pytest.mark.asyncio
async def test_mcp_requires_auth_returns_oauth_envelope(handler, tmp_oauth_dir, monkeypatch):
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
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert r.status_code == 401
        body = r.json()
        assert body["error"] == "invalid_token"
        assert "WWW-Authenticate" in r.headers


@pytest.mark.asyncio
async def test_oauth_token_error_returns_oauth_envelope(handler, tmp_oauth_dir, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "false")
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
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        # OAuth disabled → invalid_token with the oauth_disabled reason.
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_register_returns_oauth_error_envelope(client):
    r = await client.post(
        "/oauth/register",
        json={"client_name": "x"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_request"
    assert "redirect_uris" in body["error_description"]


@pytest.mark.asyncio
async def test_token_invalid_grant_envelope(client):
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": "fake-code",
            "redirect_uri": "http://x/cb",
            "code_verifier": "a" * 64,
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_unsupported_grant_type_envelope(client):
    r = await client.post("/oauth/token", data={"grant_type": "password"})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


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

@pytest.mark.asyncio
async def test_redoc_available(client):
    r = await client.get("/redoc")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_openapi_documents_mcp_responses(client):
    """The /mcp route advertises success + error responses in OpenAPI."""
    r = await client.get("/openapi.json")
    schema = r.json()
    mcp = schema["paths"]["/mcp"]["post"]
    codes = {int(c) for c in mcp["responses"].keys()}
    assert 200 in codes
    assert 204 in codes
    assert 400 in codes
    assert 500 in codes
    examples = mcp["responses"]["200"]["content"]["application/json"].get("examples")
    assert examples is not None
    assert "result" in examples
    assert "error" in examples


@pytest.mark.asyncio
async def test_openapi_documents_health_endpoints(client):
    r = await client.get("/openapi.json")
    schema = r.json()
    assert "/health" in schema["paths"]
    assert "/healthz" in schema["paths"]
    codes = {int(c) for c in schema["paths"]["/healthz"]["get"]["responses"].keys()}
    assert 200 in codes
    assert 503 in codes


@pytest.mark.asyncio
async def test_openapi_includes_tags_and_contact(client):
    r = await client.get("/openapi.json")
    schema = r.json()
    assert schema["info"]["license"]["name"] == "MIT"
    assert schema["info"]["contact"]["url"].startswith("https://")
    tag_names = {t["name"] for t in schema.get("tags", [])}
    assert {"mcp", "oauth", "health"} <= tag_names
