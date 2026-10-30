# Changelog

All notable changes to `mcp-service` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Versioning policy** — see [`CONTRIBUTING.md`](./CONTRIBUTING.md#versioning).
> Backwards-incompatible changes bump the **MAJOR** version. Deprecations are
> announced one minor release ahead and removed on the next major bump.

## [Unreleased]

### Changed

- **RFC 9728 protected-resource metadata fixed** — `resource` now identifies
  the MCP endpoint (`{base}/mcp`) instead of the bare origin, and
  `authorization_servers` lists the AS issuer origin instead of the metadata
  document URL. Added `bearer_methods_supported: ["header"]`. This is what
  ChatGPT/OpenAI connectors read to start the OAuth flow; the previous
  values made discovery fail.
- **`WWW-Authenticate` challenges now carry `resource_metadata`** (RFC 9728
  §5.1) on every 401 — the MCP endpoint and the OAuth token validator
  dependencies. Without this param clients cannot discover the authorization
  server and fall back to (unsupported) static API keys.
- **`redirect_uri` is enforced against the client's DCR registration** at the
  authorize endpoint, and `client_id` is required and checked against
  registered clients (RFC 6749 §2.2, §3.1.2.2; OAuth 2.1). Previously any
  shape-valid `redirect_uri` was accepted and unknown `client_id`s were
  allowed through — an open-redirect/mix-up risk.

### Added

- **RFC 8707 `resource` parameter** — accepted at `/oauth/authorize` and
  `/oauth/token`, bound to the authorization code and refresh token, echoed
  in token responses, and mismatch-checked. `client_id` mismatches at the
  token endpoint are now rejected with `invalid_grant`.
- **`build_www_authenticate(..., resource_metadata=...)`** — new keyword
  parameter, threaded through `oauth_error_response` and
  `TokenValidator.create_www_authenticate_header`.
- **Tests** — 12 new cases covering the metadata fix, challenge header,
  client/redirect_uri validation, and `resource` echo/mismatch. Total:
  **188 passing**.

- **`MCPHandler` extensibility API** — new `mcp_service.handler.MCPHandler`
  base class with `@register_tool` / `@register_method` decorators,
  `on_<method>` dispatch convention, and built-in answers for
  `initialize`, `notifications/initialized`, `ping`, `tools/list`, and
  `tools/call`. Plain function handlers remain fully backward-compatible
  via the `as_handler()` adapter.
- **Lifecycle hooks** — `async def setup()` / `async def teardown()` on
  handlers are wired into FastAPI's lifespan, so projects can open
  database connections, warm caches, and release resources cleanly.
- **`/.well-known/mcp.json`** — service discovery endpoint exposing the
  protocol version, server identity, transport, supported auth schemes
  (with `required` flags), `scopes_supported`, declared capabilities,
  and the full tool list. Documented in the OpenAPI `discovery` tag and
  the `/docs` UI.
- **`request["_meta"]["user_id"]`** — the authenticated subject (from a
  validated Bearer token) is now exposed to handlers via the request
  payload's `_meta` block, so `MCPHandler` subclasses can implement
  per-user authorization without threading context through every call.
- **`example/main.py`** rewritten as a `MCPHandler` subclass demonstrating
  tool registration, custom JSON-RPC methods, and discovery metadata.
- **Tests** — 39 new cases (`tests/test_handler.py`) covering handler
  registration, dispatch, built-ins, tools/call paths, discovery
  document shape, and lifespan lifecycle. Total: **176 passing**.

## [0.1.0] — 2026-06-18

The first public release of `mcp-service`. The codebase was already feature-complete
but lacked packaging, tests, deployment artefacts, and standardised error
contracts; this release closes those gaps.

### Added

- **README.md** — full installation, configuration, OAuth flow, troubleshooting
  ([`README.md`](./README.md)).
- **Tests** — 137 pytest cases covering OAuth flows, PKCE, token validation,
  storage persistence, MCP dispatch, error envelopes, health probes, and
  OpenAPI schema correctness; line coverage **91 %**.
- **`mcp_service.errors`** — single source of truth for OAuth (`RFC 6749 §5.2`)
  and JSON-RPC 2.0 error envelopes, plus a `WWW-Authenticate` builder that
  sanitises non-ASCII values per RFC 7230 §3.2.6.
- **`/healthz`** — deep liveness/readiness probe reporting token-store and
  client-store health (returns 503 when any check fails).
- **Dockerfile** — multi-stage build producing a slim, non-root runtime image
  with a `HEALTHCHECK` that hits `/healthz`.
- **`docker-compose.yml`** — production-ready compose file with a persistent
  `mcp-data` volume, read-only root filesystem, `no-new-privileges`, and
  healthcheck wiring.
- **`.env.production`** — documented production env template.
- **OpenAPI / Swagger UI** — title, version, contact, license, response
  examples, error envelopes, tags (`mcp`, `oauth`, `health`), and a
  PKCE-enabled "Authorize" button in Swagger UI.
- **GitHub Actions CI** — matrix test on Python 3.11/3.12/3.13, coverage gate
  (`>=85 %`), `sdist`+`wheel` build job, Docker build + smoke-test job.
- **GitHub Actions release** — tag-triggered PyPI publish via trusted
  publishing plus a GitHub Release with auto-generated notes.
- **Issue & PR templates** — bug report, feature request, and PR checklists.
- **`docs/ERRORS.md`** — complete catalog of OAuth and JSON-RPC errors with
  HTTP codes and resolution hints.
- **`CHANGELOG.md`** — this file.
- **`CONTRIBUTING.md`** — dev setup, testing, semver policy, deprecation timeline.
- **Default handler fallback** — `mcp-service` CLI now boots the bundled
  `example.main:handler` when `MCP_HANDLER` is unset, so `docker run mcp-service`
  is a usable smoke test out of the box.

### Changed

- `pyproject.toml` — replaced the non-existent `setuptools.backends.legacy:build`
  with `setuptools.build_meta`, added classifiers, project URLs, dev extras,
  Jinja template as package data, and pytest config under
  `[tool.pytest.ini_options]`.
- `server.py` — OAuth-gated responses now return the documented envelope via
  `oauth_error_response`; FastAPI exception handlers installed by
  `create_app` normalise 404 / 405 / 422 / `HTTPException` to the same shape.
- `token_validator.py` — `create_www_authenticate_header` delegates to
  `mcp_service.errors.build_www_authenticate` so all 401 responses share
  one ASCII-safe implementation.
- `.gitignore` — expanded to cover editor caches, coverage reports,
  `.pytest_cache`, `node_modules`, etc.

### Fixed

- `endpoints.py` — imported `JSONResponse` for response builders.
- WWW-Authenticate header values can no longer raise `UnicodeEncodeError`
  when descriptions contain non-ASCII characters.

[Unreleased]: https://github.com/AvengerMoJo/mcp-service/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AvengerMoJo/mcp-service/releases/tag/v0.1.0
