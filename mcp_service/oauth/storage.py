"""
OAuth 2.1 Authorization Server state — in-memory with JSON persistence.
Tokens survive server restarts; expired tokens are filtered on load.
"""

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, List
from threading import Lock

_log = logging.getLogger(__name__)


def _oauth_storage_dir() -> Path:
    from mcp_service.config import get_config
    d = get_config().oauth.storage_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class AuthorizationCodeData:
    code: str
    client_id: Optional[str]
    redirect_uri: str
    scope: str
    code_challenge: str
    code_challenge_method: str
    expires_at: datetime
    used: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        return not self.used and not self.is_expired()


@dataclass
class AccessTokenData:
    token: str
    client_id: Optional[str]
    scope: str
    expires_at: datetime
    refresh_token: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_expired()

    def get_expires_in(self) -> int:
        if self.is_expired():
            return 0
        return max(0, int((self.expires_at - datetime.now(timezone.utc)).total_seconds()))


@dataclass
class RefreshTokenData:
    token: str
    client_id: Optional[str]
    scope: str
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_expired()


class AuthorizationCodeStore:
    def __init__(self, cleanup_interval: int = 300):
        self._codes: Dict[str, AuthorizationCodeData] = {}
        self._lock = Lock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    def create(self, client_id, redirect_uri, scope, code_challenge,
               code_challenge_method, ttl=600) -> AuthorizationCodeData:
        code = secrets.token_urlsafe(32)
        data = AuthorizationCodeData(
            code=code, client_id=client_id, redirect_uri=redirect_uri, scope=scope,
            code_challenge=code_challenge, code_challenge_method=code_challenge_method,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )
        with self._lock:
            self._codes[code] = data
            self._maybe_cleanup()
        return data

    def get(self, code: str) -> Optional[AuthorizationCodeData]:
        with self._lock:
            return self._codes.get(code)

    def mark_used(self, code: str) -> bool:
        with self._lock:
            if code in self._codes:
                self._codes[code].used = True
                return True
            return False

    def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            expired = [c for c, d in self._codes.items() if not d.is_valid()]
            for c in expired:
                del self._codes[c]
            self._last_cleanup = now


class TokenStore:
    def __init__(self, cleanup_interval: int = 300):
        self._access_tokens: Dict[str, AccessTokenData] = {}
        self._refresh_tokens: Dict[str, RefreshTokenData] = {}
        self._lock = Lock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()
        self._path = _oauth_storage_dir() / "tokens.json"
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            now = datetime.now(timezone.utc)
            for token, td in raw.get("access_tokens", {}).items():
                expires_at = datetime.fromisoformat(td["expires_at"])
                if expires_at > now:
                    self._access_tokens[token] = AccessTokenData(
                        token=td["token"], client_id=td.get("client_id"),
                        scope=td["scope"], expires_at=expires_at,
                        refresh_token=td.get("refresh_token"),
                        created_at=datetime.fromisoformat(td["created_at"]),
                    )
            for token, rd in raw.get("refresh_tokens", {}).items():
                expires_at = datetime.fromisoformat(rd["expires_at"])
                if expires_at > now:
                    self._refresh_tokens[token] = RefreshTokenData(
                        token=rd["token"], client_id=rd.get("client_id"),
                        scope=rd["scope"], expires_at=expires_at,
                        created_at=datetime.fromisoformat(rd["created_at"]),
                    )
        except Exception as e:
            _log.warning("Failed to load token store: %s", e)

    def _save(self):
        try:
            data = {
                "access_tokens": {
                    t: {"token": td.token, "client_id": td.client_id, "scope": td.scope,
                        "expires_at": td.expires_at.isoformat(),
                        "refresh_token": td.refresh_token,
                        "created_at": td.created_at.isoformat()}
                    for t, td in self._access_tokens.items() if td.is_valid()
                },
                "refresh_tokens": {
                    t: {"token": rd.token, "client_id": rd.client_id, "scope": rd.scope,
                        "expires_at": rd.expires_at.isoformat(),
                        "created_at": rd.created_at.isoformat()}
                    for t, rd in self._refresh_tokens.items() if rd.is_valid()
                },
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self._path)
        except Exception as e:
            _log.warning("Failed to persist token store: %s", e)

    def create_access_token(self, client_id, scope, ttl=3600,
                            create_refresh_token=True, refresh_token_ttl=2592000) -> AccessTokenData:
        access_token = secrets.token_urlsafe(32)
        refresh_token = None
        if create_refresh_token:
            refresh_token = secrets.token_urlsafe(32)
            with self._lock:
                self._refresh_tokens[refresh_token] = RefreshTokenData(
                    token=refresh_token, client_id=client_id, scope=scope,
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=refresh_token_ttl),
                )
        data = AccessTokenData(
            token=access_token, client_id=client_id, scope=scope,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
            refresh_token=refresh_token,
        )
        with self._lock:
            self._access_tokens[access_token] = data
            self._maybe_cleanup()
        self._save()
        return data

    def get_access_token(self, token: str) -> Optional[AccessTokenData]:
        with self._lock:
            d = self._access_tokens.get(token)
            return d if d and d.is_valid() else None

    def get_refresh_token(self, token: str) -> Optional[RefreshTokenData]:
        with self._lock:
            d = self._refresh_tokens.get(token)
            return d if d and d.is_valid() else None

    def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            expired_a = [t for t, d in self._access_tokens.items() if not d.is_valid()]
            expired_r = [t for t, d in self._refresh_tokens.items() if not d.is_valid()]
            for t in expired_a:
                del self._access_tokens[t]
            for t in expired_r:
                del self._refresh_tokens[t]
            if expired_a or expired_r:
                self._save()
            self._last_cleanup = now


