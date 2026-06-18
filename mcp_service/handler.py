"""
Extensible MCP handler base class.

A :class:`MCPHandler` subclass gets:

* **Method dispatch** — ``async def on_<method>`` style methods handle
  ``tools/list``, ``tools/call``, custom methods, etc.
* **Tool registration** — ``@handler.register_tool`` decorator or
  ``handler.register_tool(...)(fn)`` direct call.  Schemas and callables
  live on the handler, so ``tools/list`` and ``tools/call`` are answered
  automatically.
* **Lifecycle hooks** — override :meth:`setup` / :meth:`teardown` to open
  database connections, warm caches, etc.
* **Discovery metadata** — ``name`` / ``version`` / ``description`` /
  ``protocol_version`` are surfaced through ``/.well-known/mcp.json``.

Plain function handlers remain fully supported — they are wrapped in a
lightweight :class:`_FunctionHandler` adapter so the dispatch path is
identical for both styles.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Optional, Union

JSON_RPC_VERSION = "2.0"

# JSON-RPC standard error codes (https://www.jsonrpc.org/specification)
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

# Sentinel attributes attached to functions by the @register_tool /
# @register_method decorators.  ``__init__`` walks the class MRO and picks
# them up — this works for any class, including ones defined inside test
# functions.
_TOOL_ATTR = "__mcp_tool__"
_METHOD_ATTR = "__mcp_method__"


def _maybe_await(value: Any) -> Awaitable[Any]:
    """Coerce a sync return value into an awaitable (for ``await``)."""
    if inspect.isawaitable(value):
        return value
    async def _wrap():
        return value
    return _wrap()


def _method_not_found(req_id: Any, method: str) -> dict:
    return {
        "jsonrpc": JSON_RPC_VERSION,
        "id": req_id,
        "error": {"code": JSONRPC_METHOD_NOT_FOUND,
                  "message": f"Method not found: {method}"},
    }


class MCPHandler:
    """
    Base class for pluggable MCP handlers.

    Subclass to expose your server's identity and tools:

        from mcp_service import MCPHandler, run

        class WeatherHandler(MCPHandler):
            name = "weather-mcp"
            version = "1.0.0"
            description = "Read-only weather lookup"
            protocol_version = "2024-11-05"

            @MCPHandler.register_tool(
                name="get_weather",
                description="Get current weather for a city",
                input_schema={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            )
            def get_weather(self, args: dict) -> dict:
                return {"content": [{"type": "text",
                                     "text": f"Sunny in {args['city']}"}]}

        if __name__ == "__main__":
            run(WeatherHandler())

    The handler is invoked by the dispatch loop.  Override :meth:`handle`
    for full control, or rely on the default dispatcher which:

      1. Routes to a method registered via :meth:`register_method`.
      2. Routes to an ``on_<method>`` method on the instance.
      3. Answers ``initialize``, ``notifications/initialized``,
         ``tools/list``, ``tools/call`` built-ins.
      4. Returns a JSON-RPC ``method not found`` error otherwise.
    """

    name: str = "mcp-service"
    version: str = "0.1.0"
    description: str = ""
    protocol_version: str = "2024-11-05"

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}
        self._method_handlers: dict[str, Callable[..., Any]] = {}
        # Walk the MRO so subclasses inherit parent registrations.
        seen: set[str] = set()
        for klass in type(self).__mro__:
            for attr_name, attr_value in vars(klass).items():
                if attr_name in seen:
                    continue
                seen.add(attr_name)
                tool_meta = getattr(attr_value, _TOOL_ATTR, None)
                if tool_meta is not None and callable(attr_value):
                    # Bind the descriptor to ``self`` so ``def tool(self, args)``
                    # receives the handler as the first argument.
                    bound = attr_value.__get__(self, type(self))
                    self._tools[tool_meta["name"]] = {
                        "name": tool_meta["name"],
                        "description": tool_meta["description"],
                        "inputSchema": tool_meta["inputSchema"],
                        "callable": bound,
                    }
                method_meta = getattr(attr_value, _METHOD_ATTR, None)
                if method_meta is not None and callable(attr_value):
                    bound = attr_value.__get__(self, type(self))
                    self._method_handlers[method_meta] = bound

    # ── registration API ────────────────────────────────────────────────────

    @staticmethod
    def register_tool(
        name: str,
        description: str = "",
        input_schema: Optional[dict] = None,
    ) -> Callable[[Callable], Callable]:
        """
        Decorator that registers a tool on the enclosing :class:`MCPHandler`.

        Use as a class-body decorator::

            class H(MCPHandler):
                @MCPHandler.register_tool("ping", description="Pong")
                def ping(self, args): ...

        Instances see the tool via :meth:`list_tools` and
        :meth:`capabilities` automatically.
        """
        schema = input_schema or {"type": "object", "properties": {}}

        def decorator(fn: Callable) -> Callable:
            setattr(fn, _TOOL_ATTR, {
                "name": name,
                "description": description or (fn.__doc__ or "").strip(),
                "inputSchema": schema,
            })
            return fn

        return decorator

    def register_tool_instance(self, name: str, description: str = "",
                                input_schema: Optional[dict] = None,
                                callable: Optional[Callable] = None
                                ) -> Callable[[Callable], Callable]:
        """
        Register a tool on a specific instance — useful when tools are added
        dynamically after construction. Same signature as
        :meth:`register_tool`, but the callable binds to this instance.
        """
        schema = input_schema or {"type": "object", "properties": {}}

        def decorator(fn: Callable) -> Callable:
            self._tools[name] = {
                "name": name,
                "description": description or (fn.__doc__ or "").strip(),
                "inputSchema": schema,
                "callable": fn,
            }
            return fn

        if callable is not None:
            return decorator(callable)
        return decorator

    @staticmethod
    def register_method(method: str) -> Callable[[Callable], Callable]:
        """
        Decorator that binds a JSON-RPC method to a Python callable::

            class H(MCPHandler):
                @MCPHandler.register_method("resources/list")
                def list_resources(self, request):
                    return self._ok(request, {"resources": []})
        """
        def decorator(fn: Callable) -> Callable:
            setattr(fn, _METHOD_ATTR, method)
            return fn

        return decorator

    # ── introspection ──────────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        """Return MCP-formatted tool list (no callables)."""
        return [
            {"name": t["name"],
             "description": t["description"],
             "inputSchema": t["inputSchema"]}
            for t in self._tools.values()
        ]

    def capabilities(self) -> dict:
        """
        Return MCP capabilities for the discovery endpoint and the
        ``initialize`` response.
        """
        caps: dict = {}
        if self._tools:
            caps["tools"] = {"listChanged": False}
        return caps

    def server_info(self) -> dict:
        """Return the ``serverInfo`` block for ``initialize`` responses."""
        info = {"name": self.name, "version": self.version}
        if self.description:
            info["description"] = self.description
        return info

    def discovery_metadata(self) -> dict:
        """Return the metadata block for ``/.well-known/mcp.json``."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "protocol_version": self.protocol_version,
            "capabilities": self.capabilities(),
            "tools": self.list_tools(),
        }

    # ── dispatch ───────────────────────────────────────────────────────────

    async def handle(self, request: dict) -> Optional[dict]:
        """
        Default dispatcher.  Override for custom routing.
        Returns ``None`` for notifications, a response dict otherwise.
        """
        method = request.get("method")
        req_id = request.get("id")

        if not isinstance(method, str):
            return {
                "jsonrpc": JSON_RPC_VERSION,
                "id": req_id,
                "error": {"code": JSONRPC_INVALID_REQUEST,
                          "message": "Missing or invalid 'method'"},
            }

        # 1. explicitly registered method
        if method in self._method_handlers:
            fn = self._method_handlers[method]
            return await _maybe_await(fn(request))

        # 2. on_<method> convention
        snake = "on_" + method.replace("/", "_")
        on_method = getattr(self, snake, None)
        if on_method is not None:
            return await _maybe_await(on_method(request))

        # 3. built-ins
        if method == "initialize":
            return self._builtin_initialize(request)
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self._builtin_ping(request)
        if method == "tools/list":
            return self._builtin_tools_list(request)
        if method == "tools/call":
            return await self._builtin_tools_call(request)

        # 4. fallback
        return _method_not_found(req_id, method)

    # ── lifecycle hooks (overridable) ──────────────────────────────────────

    async def setup(self) -> None:
        """Called once at server startup (FastAPI lifespan)."""

    async def teardown(self) -> None:
        """Called once at server shutdown (FastAPI lifespan)."""

    # ── built-in method answers ────────────────────────────────────────────

    def _ok(self, request: dict, result: Any) -> dict:
        return {"jsonrpc": JSON_RPC_VERSION,
                "id": request.get("id"),
                "result": result}

    def _err(self, request: dict, code: int, message: str,
             data: Any = None) -> dict:
        body = {"code": code, "message": message}
        if data is not None:
            body["data"] = data
        return {"jsonrpc": JSON_RPC_VERSION,
                "id": request.get("id"),
                "error": body}

    def _builtin_initialize(self, request: dict) -> dict:
        return self._ok(request, {
            "protocolVersion": self.protocol_version,
            "capabilities": self.capabilities(),
            "serverInfo": self.server_info(),
        })

    def _builtin_ping(self, request: dict) -> dict:
        return self._ok(request, {})

    def _builtin_tools_list(self, request: dict) -> dict:
        return self._ok(request, {"tools": self.list_tools()})

    async def _builtin_tools_call(self, request: dict) -> dict:
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return self._err(request, JSONRPC_INVALID_PARAMS,
                             "tools/call 'params' must be an object")
        name = params.get("name")
        if not isinstance(name, str) or name not in self._tools:
            return self._err(request, JSONRPC_INVALID_PARAMS,
                             f"Unknown tool: {name!r}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return self._err(request, JSONRPC_INVALID_PARAMS,
                             "'arguments' must be an object")
        tool = self._tools[name]
        try:
            result = await _maybe_await(tool["callable"](args))
        except Exception as e:
            return self._err(request, JSONRPC_INTERNAL_ERROR,
                             f"Tool {name!r} failed",
                             data=str(e))
        if isinstance(result, dict) and "content" in result:
            return self._ok(request, result)
        return self._ok(request, {
            "content": [{"type": "text", "text": str(result)}],
        })


