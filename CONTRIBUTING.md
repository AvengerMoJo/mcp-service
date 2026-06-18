# Contributing

Thanks for your interest in `mcp-service`! This document explains the local
development workflow, the testing conventions, and the versioning policy.

## Development setup

```bash
git clone https://github.com/AvengerMoJo/mcp-service
cd mcp-service
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Running the test suite

```bash
pytest                           # full suite
pytest tests/test_oauth.py -v    # a single file
pytest -k "pkce" -v              # by keyword
```

Coverage is gated at **85 %**. The CI workflow fails if the threshold is not
met:

```bash
pytest --cov=mcp_service --cov-report=term-missing
coverage report --fail-under=85
```

When adding tests, prefer **behaviour-driven** names
(`test_refresh_issues_new_access_token`) and keep the AAA structure
(arrange / act / assert). Use the existing fixtures in `tests/conftest.py`
where possible.

## Coding conventions

- Type-annotate everything that leaves the module boundary.
- Public functions and classes get a short docstring describing the contract,
  not the implementation.
- Keep modules small (`< 400` lines) — split early.
- Use the helpers in `mcp_service.errors` rather than hand-rolling error
  envelopes.
- Don't import private symbols across modules; if you need it, promote it.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(oauth): add client_credentials grant
fix(errors): sanitise non-ASCII in WWW-Authenticate header
docs: document OAUTH_SUPPORTED_SCOPES
test(storage): cover token rotation edge case
build(docker): drop distroless for python:3.12-slim
ci: gate coverage at 85%
```

Breaking changes append `!`: `feat(api)!: drop /v1 prefix from endpoints`.

## Pull requests

- One logical change per PR. Squash fixups locally.
- Update `CHANGELOG.md` under `[Unreleased]` (or your version if cutting a release).
- If you touched an HTTP route, update the OpenAPI examples in
  `mcp_service.server`.
- If you added or changed a public symbol, make sure the test suite still
  passes and the README still reflects reality.

## Versioning

`mcp-service` follows **Semantic Versioning 2.0.0**.

| Bump    | When                                                                            |
|---------|---------------------------------------------------------------------------------|
| MAJOR   | Backwards-incompatible API change, removal of a deprecated symbol, or change in default behaviour that requires user action. |
| MINOR   | Backwards-compatible feature: new endpoint, new env var, new optional dependency. |
| PATCH   | Backwards-compatible bug fix, refactor with no behaviour change, docs.          |

### Deprecation timeline

A feature deprecated in `X.Y` is removed no earlier than `X.(Y+2)`. We
backport the deprecation warning into the `X.Y` release so downstream users
have two minor releases to migrate.

Concretely:

1. Mark the symbol with a `DeprecationWarning` and document it in `CHANGELOG.md`.
2. Keep it functional for two subsequent minor releases.
3. Remove it in the next major release and add a `BREAKING` entry.

### Stable API surface

The following are considered **public** and follow semver guarantees:

- `mcp_service.create_app`, `mcp_service.run`, `mcp_service.__version__`
- `mcp_service.config.AppConfig`, `OAuthConfig`
- `mcp_service.errors.*` (all symbols)
- HTTP endpoints documented in `README.md` and `docs/ERRORS.md`
- Environment variables listed in `.env.example`

Everything else (module-internal helpers, file paths, JSON shapes inside the
token store) is **internal** and may change in any release.

## Release process

1. Bump `version` in `pyproject.toml` (and `mcp_service/__init__.__version__`
   if you want to keep them in lockstep — both are read by the build).
2. Move the `[Unreleased]` notes into a dated `[X.Y.Z]` section in
   `CHANGELOG.md`.
3. Commit `chore(release): vX.Y.Z`.
4. Tag `git tag vX.Y.Z` and push (`git push --tags`).
5. The `release.yml` workflow publishes to PyPI and opens a GitHub Release
   with auto-generated notes.
6. Update the container build if you want a fresh `mcp-service:X.Y.Z` tag
   (not automated yet — manual `docker buildx build --push`).

## Code of conduct

Be patient, be specific, and prefer text over assumptions. Disagreement is
fine; disrespect is not.
