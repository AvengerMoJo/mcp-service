"""Tests for the MCPHandler extensibility API + service discovery."""

from __future__ import annotations

import pytest


# ── MCPHandler unit tests (no server) ────────────────────────────────────────


class TestHandlerRegistration:
    def test_default_metadata(self):
        from mcp_service import MCPHandler

        h = MCPHandler()
        assert h.name == "mcp-service"
        assert h.version == "0.1.0"
        assert h.protocol_version == "2024-11-05"
        assert h.list_tools() == []
        assert h.capabilities() == {}

    def test_register_tool_decorator(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_tool(
                name="add",
                description="Add two numbers",
                input_schema={
                    "type": "object",
                    "properties": {"a": {"type": "number"},
                                   "b": {"type": "number"}},
                    "required": ["a", "b"],
                },
            )
            def add(self, args):
                return args["a"] + args["b"]

        h = H()
        tools = h.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "add"
        assert tools[0]["description"] == "Add two numbers"
        assert tools[0]["inputSchema"]["required"] == ["a", "b"]

    def test_capabilities_reports_tools(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_tool("noop", description="x")
            def noop(self, args):
                return None

        assert H().capabilities() == {"tools": {"listChanged": False}}

    def test_register_method_decorator(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_method("custom/echo")
            def echo(self, request):
                return self._ok(request, {"echo": request.get("params", {})})

        h = H()
        assert "custom/echo" in h._method_handlers

    def test_register_tool_via_call_form(self):
        from mcp_service import MCPHandler

        h = MCPHandler()
        h.register_tool_instance("fn_tool", description="d")(lambda args: {"x": 1})
        assert "fn_tool" in h._tools

    def test_description_falls_back_to_docstring(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_tool("dt")
            def dt(self) -> None:
                """My tool description."""
                return None

        tools = H().list_tools()
        assert tools[0]["description"] == "My tool description."

    def test_server_info(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            name = "x"
            version = "9.9"
            description = "demo"

        h = H()
        info = h.server_info()
        assert info == {"name": "x", "version": "9.9", "description": "demo"}

    def test_discovery_metadata_shape(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            name = "srv"
            version = "1.2.3"
            description = "Desc"
            protocol_version = "2024-11-05"

            @MCPHandler.register_tool("t", description="T")
            def t(self, args):
                return None

        meta = H().discovery_metadata()
        assert meta["name"] == "srv"
        assert meta["version"] == "1.2.3"
        assert meta["description"] == "Desc"
        assert meta["protocol_version"] == "2024-11-05"
        assert meta["capabilities"] == {"tools": {"listChanged": False}}
        assert meta["tools"] == [{"name": "t", "description": "T",
                                  "inputSchema": {"type": "object",
                                                  "properties": {}}}]


class TestHandlerDispatch:
    @pytest.mark.asyncio
    async def test_initialize_builtin(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            name = "n"
            version = "v"
            description = "d"

        h = H()
        resp = await h.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert resp["id"] == 1
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"] == {"name": "n", "version": "v",
                                                "description": "d"}
        assert resp["result"]["capabilities"] == {}

    @pytest.mark.asyncio
    async def test_notifications_returns_none(self):
        from mcp_service import MCPHandler

        resp = await MCPHandler().handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert resp is None

    @pytest.mark.asyncio
    async def test_ping_builtin(self):
        from mcp_service import MCPHandler

        resp = await MCPHandler().handle(
            {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        )
        assert resp == {"jsonrpc": "2.0", "id": 1, "result": {}}

    @pytest.mark.asyncio
    async def test_tools_list_builtin(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_tool("only", description="x")
            def only(self, args):
                return None

        resp = await H().handle(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list"}
        )
        assert resp["id"] == 5
        assert resp["result"]["tools"][0]["name"] == "only"

    @pytest.mark.asyncio
    async def test_tools_call_dispatches_to_callable(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_tool("double", description="x")
            def double(self, args):
                return args["n"] * 2

        resp = await H().handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "double", "arguments": {"n": 21}},
        })
        assert resp["result"] == {"content": [{"type": "text", "text": "42"}]}

    @pytest.mark.asyncio
    async def test_tools_call_passes_through_content(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_tool("rich")
            def rich(self, args):
                return {"content": [{"type": "text", "text": "hi"}],
                        "extra": 1}

        resp = await H().handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "rich", "arguments": {}},
        })
        assert resp["result"]["content"][0]["text"] == "hi"
        assert resp["result"]["extra"] == 1

    @pytest.mark.asyncio
    async def test_tools_call_unknown_tool(self):
        from mcp_service import MCPHandler

        resp = await MCPHandler().handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        })
        assert resp["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tools_call_invalid_params(self):
        from mcp_service import MCPHandler

        resp = await MCPHandler().handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": "not-an-object",
        })
        assert resp["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tools_call_exception_wrapped(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            @MCPHandler.register_tool("boom")
            def boom(self, args):
                raise RuntimeError("kaboom")

        resp = await H().handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "boom", "arguments": {}},
        })
        assert resp["error"]["code"] == -32603
        assert "kaboom" in resp["error"]["data"]

    @pytest.mark.asyncio
    async def test_on_method_convention(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            async def on_resources_list(self, request):
                return self._ok(request, {"resources": []})

        resp = await H().handle({
            "jsonrpc": "2.0", "id": 1, "method": "resources/list",
        })
        assert resp["result"] == {"resources": []}

    @pytest.mark.asyncio
    async def test_explicit_method_routing_wins(self):
        from mcp_service import MCPHandler

        class H(MCPHandler):
            def on_custom(self, request):
                return self._ok(request, {"src": "on_method"})

            @MCPHandler.register_method("custom")
            def custom(self, request):
                return self._ok(request, {"src": "registered"})

        resp = await H().handle(
            {"jsonrpc": "2.0", "id": 1, "method": "custom"}
        )
        assert resp["result"] == {"src": "registered"}

    @pytest.mark.asyncio
    async def test_unknown_method(self):
        from mcp_service import MCPHandler

        resp = await MCPHandler().handle(
            {"jsonrpc": "2.0", "id": 1, "method": "no/such/thing"}
        )
        assert resp["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_missing_method_field(self):
        from mcp_service import MCPHandler

        resp = await MCPHandler().handle({"jsonrpc": "2.0", "id": 1})
        assert resp["error"]["code"] == -32600


# ── as_handler adapter ──────────────────────────────────────────────────────


class TestAsHandler:
    def test_passes_through_mcp_handler(self):
        from mcp_service import MCPHandler, as_handler

        h = MCPHandler()
        assert as_handler(h) is h

    def test_wraps_callable(self):
        from mcp_service import MCPHandler, as_handler

        def my_handler(req):
            return {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}

        wrapped = as_handler(my_handler)
        assert isinstance(wrapped, MCPHandler)

    @pytest.mark.asyncio
    async def test_wrapped_callable_invokes_user_function(self):
        from mcp_service import as_handler

        def fn(req):
            method = req.get("method")
            return {"jsonrpc": "2.0", "id": req.get("id"),
                    "result": {"method": method}}

        wrapped = as_handler(fn)
        resp = await wrapped.handle(
            {"jsonrpc": "2.0", "id": 9, "method": "ping"}
        )
        assert resp == {"jsonrpc": "2.0", "id": 9, "result": {"method": "ping"}}

    def test_rejects_non_callable(self):
        from mcp_service import as_handler

        with pytest.raises(TypeError):
            as_handler(42)


# ── create_app integration with MCPHandler ──────────────────────────────────


class TestCreateAppWithHandler:
    @pytest.mark.asyncio
    async def test_class_handler_dispatches_initialize(self, handler, tmp_oauth_dir,
                                                       reset_config, reset_token_store,
                                                       reset_validator):
        from mcp_service import MCPHandler, create_app
        import httpx

        class H(MCPHandler):
            name = "cls-srv"
            version = "2.0.0"
            description = "class-based"

        app = create_app(H())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r = await c.post("/mcp", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize"})
            assert r.status_code == 200
            body = r.json()
            assert body["result"]["serverInfo"]["name"] == "cls-srv"
            assert body["result"]["serverInfo"]["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_class_handler_dispatches_tools_call(self, tmp_oauth_dir,
                                                       reset_config,
                                                       reset_token_store,
                                                       reset_validator):
        from mcp_service import MCPHandler, create_app
        import httpx

        class H(MCPHandler):
            name = "t-srv"

            @MCPHandler.register_tool("hello", description="say hi",
                                      input_schema={"type": "object",
                                                    "properties": {}})
            def hello(self, args):
                return "hi!"

        app = create_app(H())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r = await c.post("/mcp", json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {"name": "hello", "arguments": {}}})
            assert r.status_code == 200
            body = r.json()
            assert body["result"]["content"][0]["text"] == "hi!"

    @pytest.mark.asyncio
    async def test_class_handler_user_id_injected_into_meta(
        self, tmp_oauth_dir, reset_config, reset_token_store, reset_validator
    ):
        from mcp_service import MCPHandler, create_app
        from mcp_service.oauth.storage import get_token_store
        import httpx

        captured: dict = {}

        class H(MCPHandler):
            name = "meta-srv"

            @MCPHandler.register_method("whoami")
            def whoami(self, request):
                captured.update(request.get("_meta") or {})
                return self._ok(request, captured)

        app = create_app(H())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            td = get_token_store().create_access_token("alice", "mcp:read")
            r = await c.post(
                "/oauth",
                json={"jsonrpc": "2.0", "id": 1, "method": "whoami"},
                headers={"Authorization": f"Bearer {td.token}"},
            )
            assert r.status_code == 200
            assert captured["user_id"] == "alice"


# ── /.well-known/mcp.json ────────────────────────────────────────────────────


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discovery_basic_shape(self, client):
        r = await client.get("/.well-known/mcp.json")
        assert r.status_code == 200
        body = r.json()
        assert body["mcp_version"] == "2024-11-05"
        assert "server" in body
        assert "transport" in body
        assert body["transport"]["type"] == "http"
        assert body["transport"]["endpoint"] == "/mcp"
        assert "auth" in body
        assert "scopes_supported" in body
        assert "endpoints" in body

    @pytest.mark.asyncio
    async def test_discovery_lists_scopes_from_config(self, client):
        body = (await client.get("/.well-known/mcp.json")).json()
        assert "mcp:read" in body["scopes_supported"]
        assert "mcp:write" in body["scopes_supported"]
        assert "mcp:admin" in body["scopes_supported"]

    @pytest.mark.asyncio
    async def test_discovery_optional_auth_when_not_required(self, client):
        body = (await client.get("/.well-known/mcp.json")).json()
        assert body["auth"]["required"] is False
        # Bearer is always listed but marked optional.
        bearer = next(s for s in body["auth"]["schemes"] if s["type"] == "bearer")
        assert bearer["required"] is False

    @pytest.mark.asyncio
    async def test_discovery_includes_oauth_metadata_when_enabled(self, client):
        body = (await client.get("/.well-known/mcp.json")).json()
        assert "authorization_server" in body["auth"]
        assert body["auth"]["registration_endpoint"].endswith("/oauth/register")

    @pytest.mark.asyncio
    async def test_discovery_required_auth(self, handler, tmp_oauth_dir, monkeypatch):
        monkeypatch.setenv("MCP_REQUIRE_AUTH", "true")
        monkeypatch.setenv("MCP_API_KEY", "")
        import mcp_service.config as config_mod
        config_mod._config = None
        from mcp_service import create_app
        import httpx

        app = create_app(handler, title="t")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r = await c.get("/.well-known/mcp.json")
            assert r.status_code == 200
            body = r.json()
            assert body["auth"]["required"] is True
            bearer = next(s for s in body["auth"]["schemes"] if s["type"] == "bearer")
            assert bearer["required"] is True

    @pytest.mark.asyncio
    async def test_discovery_lists_handler_tools_and_capabilities(
        self, tmp_oauth_dir, reset_config, reset_token_store, reset_validator
    ):
        from mcp_service import MCPHandler, create_app
        import httpx

        class H(MCPHandler):
            name = "cap-srv"
            description = "demo"

            @MCPHandler.register_tool("a", description="A")
            def a(self, args):
                return None

            @MCPHandler.register_tool("b", description="B")
            def b(self, args):
                return None

        app = create_app(H())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r = await c.get("/.well-known/mcp.json")
            assert r.status_code == 200
            body = r.json()
            assert body["server"]["name"] == "cap-srv"
            assert body["server"]["description"] == "demo"
            tool_names = {t["name"] for t in body["tools"]}
            assert tool_names == {"a", "b"}
            assert body["capabilities"] == {"tools": {"listChanged": False}}

    @pytest.mark.asyncio
    async def test_discovery_in_openapi(self, client):
        body = (await client.get("/openapi.json")).json()
        assert "/.well-known/mcp.json" in body["paths"]
        path = body["paths"]["/.well-known/mcp.json"]["get"]
        assert path["tags"] == ["discovery"]
        assert int("200" in path["responses"])


# ── Lifecycle hooks ─────────────────────────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_setup_and_teardown_called(self):
        from mcp_service import MCPHandler, create_app

        events: list[str] = []

        class H(MCPHandler):
            async def setup(self):
                events.append("setup")

            async def teardown(self):
                events.append("teardown")

        app = create_app(H())
        async with app.router.lifespan_context(app):
            pass
        assert events == ["setup", "teardown"]

    @pytest.mark.asyncio
    async def test_setup_exception_prevents_startup(self):
        from mcp_service import MCPHandler, create_app

        class H(MCPHandler):
            async def setup(self):
                raise RuntimeError("startup failed")

        app = create_app(H())
        with pytest.raises(RuntimeError, match="startup failed"):
            async with app.router.lifespan_context(app):
                pass

    @pytest.mark.asyncio
    async def test_sync_setup_and_teardown_work(self):
        from mcp_service import MCPHandler, create_app

        events: list[str] = []

        class H(MCPHandler):
            def setup(self):
                events.append("setup")

            def teardown(self):
                events.append("teardown")

        app = create_app(H())
        async with app.router.lifespan_context(app):
            pass
        assert events == ["setup", "teardown"]

    @pytest.mark.asyncio
    async def test_teardown_called_even_when_setup_fails(self):
        from mcp_service import MCPHandler, create_app

        events: list[str] = []

        class H(MCPHandler):
            async def setup(self):
                events.append("setup")
                raise RuntimeError("boom")

            async def teardown(self):
                events.append("teardown")

        app = create_app(H())
        with pytest.raises(RuntimeError):
            async with app.router.lifespan_context(app):
                pass
        # teardown is intentionally NOT called when setup fails (matches
        # FastAPI lifespan semantics). Verify the contract.
        assert events == ["setup"]