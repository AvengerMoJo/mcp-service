"""FastAPI dependencies and middleware for OAuth 2.1 bearer token validation."""

import logging
from typing import Optional, Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .models import OAuthToken
from .token_validator import TokenValidator, TokenValidationError
from mcp_service.config import OAuthConfig, get_config

_log = logging.getLogger(__name__)
_validator: Optional[TokenValidator] = None
oauth2_scheme = HTTPBearer(auto_error=False)


def _get_validator() -> TokenValidator:
    global _validator
    if _validator is None:
        _validator = TokenValidator(get_config().oauth)
    return _validator


async def optional_oauth_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
) -> Optional[OAuthToken]:
    if not credentials:
        return None
    try:
        return await _get_validator().validate_token(credentials.credentials)
    except TokenValidationError:
        return None


async def validated_oauth_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
) -> Optional[OAuthToken]:
    if not credentials:
        return None
    try:
        return await _get_validator().validate_token(credentials.credentials)
    except TokenValidationError as e:
        v = _get_validator()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e.message}",
            headers={"WWW-Authenticate": v.create_www_authenticate_header(e.error_code, e.message)},
        )


async def required_oauth_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
) -> OAuthToken:
    v = _get_validator()
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": v.create_www_authenticate_header("invalid_request", "Bearer token required")},
        )
    try:
        return await v.validate_token(credentials.credentials)
    except TokenValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            headers={"WWW-Authenticate": v.create_www_authenticate_header(e.error_code, e.message)},
        )


OptionalOAuthToken = Annotated[Optional[OAuthToken], Depends(optional_oauth_token)]
ValidatedOAuthToken = Annotated[Optional[OAuthToken], Depends(validated_oauth_token)]
RequiredOAuthToken = Annotated[OAuthToken, Depends(required_oauth_token)]
