# MCP Service Improvement Plan

**Version:** 1.0  
**Date:** 2026-06-18  
**Author:** Paul (Product Manager)

---

## Executive Summary

The `mcp-service` repository is a **functional but incomplete foundation** for a reusable OAuth 2.1-protected MCP HTTP server. It has solid technical DNA but lacks the professional packaging, documentation, and extensibility patterns required to be "plug-and-play" across projects.

---

## 1. Current State Assessment

### ✅ What Exists (Strengths)

| Component | Status | Notes |
|-----------|--------|-------|
| **OAuth 2.1 Authorization Server** | Implemented | Full support for PKCE, dynamic client registration, token management |
| **Token Storage** | Functional | In-memory with JSON persistence; survives restarts |
| **JWT Validation** | Partial | Supports external IdP validation but poorly documented |
| **FastAPI Server Factory** | Good | `create_app()` and `run()` provide clean extension points |
| **Environment Configuration** | Complete | `.env.example` covers all major settings |
| **Basic MCP Protocol Support** | Working | Example shows initialize, tools/list, tools/call |

### ❌ What's Missing (Critical Gaps)

| Gap | Impact | Severity |
|-----|--------|----------|
| **No README.md** | Zero discoverability; users must reverse-engineer | 🔴 Critical |
| **No API Documentation** | No OpenAPI/Swagger usage examples | 🟠 High |
| **No Tests** | Unverified reliability; no regression safety net | 🔴 Critical |
| **No Dockerfile/Container Image** | Deployment friction; inconsistent environments | 🟠 High |
| **No Release Process / Versioning Policy** | Unclear how to upgrade; breaking change risk | 🟡 Medium |
| **Limited Scope Support** | Only `mcp:read`, `mcp:write`, `mcp:admin` hardcoded | 🟡 Medium |
| **Inconsistent Error Handling** | Truncated code paths; unclear error contracts | 🟠 High |

### 🔴 What Is Unprofessional

1. **No public documentation**: A library without a README.md is essentially unusable for external consumers.
2. **No test coverage**: Code exists but has zero verification against the stated guarantees (OAuth 2.1 compliance, token lifecycle, etc.).
3. **Opaque error contracts**: The `server.py` output was truncated due to length limits—this indicates complex error paths that are unmapped and untested.
4. **Missing versioning strategy**: No changelog, no semver policy, no deprecation warnings for breaking changes.

---

## 2. Target State: "Reusable Across All Projects"

A truly reusable MCP service must satisfy these criteria:

### Design Principles

| Principle | What It Means |
|-----------|---------------|
| **Zero-configuration onboarding** | A project can clone the repo, set env vars, and be running in < 5 minutes without reading documentation. |
| **Explicit contracts, implicit defaults** | Every interface is documented; every default has a rationale and escape hatch. |
| **Tested guarantees** | OAuth token lifecycle, PKCE enforcement, JWT validation—all covered by automated tests. |
| **Deployment-agnostic** | Works in Docker, Kubernetes, serverless, or bare metal with identical behavior. |
| **Backward-compatible evolution** | New features don't break existing integrations; deprecations follow a clear timeline. |

### Success Metrics

1. **Onboarding time**: < 30 minutes for a new project to integrate (including environment setup).
2. **Test coverage**: ≥ 85% line coverage across core modules (`server.py`, `token_validator.py`, `storage.py`).
3. **Documentation completeness**: All public APIs documented; all config options explained with examples.
4. **Zero critical bugs**: No P0/P1 issues filed in the first 90 days after v1.0 release.

---

## 3. Prioritized Task List

### Phase 1: Foundation (Week 1-2)

#### Task 1.1 — Write README.md
**What to do:** Create a comprehensive README with installation, configuration, and usage examples.  
**Why:** Without documentation, the service is unusable for external consumers.  
**Acceptance criteria:**
- [ ] Installation instructions work end-to-end (local + Docker)
- [ ] `.env.example` fully documented with all options explained
- [ ] Quick start guide: "run this command to get a working server"
- [ ] OAuth flow diagram and example client integration steps
- [ ] Troubleshooting section for common errors

#### Task 1.2 — Add Comprehensive Tests
**What to do:** Implement pytest + pytest-asyncio test suite covering all critical paths.  
**Why:** Unverified code leads to production failures; tests are the safety net for refactoring.  
**Acceptance criteria:**
- [ ] ≥ 85% line coverage on core modules (`server.py`, `token_validator.py`, `storage.py`)
- [ ] OAuth token lifecycle tested: authorization → access token → refresh → revocation
- [ ] PKCE enforcement verified (invalid challenges rejected)
- [ ] JWT validation tested against both valid and malformed tokens
- [ ] MCP protocol methods tested (initialize, tools/list, tools/call)

#### Task 1.3 — Standardize Error Handling
**What to do:** Define a consistent error response format; document all possible errors with HTTP codes.  
**Why:** Clients need to handle errors gracefully; inconsistent responses lead to brittle integrations.  
**Acceptance criteria:**
- [ ] All error paths return structured JSON with `error`, `error_description`, and optional `error_uri`
- [ ] Error catalog documented in a separate file (e.g., `ERRORS.md`)
- [ ] HTTP status codes follow REST conventions (401 for auth failures, 403 for permission denied)
- [ ] WWW-Authenticate headers present on all 4xx/5xx responses