@dataclass
class ClientRegistration:
    client_id: str
    client_name: str
    redirect_uris: List[str]
    grant_types: List[str]
    response_types: List[str]
    scope: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ClientRegistrationStore:
    def __init__(self):
        self._clients: Dict[str, ClientRegistration] = {}
        self._lock = Lock()
        self._path = _oauth_storage_dir() / "clients.json"
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for cid, cd in raw.items():
                self._clients[cid] = ClientRegistration(
                    client_id=cd["client_id"], client_name=cd["client_name"],
                    redirect_uris=cd["redirect_uris"], grant_types=cd["grant_types"],
                    response_types=cd["response_types"], scope=cd["scope"],
                    created_at=datetime.fromisoformat(cd["created_at"]),
                )
        except Exception as e:
            _log.warning("Failed to load client store: %s", e)

    def _save(self):
        try:
            data = {
                cid: {"client_id": c.client_id, "client_name": c.client_name,
                      "redirect_uris": c.redirect_uris, "grant_types": c.grant_types,
                      "response_types": c.response_types, "scope": c.scope,
                      "created_at": c.created_at.isoformat()}
                for cid, c in self._clients.items()
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self._path)
        except Exception as e:
            _log.warning("Failed to persist client store: %s", e)

    def register_client(self, client_name, redirect_uris, grant_types,
                        response_types, scope="") -> ClientRegistration:
        client_id = secrets.token_urlsafe(16)
        client = ClientRegistration(
            client_id=client_id, client_name=client_name, redirect_uris=redirect_uris,
            grant_types=grant_types, response_types=response_types, scope=scope,
        )
        with self._lock:
            self._clients[client_id] = client
        self._save()
        return client

    def get_client(self, client_id: str) -> Optional[ClientRegistration]:
        with self._lock:
            return self._clients.get(client_id)


# Singletons
_code_store: Optional[AuthorizationCodeStore] = None
_token_store: Optional[TokenStore] = None
_client_store: Optional[ClientRegistrationStore] = None


def get_authorization_code_store() -> AuthorizationCodeStore:
    global _code_store
    if _code_store is None:
        _code_store = AuthorizationCodeStore()
    return _code_store


def get_token_store() -> TokenStore:
    global _token_store
    if _token_store is None:
        _token_store = TokenStore()
    return _token_store


def get_client_registration_store() -> ClientRegistrationStore:
    global _client_store
    if _client_store is None:
        _client_store = ClientRegistrationStore()
    return _client_store
