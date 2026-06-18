# mcp-service

> **Reusable MCP HTTP server with OAuth 2.1** — drop in any JSON-RPC handler and get a production-ready, plug-and-play MCP endpoint with dynamic client registration, PKCE, refresh tokens, and OpenAPI docs.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![OAuth 2.1](https://img.shields.io/badge/OAuth-2.1-purple.svg)](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1)

---

## Table of Contents

- [Why mcp-service?](#why-mcp-service)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Class-based handlers (MCPHandler)](#class-based-handlers-mcphandler)
  - [Function handlers](#function-handlers)
  - [Service discovery](#service-discovery)
- [OAuth 2.1 Flow](#oauth-21-flow)
- [Docker](#docker)
- [API Reference](#api-reference)
- [Integration Examples](#integration-examples)
- [Project Structure](#project-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Why mcp-service?

Building an MCP server from scratch is repetitive: OAuth dance, token persistence, PKCE, registration, RFC 8414 metadata, error handling, health checks… `mcp-service` provides all of that as a tested, documented, configurable FastAPI factory.

You write **one function** — a JSON-RPC handler — and `mcp-service` handles everything else:

```python
from mcp_service import run

def my_handler(request: dict) -> dict | None:
    if request["method"] == "tools/list":
        return {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": []}}
    # …

if __name__ == "__main__":
    run(my_handler, title="My MCP Server")
```

That's it. You now have an MCP HTTP server with:

- ✅ OAuth 2.1 Authorization Server (RFC 8414)
- ✅ Dynamic Client Registration (RFC 7591)
- ✅ PKCE / S256 enforcement (RFC 7636)
- ✅ Access + refresh tokens with rotation
- ✅ JWT validation for external IdPs (Google, Auth0, Okta, …)
- ✅ OpenAPI/Swagger docs at `/docs`
- ✅ Health probes at `/health` and `/healthz`
- ✅ Standardized error responses (RFC 6749 + RFC 6750)
- ✅ In-memory token store with JSON persistence
- ✅ Docker-ready multi-stage image

---

## Quick Start

The fastest way to get a working server in under 60 seconds:

### 1. Clone & install

```bash
git clone https://github.com/AvengerMoJo/mcp-service.git
cd mcp-service
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
```

The defaults work out of the box for local development. No edits required.

### 3. Run the example server

```bash
python example/main.py
```

### 4. Verify it's up

```bash
curl http://localhost:8000/health
# → {"status":"ok","server":"Example MCP Server"}
```

### 5. Hit the MCP endpoint

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### 6. Explore the API

Open <http://localhost:8000/docs> in your browser — interactive Swagger UI with every endpoint documented.

---

## Installation

### From source (recommended for development)

```bash
git clone https://github.com/AvengerMoJo/mcp-service.git
cd mcp-service
pip install -e ".[dev]"
```

### From PyPI (planned for v1.0)

```bash
pip install mcp-service
```

### Requirements

- **Python** 3.11 or newer
- **OS** any (Linux, macOS, Windows, containers)
- **Runtime deps** (installed automatically):
  - `fastapi` ≥ 0.110
  - `uvicorn[standard]` ≥ 0.29
  - `pydantic` ≥ 2.0
  - `PyJWT[crypto]` ≥ 2.8
  - `httpx` ≥ 0.27
  - `jinja2` ≥ 3.1
  - `python-multipart` ≥ 0.0.9

---

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and edit as needed.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MCP_PORT` | int | `8000` | Server port to bind to. |
| `MCP_REQUIRE_AUTH` | bool | `false` | Enforce OAuth or API key on all requests. |
| `MCP_API_KEY` | string | `change-me` | Static API key accepted as Bearer token (used when OAuth disabled or as fallback). |
| `OAUTH_ENABLED` | bool | `true` | Enable the OAuth 2.1 Authorization Server. |
| `OAUTH_ENABLE_AS` | bool | `true` | Mount AS endpoints (well-known, /oauth/*). |
| `OAUTH_AUTO_APPROVE` | bool | `true` | Skip the consent page. **Only enable for personal/headless clients.** |
| `OAUTH_STORAGE_DIR` | path | `~/.mcp_service/oauth` | Directory for persisted tokens & clients. |
| `OAUTH_ACCESS_TOKEN_TTL` | int | `3600` | Access token lifetime in seconds (1 hour). |
| `OAUTH_REFRESH_TOKEN_TTL` | int | `2592000` | Refresh token lifetime (30 days). |
| `OAUTH_AUTH_CODE_TTL` | int | `600` | Authorization code lifetime (10 minutes). |
| `OAUTH_SUPPORTED_SCOPES` | space-separated string | `mcp:read mcp:write mcp:admin` | Allowed OAuth scopes. See [Custom scopes](#custom-oauth-scopes) below. |
| `OAUTH_ISSUER` | URL | _empty_ | Expected `iss` claim for JWT validation. |
| `OAUTH_AUDIENCE` | string | _empty_ | Expected `aud` claim for JWT validation. |
| `OAUTH_JWKS_URI` | URL | _empty_ | JWKS endpoint for external IdP signature verification. |
| `OAUTH_ALGORITHM` | string | `RS256` | JWT algorithm (RS256, HS256, …). |
| `OAUTH_VERIFY_SIGNATURE` | bool | `true` | Verify JWT signatures. **Always keep on in production.** |
| `OAUTH_VERIFY_AUDIENCE` | bool | `false` | Enforce `aud` claim match. |
| `OAUTH_VERIFY_ISSUER` | bool | `false` | Enforce `iss` claim match. |
| `OAUTH_VERIFY_EXP` | bool | `true` | Enforce JWT `exp` claim. |
| `OAUTH_REQUIRED_SCOPE` | string | _empty_ | Scope required for all requests (e.g. `mcp:read`). |
| `JWT_SECRET` | string | _empty_ | HMAC secret fallback when no JWKS URI is configured. |

### Quick config examples

**Local development (no auth):**

```env
MCP_PORT=8000
MCP_REQUIRE_AUTH=false
OAUTH_ENABLED=false
```

**Production with built-in OAuth AS:**

```env
MCP_PORT=8000
MCP_REQUIRE_AUTH=true
OAUTH_ENABLED=true
OAUTH_AUTO_APPROVE=false
OAUTH_STORAGE_DIR=/var/lib/mcp-service/oauth
MCP_API_KEY=<random-32-bytes>
```

**Production with external JWT IdP (e.g. Auth0):**

```env
MCP_REQUIRE_AUTH=true
OAUTH_ENABLED=false
OAUTH_ISSUER=https://your-tenant.auth0.com/
OAUTH_AUDIENCE=https://mcp.yourcompany.com
OAUTH_JWKS_URI=https://your-tenant.auth0.com/.well-known/jwks.json
OAUTH_VERIFY_AUDIENCE=true
OAUTH_VERIFY_ISSUER=true
```

### Custom OAuth Scopes

`OAUTH_SUPPORTED_SCOPES` accepts any whitespace-separated list of scope names.
The AS treats them as **opaque strings** — `mcp-service` does not enforce a
fixed taxonomy. Projects can use domain-specific names and decide for
themselves how to interpret them in their handler.

```env
# Custom scope set for a finance MCP server
OAUTH_SUPPORTED_SCOPES=portfolio:read portfolio:write trades:execute admin
```

The scopes appear in:

- `/.well-known/oauth-authorization-server` → `scopes_supported`
- `/.well-known/oauth-protected-resource` → `scopes_supported`
- The consent page template (each scope rendered as a list item)
- The `scope` claim of issued access tokens

The handler receives the granted scopes in the validated `OAuthToken.scopes`
list, so the application code can enforce them however it wants:

```python
def handler(request):
    if request.get("method") == "tools/call":
        tool = request["params"]["name"]
        if tool == "execute_trade" and "trades:execute" not in request["scopes"]:
            return error(-32603, "missing required scope: trades:execute")
```

---

## Usage

### Class-based handlers (`MCPHandler`)

For new projects, subclass `MCPHandler` to get method-based dispatch,
tool registration, lifecycle hooks, and discovery metadata — without any
boilerplate:

```python
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

    async def on_resources_list(self, request):
        return self._ok(request, {"resources": []})

    async def setup(self):
        # Open DB connections, warm caches, etc. Runs once at startup.
        ...

    async def teardown(self):
        # Release resources on shutdown.
        ...


if __name__ == "__main__":
    run(WeatherHandler())
```

**What you get for free:**

| Built-in JSON-RPC method | Answer |
|--------------------------|--------|
| `initialize` | Reports `name`, `version`, `protocolVersion`, and `capabilities` |
| `notifications/initialized` | Returns `None` → HTTP `204` |
| `ping` | Empty result |
| `tools/list` | Iterates over registered tools |
| `tools/call` | Invokes the matching callable; wraps plain results in MCP `content` |
| any other method | Routed via `@register_method("foo/bar")` or `on_foo_bar(self, req)` |

The authenticated subject (when a Bearer token is present) is surfaced
via `request["_meta"]["user_id"]`, so handlers can implement per-user
authorization without threading context through every call.

### Function handlers

Plain function handlers remain fully supported:

```python
from mcp_service import run

def my_handler(request: dict) -> dict | None:
    method = request.get("method")
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"tools": [
                {"name": "ping", "description": "Returns pong"},
            ]},
        }
    if method == "tools/call":
        return {"jsonrpc": "2.0", "id": request.get("id"),
                "result": {"content": [{"type": "text", "text": "pong"}]}}
    return None

if __name__ == "__main__":
    run(my_handler, title="My Server")
```

Internally, `create_app` wraps function handlers in a lightweight
`MCPHandler` adapter so the dispatch path is identical for both styles.

### Handler contract

```python
Handler = MCPHandler | Callable[[dict], Optional[dict]]
```

- **Input:** a raw JSON-RPC 2.0 request dict (`jsonrpc`, `id`, `method`,
  `params`, plus `_meta` for context like `user_id`).
- **Output:**
  - a dict — wrapped in a 200 response.
  - `None` — notification; responded with `204 No Content`.
  - raise an exception — wrapped in a 500 JSON-RPC error.

### Service discovery

Every server advertises its capabilities at a stable well-known URI.
Clients fetch this **once on connect** to learn what's supported before
negotiating OAuth or sending method calls:

```bash
curl http://localhost:8000/.well-known/mcp.json
```

```json
{
  "mcp_version": "2024-11-05",
  "server": {"name": "weather-mcp", "version": "1.0.0", "description": "Read-only weather lookup"},
  "transport": {"type": "http", "endpoint": "/mcp", "methods": ["POST", "GET"]},
  "auth": {
    "required": false,
    "schemes": [
      {"type": "bearer", "header": "Authorization", "required": false},
      {"type": "api-key", "header": "MCP-API-Key", "required": false}
    ],
    "authorization_server": "http://localhost:8000/.well-known/oauth-authorization-server",
    "registration_endpoint": "http://localhost:8000/oauth/register"
  },
  "scopes_supported": ["mcp:read", "mcp:write", "mcp:admin"],
  "capabilities": {"tools": {"listChanged": false}},
  "tools": [
    {"name": "get_weather", "description": "Get current weather for a city",
     "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}
  ],
  "endpoints": {
    "mcp": "/mcp",
    "openapi": "/openapi.json",
    "docs": "/docs",
    "health": "/health",
    "healthz": "/healthz"
  }
}
```

`capabilities` and `tools` are populated automatically from
`MCPHandler.capabilities()` and `MCPHandler.list_tools()`. Override
those on a subclass to customise.

### CLI entry point

If `mcp_service` is installed, a console script is available:

```bash
MCP_HANDLER=example.main:handler mcp-service
```

---

## OAuth 2.1 Flow

`mcp-service` implements **Authorization Code Flow with PKCE** (RFC 7636), the OAuth 2.1 recommended flow for public clients.

```
┌────────┐                                          ┌──────────────┐
│ Client │                                          │  MCP Service │
└───┬────┘                                          └──────┬───────┘
    │  1. GET /.well-known/oauth-authorization-server    │
    │ ──────────────────────────────────────────────────►│
    │  ◄──────────────────────────────────────────────── │
    │  { issuer, authorization_endpoint, token_endpoint, │
    │    registration_endpoint, scopes_supported }      │
    │                                                    │
    │  2. POST /oauth/register (RFC 7591)                │
    │ ──────────────────────────────────────────────────►│
    │  ◄──────────────────────────────────────────────── │
    │  { client_id, … }                                  │
    │                                                    │
    │  3. Generate code_verifier + code_challenge (S256) │
    │  4. GET /oauth/authorize?response_type=code        │
    │                  &client_id=…                      │
    │                  &redirect_uri=…                   │
    │                  &code_challenge=…                  │
    │                  &code_challenge_method=S256       │
    │                  &state=…                          │
    │                  &scope=…                          │
    │ ──────────────────────────────────────────────────►│
    │  ◄──────────────────────────────────────────────── │
    │  302 → redirect_uri?code=…&state=…                 │
    │                                                    │
    │  5. POST /oauth/token                              │
    │      grant_type=authorization_code                 │
    │      &code=…                                       │
    │      &code_verifier=…                              │
    │      &redirect_uri=…                               │
    │ ──────────────────────────────────────────────────►│
    │  ◄──────────────────────────────────────────────── │
    │  { access_token, refresh_token, expires_in, … }    │
    │                                                    │
    │  6. POST /mcp  Authorization: Bearer <access_token>│
    │ ──────────────────────────────────────────────────►│
    │  ◄──────────────────────────────────────────────── │
    │  JSON-RPC 2.0 response                             │
    │                                                    │
    │  7. POST /oauth/token  (when access_token expires) │
    │      grant_type=refresh_token                      │
    │      &refresh_token=…                              │
    │ ──────────────────────────────────────────────────►│
    │  ◄──────────────────────────────────────────────── │
    │  { access_token, refresh_token, … }                │
```

### Minimal Python client

```python
import secrets, hashlib, base64, httpx

verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
challenge = base64.urlsafe_b64encode(
    hashlib.sha256(verifier.encode()).digest()
).decode().rstrip("=")

# Register client
client = httpx.post("http://localhost:8000/oauth/register",
                    json={"client_name": "demo",
                          "redirect_uris": ["http://localhost:9999/cb"]}).json()

# Authorize (with auto-approve enabled, server returns 302 with code)
auth = httpx.get("http://localhost:8000/oauth/authorize",
                 params={"response_type": "code",
                         "client_id": client["client_id"],
                         "redirect_uri": "http://localhost:9999/cb",
                         "state": "xyz",
                         "code_challenge": challenge,
                         "code_challenge_method": "S256"},
                 follow_redirects=False)
code = httpx.params(auth.headers["location"])["code"]

# Exchange code for tokens
tokens = httpx.post("http://localhost:8000/oauth/token",
                    data={"grant_type": "authorization_code",
                          "code": code,
                          "redirect_uri": "http://localhost:9999/cb",
                          "code_verifier": verifier}).json()

# Call MCP
result = httpx.post("http://localhost:8000/mcp",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                    json={"jsonrpc": "2.0", "id": 1,
                          "method": "tools/list", "params": {}}).json()
```

See [`examples/clients/`](examples/clients/) for full curl, Python, and Node.js clients.

---

## Docker

A multi-stage `Dockerfile` and `docker-compose.yml` are provided.

```bash
docker-compose up -d
curl http://localhost:8000/health
```

Build a minimal image:

```bash
docker build -t mcp-service:latest .
docker run --rm -p 8000:8000 --env-file .env mcp-service:latest
```

See [`docs/quickstart.md`](docs/quickstart.md) for production deployment notes.

---

## API Reference

Interactive docs: **`/docs`** (Swagger UI) and **`/redoc`** (ReDoc).

Raw schema: **`/openapi.json`**.

Full endpoint table and request/response shapes: [`docs/api-reference.md`](docs/api-reference.md).

---

## Integration Examples

Ready-to-run examples in [`examples/clients/`](examples/clients/):

- **`curl-auth.sh`** — full OAuth dance with curl
- **`python-client.py`** — Python with PKCE (httpx)
- **`js-integration.mjs`** — Node.js with built-in `fetch`

---

## Project Structure

```
mcp-service/
├── mcp_service/          # Library code
│   ├── server.py         # FastAPI factory + run()
│   ├── config.py         # Environment-based config
│   ├── errors.py         # Standardized error helpers
│   └── oauth/            # OAuth 2.1 Authorization Server
│       ├── endpoints.py  # /oauth/* routes
│       ├── middleware.py # Bearer token validation
│       ├── models.py     # Pydantic schemas
│       ├── pkce.py       # RFC 7636
│       ├── storage.py    # Token + client persistence
│       ├── token_validator.py
│       └── templates/    # Consent page
├── example/              # Minimal working MCP server
├── examples/clients/     # curl, Python, Node.js examples
├── tests/                # pytest suite (≥85% coverage)
├── docs/                 # Detailed documentation
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── pyproject.toml
└── README.md
```

---

## Development

### Setup

```bash
git clone https://github.com/AvengerMoJo/mcp-service.git
cd mcp-service
pip install -e ".[dev]"
```

### Run tests

```bash
pytest                       # full suite
pytest --cov=mcp_service     # with coverage report
pytest tests/test_oauth.py   # single file
pytest -k "pkce"             # by keyword
```

### Lint / format

```bash
ruff check mcp_service/
ruff format mcp_service/
```

### Run the example

```bash
python example/main.py
# in another terminal:
bash examples/clients/curl-auth.sh
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'mcp_service'`

Install in editable mode: `pip install -e .`

### `Address already in use` on startup

Change `MCP_PORT` or kill the process holding the port:

```bash
lsof -ti:8000 | xargs kill -9
```

### `invalid_request: PKCE verification failed`

The `code_verifier` sent to `/oauth/token` doesn't match the `code_challenge` from `/oauth/authorize`. Ensure you're sending the same verifier that produced the challenge (SHA-256, then base64url-stripped).

### `401 Unauthorized: invalid_token`

Token expired or malformed. For JWTs, verify `OAUTH_JWKS_URI` is reachable and the `kid` in the JWT header matches a key in the JWKS. For opaque tokens, the token must come from `/oauth/token` — tokens are tied to the issuing client.

### `400 Bad Request: redirect_uri mismatch`

The `redirect_uri` sent to `/oauth/token` must match exactly the one used in `/oauth/authorize`. This is per OAuth 2.1 spec.

### `OAUTH_SUPPORTED_SCOPES` ignored

Restart the server after editing `.env`. The config is read once at startup.

### Tokens lost on restart

Check `OAUTH_STORAGE_DIR` is on a persistent volume and writable. Tokens are persisted to `<storage_dir>/tokens.json` after every issue/refresh.

### `WWW-Authenticate` header missing on errors

This was fixed in v1.0. See [CHANGELOG.md](CHANGELOG.md). If you're seeing it on an older version, upgrade.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the versioning policy, deprecation timeline, and PR process.

---

## License

[MIT](LICENSE) — © 2026 AvengerMoJo.