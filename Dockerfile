# syntax=docker/dockerfile:1.6
#
# Multi-stage Dockerfile for mcp-service.
#
#   docker build -t mcp-service:dev .
#   docker run --rm -p 8000:8000 mcp-service:dev
#
# Runtime image is python:3.12-slim, run as the unprivileged `app` user.
# No shell needed by the entrypoint — we exec the installed `mcp-service`
# console script directly so the only thing inside the container is the
# Python interpreter + site-packages + the application code.

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Build deps for any wheels that need compiling (cryptography, httpx, etc.).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

# Copy ONLY pyproject.toml + README first so the dependency layer caches
# independently of source changes.
COPY pyproject.toml README.md ./
COPY mcp_service ./mcp_service
COPY example ./example

# Install the package and its dependencies into the builder.
RUN pip install --upgrade pip \
 && pip install .

# Pre-create the persistent data directory in the builder so it ships with
# correct permissions (avoids needing a shell in the runtime image to mkdir).
RUN mkdir -p /var/lib/mcp-service/oauth \
 && chmod 0775 /var/lib/mcp-service/oauth

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="mcp-service" \
      org.opencontainers.image.description="Reusable MCP HTTP server with OAuth 2.1" \
      org.opencontainers.image.source="https://github.com/AvengerMoJo/mcp-service" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_PORT=8000 \
    OAUTH_ENABLED=true \
    OAUTH_AUTO_APPROVE=true \
    OAUTH_STORAGE_DIR=/var/lib/mcp-service/oauth \
    MCP_HANDLER=example.main:handler \
    PYTHONPATH=/home/app \
    PATH="/home/app/.local/bin:${PATH}"

# Create the unprivileged `app` user (uid 1000). No shell needed.
RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --home /home/app --shell /usr/sbin/nologin app \
 && mkdir -p /home/app /var/lib/mcp-service/oauth \
 && chown -R app:app /home/app /var/lib/mcp-service

WORKDIR /home/app

# Application + dependencies from the builder.
COPY --from=builder --chown=app:app /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder --chown=app:app /usr/local/bin/mcp-service /usr/local/bin/mcp-service
COPY --from=builder --chown=app:app /var/lib/mcp-service /var/lib/mcp-service
COPY --chown=app:app mcp_service ./mcp_service
COPY --chown=app:app example ./example

USER app:app
EXPOSE 8000

# Liveness probe — hits /healthz. Kubernetes / compose can scrape every 30s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# Default entry point — the `mcp-service` console script.
ENTRYPOINT ["mcp-service"]
