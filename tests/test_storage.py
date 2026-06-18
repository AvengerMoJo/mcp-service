"""Token store + client registration store tests."""

from __future__ import annotations

import json
import time

import pytest

from mcp_service.oauth.storage import (
    AccessTokenData,
    AuthorizationCodeData,
    AuthorizationCodeStore,
    ClientRegistrationStore,
    RefreshTokenData,
    TokenStore,
)


class TestAuthorizationCodeStore:
    def test_create_returns_data(self):
        store = AuthorizationCodeStore()
        data = store.create(
            client_id="c1",
            redirect_uri="http://x/cb",
            scope="mcp:read",
            code_challenge="ch",
            code_challenge_method="S256",
        )
        assert isinstance(data, AuthorizationCodeData)
        assert data.client_id == "c1"
        assert data.redirect_uri == "http://x/cb"
        assert data.scope == "mcp:read"
        assert data.code_challenge == "ch"
        assert data.code_challenge_method == "S256"
        assert data.is_valid()
        assert data.is_expired() is False

    def test_get_returns_existing(self):
        store = AuthorizationCodeStore()
        data = store.create(
            "c", "http://x/cb", "s", "ch", "S256"
        )
        assert store.get(data.code) is data

    def test_get_missing_returns_none(self):
        store = AuthorizationCodeStore()
        assert store.get("nope") is None

    def test_mark_used(self):
        store = AuthorizationCodeStore()
        data = store.create("c", "http://x/cb", "s", "ch", "S256")
        assert store.mark_used(data.code) is True
        assert store.get(data.code).used is True
        assert store.get(data.code).is_valid() is False
        # second mark is still True (idempotent on stored code)
        assert store.mark_used(data.code) is True

    def test_mark_used_missing(self):
        store = AuthorizationCodeStore()
        assert store.mark_used("nope") is False

    def test_ttl_expires_code(self):
        store = AuthorizationCodeStore()
        data = store.create("c", "http://x/cb", "s", "ch", "S256", ttl=1)
        assert data.is_valid()
        time.sleep(1.1)
        assert data.is_expired()
        assert store.get(data.code).is_valid() is False

    def test_cleanup_runs_on_create(self):
        store = AuthorizationCodeStore(cleanup_interval=0)
        d = store.create("c", "http://x/cb", "s", "ch", "S256", ttl=1)
        time.sleep(1.1)
        # trigger cleanup
        store.create("c2", "http://x/cb", "s", "ch", "S256")
        assert store.get(d.code) is None


class TestTokenStore:
    def test_create_access_token_issues_refresh(self):
        store = TokenStore()
        td = store.create_access_token(client_id="c", scope="mcp:read")
        assert isinstance(td, AccessTokenData)
        assert td.client_id == "c"
        assert td.scope == "mcp:read"
        assert td.refresh_token is not None
        assert td.is_valid()
        assert td.get_expires_in() > 0

    def test_create_without_refresh(self):
        store = TokenStore()
        td = store.create_access_token("c", "s", create_refresh_token=False)
        assert td.refresh_token is None

    def test_get_access_token(self):
        store = TokenStore()
        td = store.create_access_token("c", "s")
        assert store.get_access_token(td.token) is td
        assert store.get_access_token("missing") is None

    def test_get_refresh_token(self):
        store = TokenStore()
        td = store.create_access_token("c", "s")
        rd = store.get_refresh_token(td.refresh_token)
        assert isinstance(rd, RefreshTokenData)
        assert rd.client_id == "c"
        assert store.get_refresh_token("missing") is None

    def test_persists_to_disk(self, tmp_oauth_dir):
        store = TokenStore()
        td = store.create_access_token("c", "s")
        path = tmp_oauth_dir / "tokens.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert td.token in data["access_tokens"]
        assert td.refresh_token in data["refresh_tokens"]

    def test_loads_from_disk(self, tmp_oauth_dir):
        store = TokenStore()
        td = store.create_access_token("c", "s")
        # New store reads the same file
        store2 = TokenStore()
        assert store2.get_access_token(td.token) is not None
        assert store2.get_refresh_token(td.refresh_token) is not None

    def test_expired_tokens_filtered_on_load(self, tmp_oauth_dir):
        # Write a tokens file with an expired access token.
        path = tmp_oauth_dir / "tokens.json"
        path.write_text(json.dumps({
            "access_tokens": {
                "expired-token": {
                    "token": "expired-token",
                    "client_id": "c",
                    "scope": "s",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                    "refresh_token": None,
                    "created_at": "2000-01-01T00:00:00+00:00",
                }
            },
            "refresh_tokens": {},
        }))
        store = TokenStore()
        assert store.get_access_token("expired-token") is None

    def test_get_expires_in_zero_when_expired(self):
        store = TokenStore()
        td = store.create_access_token("c", "s", ttl=1)
        time.sleep(1.1)
        fetched = store.get_access_token(td.token)
        assert fetched is None

    def test_cleanup_removes_expired(self):
        store = TokenStore(cleanup_interval=0)
        td = store.create_access_token("c", "s", ttl=1)
        time.sleep(1.1)
        # Trigger another create → cleanup sweeps.
        store.create_access_token("c2", "s")
        assert store.get_access_token(td.token) is None


class TestClientRegistrationStore:
    def test_register_returns_client(self):
        store = ClientRegistrationStore()
        c = store.register_client(
            client_name="demo",
            redirect_uris=["http://x/cb"],
            grant_types=["authorization_code"],
            response_types=["code"],
            scope="mcp:read",
        )
        assert c.client_id
        assert c.client_name == "demo"
        assert c.redirect_uris == ["http://x/cb"]
        assert c.grant_types == ["authorization_code"]
        assert c.scope == "mcp:read"

    def test_register_persists(self, tmp_oauth_dir):
        store = ClientRegistrationStore()
        c = store.register_client("d", ["http://x"], ["authorization_code"], ["code"])
        path = tmp_oauth_dir / "clients.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert c.client_id in data

    def test_loads_persisted_clients(self, tmp_oauth_dir):
        store = ClientRegistrationStore()
        c = store.register_client("d", ["http://x"], ["authorization_code"], ["code"])
        store2 = ClientRegistrationStore()
        assert store2.get_client(c.client_id) is not None

    def test_get_client_missing(self):
        store = ClientRegistrationStore()
        assert store.get_client("nope") is None

    def test_unique_client_ids(self):
        store = ClientRegistrationStore()
        ids = {
            store.register_client("d", ["http://x"], ["authorization_code"], ["code"]).client_id
            for _ in range(50)
        }
        assert len(ids) == 50


class TestSingletons:
    def test_code_store_is_cached(self):
        from mcp_service.oauth.storage import get_authorization_code_store

        assert get_authorization_code_store() is get_authorization_code_store()

    def test_token_store_is_cached(self):
        from mcp_service.oauth.storage import get_token_store

        assert get_token_store() is get_token_store()

    def test_client_store_is_cached(self):
        from mcp_service.oauth.storage import get_client_registration_store

        assert get_client_registration_store() is get_client_registration_store()