### Phase 2: Deployment & Discovery (Week 3-4)

#### Task 2.1 — Add Dockerfile and docker-compose.yml
**What to do:** Create reproducible container images with multi-stage builds; add production-ready compose file.  
**Why:** Deployment friction prevents adoption; containers ensure consistency across environments.  
**Acceptance criteria:**
- [ ] Multi-stage build: builder stage + minimal runtime image (alpine or distroless)
- [ ] Health check endpoint exposed in container
- [ ] `.env` file with production defaults included in repo
- [ ] `docker-compose up` brings up service with OAuth AS enabled

#### Task 2.2 — Add OpenAPI/Swagger Documentation
**What to do:** Enable FastAPI's built-in docs; customize with examples and descriptions.  
**Why:** Developers need to understand the API without reading source code.  
**Acceptance criteria:**
- [ ] `/docs` endpoint available (Swagger UI)
- [ ] `/openapi.json` returns complete schema with all endpoints documented
- [ ] OAuth flows have interactive examples (authorize → token exchange)

#### Task 2.3 — Create Changelog and Versioning Policy
**What to do:** Establish semver policy; add CHANGELOG.md with format for future releases.  
**Why:** Projects need to know when upgrades are safe; breaking changes must be communicated.  
**Acceptance criteria:**
- [ ] CHANGELOG.md follows Keep a Changelog format (https://keepachangelog.com/)
- [ ] Versioning policy documented in CONTRIBUTING.md
- [ ] Deprecation timeline defined (e.g., "features deprecated for 2 major versions before removal")

### Phase 3: Extensibility & Polish (Week 5-6)

#### Task 3.1 — Expand Scope Support
**What to do:** Make scopes configurable per-project; allow custom scope definitions.  
**Why:** Different projects need different permission models; hardcoded scopes limit reusability.  
**Acceptance criteria:**
- [ ] `OAUTH_SUPPORTED_SCOPES` environment variable fully documented with examples
- [ ] Custom scopes can be added without code changes
- [ ] Scope validation happens at registration time (not runtime)

#### Task 3.2 — Add Health Check Endpoint
**What to do:** Create `/healthz` with deeper checks (DB connectivity, token store status).  
**Why:** Kubernetes and other platforms need liveness/readiness probes for reliable deployments.  
**Acceptance criteria:**
- [ ] `/health` returns basic status (already exists)
- [ ] `/healthz` includes detailed metrics (token store health, config validation)
- [ ] Returns 200 OK only if all checks pass

#### Task 3.3 — Add Integration Examples for Popular Clients
**What to do:** Create example client integrations (curl, Python httpx, JavaScript fetch).  
**Why:** Developers learn by example; concrete code reduces integration friction.  
**Acceptance criteria:**
- [ ] `examples/clients/curl-auth.sh` — full OAuth flow with curl
- [ ] `examples/clients/python-client.py` — Python client with PKCE support
- [ ] `examples/clients/js-integration.mjs` — Node.js example

---

## 4. Proposed File / Directory Structure After Improvements

```
avengermojo-mcp-service/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # Run tests on PR
│   │   └── release.yml         # Auto-increment version, create GitHub release
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── ISSUE_TEMPLATE/
├── mcp_service/
│   ├── __init__.py             # Expose create_app(), run()
│   ├── config.py               # Environment-based configuration
│   ├── server.py               # FastAPI app factory, MCP endpoint logic
│   ├── errors.py               # Standardized error classes and responses
│   └── oauth/
│       ├── __init__.py
│       ├── models.py           # Pydantic schemas for OAuth messages
│       ├── token_validator.py  # JWT + opaque token validation
│       ├── storage.py          # Token store (in-memory + JSON persistence)
│       ├── pkce.py             # PKCE utilities per RFC 7636
│       ├── endpoints.py        # Authorization Server HTTP routes
│       ├── middleware.py       # FastAPI dependencies for OAuth checks
│       └── templates/
│           └── authorize.html  # Consent page template
├── example/
│   ├── main.py                 # Minimal working MCP server
│   └── clients/
│       ├── curl-auth.sh        # Full OAuth flow with curl
│       ├── python-client.py    # Python client with PKCE
│       └── js-integration.mjs  # Node.js example
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Shared fixtures (token store, config)
│   ├── test_server.py          # MCP endpoint logic tests
│   ├── test_oauth.py           # OAuth flow tests (authorize → token)
│   └── test_token_validator.py # JWT + opaque token validation tests
├── docs/
│   ├── index.md                # Landing page with overview
│   ├── quickstart.md           # 10-minute getting started guide
│   ├── oauth-flow.md           # Detailed OAuth 2.1 flow explanation
│   ├── api-reference.md        # Auto-generated OpenAPI reference
│   └── ERRORS.md               # Complete error catalog
├── .env.example                # All config options with comments
├── CHANGELOG.md                # Version history (Keep a Changelog format)
├── CONTRIBUTING.md             # Development guidelines, versioning policy
├── LICENSE                     # MIT license
├── pyproject.toml              # Project metadata, dependencies
├── README.md                   # Primary documentation (installation, usage)
├── Dockerfile                  # Multi-stage build for production image
└── docker-compose.yml          # Production-ready compose file with OAuth enabled
```

**Rationale:** This structure separates concerns cleanly (service code vs. examples vs. tests), follows Python packaging conventions, and provides clear entry points for new contributors.

---

## 5. Interface Contract: What the Service Must Expose

### External HTTP API

| Endpoint | Method | Purpose | Required Headers | Response Format |
|----------|--------|---------|------------------|-----------------|
| `/.well-known/oauth-authorization-server` | GET | OAuth AS metadata (RFC 8414) | None | JSON: `issuer`, `authorization_endpoint`, `token_endpoint`, ... |
| `/.well-known/oauth-protected-resource` | GET | Protected resource metadata | None | JSON: `resource`, `scopes_supported` |
| `/oauth/register` | POST | Dynamic client registration (RFC 7591) | Content-Type: application/json | JSON: `client_id`, `client_secret`, ... or error |
| `/oauth/authorize` | GET | Authorization request with PKCE | None | HTML consent page or redirect |
| `/oauth/authorize` | POST | Process allow/deny form submission | Content-Type: application/x-www-form-urlencoded | Redirect to client `redirect_uri` |
| `/oauth/token` | POST | Exchange authorization code for tokens OR refresh access token | Content-Type: application/x-www-form-urlencoded, Authorization (client auth) | JSON: `access_token`, `token_type`, `expires_in`, `refresh_token` |
| `/mcp` or `/` | POST | MCP protocol endpoint | Optional: Bearer token, MCP-API-Key header | JSON-RPC 2.0 response or notification (204) |
| `/health` | GET | Basic health check | None | JSON: `{status: "ok", server: "<title>"}` |
| `/healthz` | GET | Detailed liveness probe | None | JSON: `{status: "ok", checks: {...}}` or 503 with error details |

### MCP Protocol Contract

The service wraps any JSON-RPC 2.0 handler. The contract is minimal:

- **Input:** Raw JSON-RPC dict (e.g., `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`)
- **Output:** Response dict or None for notifications; wrapped in FastAPI's async flow
- **Authentication:** Optional by default; can be enforced via `MCP_REQUIRE_AUTH=true`

### Configuration Contract

All configuration must be environment-variable based. No hardcoded values:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MCP_PORT` | int | 8000 | Server port to bind to |
| `MCP_REQUIRE_AUTH` | bool | false | Enforce OAuth or API key on all requests |
| `MCP_API_KEY` | string | None | API key for bearer token alternative (when OAuth disabled) |
| `OAUTH_ENABLED` | bool | true | Enable OAuth 2.1 Authorization Server |
| `OAUTH_AUTO_APPROVE` | bool | true | Skip consent page (for personal assistants only!) |
| `OAUTH_STORAGE_DIR` | path | ~/.mcp_service/oauth | Directory for persisted tokens |
| `OAUTH_ACCESS_TOKEN_TTL` | int | 3600 | Access token lifetime in seconds |
| `OAUTH_REFRESH_TOKEN_TTL` | int | 2592000 | Refresh token lifetime (30 days) |
| `OAUTH_AUTH_CODE_TTL` | int | 600 | Authorization code lifetime (10 minutes) |
| `OAUTH_SUPPORTED_SCOPES` | space-separated string | "mcp:read mcp:write mcp:admin" | Allowed OAuth scopes for this service |

### Security Contract

- **PKCE required:** All authorization requests must include a valid S256 code challenge (RFC 7636).
- **Token binding:** Access tokens are bound to the client that requested them; cannot be reused across clients.
- **Refresh token rotation:** Each refresh invalidates the previous one; prevents replay attacks.
- **JWT validation:** If using external IdP, signature verification is mandatory; audience/issuer claims optionally verified based on config.

### Extensibility Contract

To plug a new project into this service:

1. Implement a handler function with signature `handler(request: dict) -> dict | None`
2. Call `create_app(handler)` or `run(handler)` from the `mcp_service` module
3. Configure OAuth scopes via environment variables (no code changes needed)
4. Deploy; no other modifications required

---

## Next Steps

**Immediate action items:**

1. **Approve this plan** — Confirm priorities align with product goals.
2. **Assign tasks** — Delegate Phase 1 tasks to appropriate team members (documentation vs. testing vs. DevOps).
3. **Set timeline** — Target v1.0 release in 6 weeks based on current task estimates.

**Open questions:**

- Should we support client credentials flow for service-to-service communication, or stick with authorization code + PKCE only?
- Is there a need for a management UI (admin dashboard) to view registered clients and active tokens?
- Do we want to publish this as a pip package (`pip install mcp-service`) before v1.0, or keep it as a repo-only solution initially?

---

**Document status:** Draft 1.0 — awaiting review and approval before implementation begins.
