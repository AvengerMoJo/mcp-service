"""OAuth 2.1 data models and schemas"""

from typing import Optional, List
from pydantic import BaseModel, Field


class OAuthToken(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    sub: Optional[str] = None
    iss: Optional[str] = None
    aud: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    jti: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    client_id: Optional[str] = None


class OAuthError(BaseModel):
    error: str
    error_description: Optional[str] = None
    error_uri: Optional[str] = None
    state: Optional[str] = None


class AuthorizationServerMetadata(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str] = None
    response_types_supported: List[str] = Field(default_factory=lambda: ["code"])
    grant_types_supported: List[str] = Field(
        default_factory=lambda: ["authorization_code", "refresh_token"]
    )
    code_challenge_methods_supported: List[str] = Field(default_factory=lambda: ["S256"])
    token_endpoint_auth_methods_supported: List[str] = Field(default_factory=lambda: ["none"])
    scopes_supported: List[str] = Field(
        default_factory=lambda: ["mcp:read", "mcp:write", "mcp:admin"]
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
