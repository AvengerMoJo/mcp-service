# Changelog

All notable changes to `mcp-service` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Versioning policy** — see [`CONTRIBUTING.md`](./CONTRIBUTING.md#versioning).
> Backwards-incompatible changes bump the **MAJOR** version. Deprecations are
> announced one minor release ahead and removed on the next major bump.

## [Unreleased]

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
