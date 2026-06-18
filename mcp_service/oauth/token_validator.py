"""OAuth 2.1 token validator — supports opaque tokens (built-in AS) and JWT (external IdP)."""

import logging
import os
import time
from typing import Optional

from .models import OAuthToken
from mcp_service.config import OAuthConfig

_log = logging.getLogger(__name__)


class TokenValidationError(Exception):
    def __init__(self, message: str, error_code: str = "invalid_token"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class TokenValidator:
    def __init__(self, config: OAuthConfig):
        self.config = config
        self.jwks_client = None
        if config.jwks_uri:
            try:
                from jwt import PyJWKClient
                self.jwks_client = PyJWKClient(config.jwks_uri)
            except ImportError:
                _log.warning("PyJWT not installed — JWKS validation unavailable")

    async def validate_token(self, token: str) -> OAuthToken:
        if not token:
            raise TokenValidationError("Token is required", "invalid_request")

        # MCP_API_KEY always accepted as Bearer token
        if await self._validate_api_key(token):
            return self._api_key_token(token)

        if not self.config.enabled:
            raise TokenValidationError("OAuth not enabled — only MCP_API_KEY accepted", "oauth_disabled")

        # Opaque token from built-in AS
        if self.config.enable_authorization_server:
            opaque = await self._validate_opaque(token)
            if opaque:
                return opaque

        # JWT from external IdP
        return await self._validate_jwt(token)

    async def _validate_api_key(self, token: str) -> bool:
        key = os.getenv("MCP_API_KEY")
        return bool(key) and token == key

    def _api_key_token(self, token: str) -> OAuthToken:
        return OAuthToken(
            access_token=token, token_type="Bearer",
            sub="api_key_user", iss="mcp_service",
            exp=int(time.time()) + 3600, iat=int(time.time()),
            scopes=["mcp:read", "mcp:write", "mcp:admin"],
            user_id="api_key_user", client_id="api_key",
            scope="mcp:read mcp:write mcp:admin",
        )

    async def _validate_opaque(self, token: str) -> Optional[OAuthToken]:
        try:
            from .storage import get_token_store
            td = get_token_store().get_access_token(token)
            if not td:
                return None
            scopes = td.scope.split() if td.scope else []
            return OAuthToken(
                access_token=td.token, token_type="Bearer",
                expires_in=td.get_expires_in(), scope=td.scope, scopes=scopes,
                user_id=td.client_id or "oauth_user", client_id=td.client_id,
                sub=td.client_id or "oauth_user", iss="mcp_oauth_server",
                aud=self.config.audience or "mcp_service",
                exp=int(td.expires_at.timestamp()), iat=int(td.created_at.timestamp()),
            )
        except Exception as e:
            _log.debug("Opaque token lookup failed: %s", e)
            return None

    async def _validate_jwt(self, token: str) -> OAuthToken:
        try:
            import jwt as _jwt
        except ImportError:
            raise TokenValidationError("PyJWT not installed", "server_error")

        try:
            header = _jwt.get_unverified_header(token)
            algorithm = header.get("alg", self.config.algorithm)
            key_id = header.get("kid")
            signing_key = await self._get_signing_key(key_id, algorithm)
            payload = _jwt.decode(
                token, signing_key, algorithms=[algorithm],
                audience=self.config.audience if self.config.verify_audience else None,
                issuer=self.config.issuer if self.config.verify_issuer else None,
                options={
                    "verify_signature": self.config.verify_signature,
                    "verify_aud": self.config.verify_audience,
                    "verify_iss": self.config.verify_issuer,
                    "verify_exp": self.config.verify_exp,
                },
            )
            return self._jwt_to_token(token, payload)
        except Exception as e:
            raise TokenValidationError(str(e))

    async def _get_signing_key(self, key_id, algorithm):
        if not self.config.verify_signature:
            return ""
        if self.jwks_client:
            try:
                return self.jwks_client.get_signing_key(key_id).key
            except Exception as e:
                raise TokenValidationError(f"JWKS key fetch failed: {e}")
        secret = os.getenv("JWT_SECRET") or os.getenv("MCP_API_KEY")
        if secret:
            return secret
        raise TokenValidationError("No signing key available", "server_error")

    def _jwt_to_token(self, token: str, payload: dict) -> OAuthToken:
        scope_raw = payload.get("scope", "")
        if isinstance(scope_raw, list):
            scopes = scope_raw
        else:
            scopes = scope_raw.split() if scope_raw else []
        return OAuthToken(
            access_token=token, token_type="Bearer",
            sub=payload.get("sub"), iss=payload.get("iss"),
            aud=payload.get("aud"), exp=payload.get("exp"), iat=payload.get("iat"),
            jti=payload.get("jti"), scopes=scopes,
            user_id=payload.get("user_id") or payload.get("sub"),
            client_id=payload.get("client_id") or payload.get("azp"),
            scope=" ".join(scopes),
        )

    def create_www_authenticate_header(self, error: str = "invalid_token",
                                       description: Optional[str] = None) -> str:
        from mcp_service.errors import build_www_authenticate
        return build_www_authenticate(
            error=error, description=description, audience=self.config.audience,
        )