class _FunctionHandler(MCPHandler):
    """Adapter that exposes a plain ``Callable[[dict], Any]`` as an MCPHandler.

    The wrapped function's docstring seeds ``description``; ``name`` is left
    at the base default so callers can keep using the ``title`` parameter to
    ``create_app`` without surprise overrides. The function's qualified name
    is exposed via :attr:`_function_qualname` for logs.
    """

    def __init__(self, fn: Callable[[dict], Any]) -> None:
        super().__init__()
        self._fn = fn
        qual = getattr(fn, "__qualname__", repr(fn))
        self._function_qualname = qual
        doc = (fn.__doc__ or "").strip().split("\n", 1)[0]
        self.description = doc or f"Function handler {qual}"

    async def handle(self, request: dict) -> Optional[dict]:
        return await _maybe_await(self._fn(request))


def as_handler(obj: Union[MCPHandler, Callable[[dict], Any]]) -> MCPHandler:
    """
    Normalise a handler argument into an :class:`MCPHandler`.

    * ``MCPHandler`` → returned unchanged.
    * Plain callable → wrapped in :class:`_FunctionHandler`.
    """
    if isinstance(obj, MCPHandler):
        return obj
    if callable(obj):
        return _FunctionHandler(obj)
    raise TypeError(
        f"handler must be MCPHandler or callable, got {type(obj).__name__}"
    )


__all__ = [
    "MCPHandler",
    "as_handler",
    "JSON_RPC_VERSION",
    "JSONRPC_PARSE_ERROR",
    "JSONRPC_INVALID_REQUEST",
    "JSONRPC_METHOD_NOT_FOUND",
    "JSONRPC_INVALID_PARAMS",
    "JSONRPC_INTERNAL_ERROR",
]