"""
Environment-based config — replaces project-specific app_config dependencies.
All settings read from env vars; safe defaults for local use.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _path(key: str, default: str) -> Path:
    raw = os.getenv(key, default)
    return Path(raw).expanduser()


@dataclass
class OAuthConfig:
    enabled: bool = False
    enable_authorization_server: bool = True
    auto_approve: bool = True

    # External token validation
    issuer: Optional[str] = None
    audience: Optional[str] = None
    jwks_uri: Optional[str] = None
    algorithm: str = "RS256"
    verify_signature: bool = True
    verify_audience: bool = False
    verify_issuer: bool = False
    verify_exp: bool = True
    required_scope: str = ""

    # Token lifetimes (seconds)
    access_token_ttl: int = 3600
    refresh_token_ttl: int = 2592000
    authorization_code_ttl: int = 600

    supported_scopes: list[str] = field(
        default_factory=lambda: ["mcp:read", "mcp:write", "mcp:admin"]
    )

    storage_dir: Path = field(
        default_factory=lambda: Path.home() / ".mcp_service" / "oauth"
    )

    def get_protected_resource_metadata(self, base_url: Optional[str] = None) -> dict:
        as_url = base_url or ""
        return {
            "resource": as_url,
            "authorization_servers": [f"{as_url}/.well-known/oauth-authorization-server"],
            "scopes_supported": self.supported_scopes,
        }


@dataclass
class AppConfig:
    oauth: OAuthConfig = field(default_factory=OAuthConfig)
    port: int = 8000
    require_auth: bool = False
    api_key: Optional[str] = None


_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _config
    if _config is not None:
        return _config

    storage_dir = _path("OAUTH_STORAGE_DIR", str(Path.home() / ".mcp_service" / "oauth"))

    oauth = OAuthConfig(
        enabled=_bool("OAUTH_ENABLED", True),
        enable_authorization_server=_bool("OAUTH_ENABLE_AS", True),
        auto_approve=_bool("OAUTH_AUTO_APPROVE", True),
        issuer=os.getenv("OAUTH_ISSUER"),
        audience=os.getenv("OAUTH_AUDIENCE"),
        jwks_uri=os.getenv("OAUTH_JWKS_URI"),
        algorithm=os.getenv("OAUTH_ALGORITHM", "RS256"),
        verify_signature=_bool("OAUTH_VERIFY_SIGNATURE", True),
        verify_audience=_bool("OAUTH_VERIFY_AUDIENCE", False),
        verify_issuer=_bool("OAUTH_VERIFY_ISSUER", False),
        verify_exp=_bool("OAUTH_VERIFY_EXP", True),
        required_scope=os.getenv("OAUTH_REQUIRED_SCOPE", ""),
        access_token_ttl=_int("OAUTH_ACCESS_TOKEN_TTL", 3600),
        refresh_token_ttl=_int("OAUTH_REFRESH_TOKEN_TTL", 2592000),
        authorization_code_ttl=_int("OAUTH_AUTH_CODE_TTL", 600),
        supported_scopes=os.getenv(
            "OAUTH_SUPPORTED_SCOPES", "mcp:read mcp:write mcp:admin"
        ).split(),
        storage_dir=storage_dir,
    )

    _config = AppConfig(
        oauth=oauth,
        port=_int("MCP_PORT", 8000),
        require_auth=_bool("MCP_REQUIRE_AUTH", False),
        api_key=os.getenv("MCP_API_KEY"),
    )
    return _config
