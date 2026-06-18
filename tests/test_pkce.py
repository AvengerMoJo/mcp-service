"""PKCE utility tests — RFC 7636."""

import base64
import hashlib

import pytest

from mcp_service.oauth.pkce import (
    generate_code_challenge,
    generate_code_verifier,
    generate_pkce_pair,
    is_valid_code_verifier,
    verify_code_challenge,
)


class TestCodeVerifier:
    def test_length_in_range(self):
        v = generate_code_verifier()
        assert 43 <= len(v) <= 128

    def test_custom_length(self):
        assert len(generate_code_verifier(64)) == 64
        assert len(generate_code_verifier(43)) == 43
        assert len(generate_code_verifier(128)) == 128

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError):
            generate_code_verifier(42)
        with pytest.raises(ValueError):
            generate_code_verifier(129)

    def test_uses_unreserved_chars(self):
        v = generate_code_verifier()
        allowed = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        )
        assert set(v) <= allowed


class TestCodeChallenge:
    def test_s256_deterministic(self):
        v = "a" * 64
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert generate_code_challenge(v, "S256") == expected

    def test_plain_returns_verifier(self):
        v = "x" * 64
        assert generate_code_challenge(v, "plain") == v

    def test_unsupported_method_raises(self):
        with pytest.raises(ValueError):
            generate_code_challenge("v", "plainish")


class TestVerifyChallenge:
    def test_round_trip_s256(self):
        v, c = generate_pkce_pair()
        assert verify_code_challenge(v, c, "S256") is True

    def test_wrong_verifier_fails(self):
        v, c = generate_pkce_pair()
        assert verify_code_challenge(v + "x", c, "S256") is False

    def test_round_trip_plain(self):
        v = "x" * 64
        assert verify_code_challenge(v, v, "plain") is True

    def test_invalid_method_returns_false(self):
        assert verify_code_challenge("v", "v", "weird") is False


class TestIsValidCodeVerifier:
    @pytest.mark.parametrize(
        "v",
        [
            "a" * 43,
            "a" * 128,
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop-_~.0123456789",
        ],
    )
    def test_valid(self, v):
        assert is_valid_code_verifier(v) is True

    @pytest.mark.parametrize(
        "v",
        [
            "",
            "a" * 42,
            "a" * 129,
            "contains spaces",
            "has/slash",
            "plus+sign",
        ],
    )
    def test_invalid(self, v):
        assert is_valid_code_verifier(v) is False


class TestPkcePair:
    def test_pair_unique(self):
        pairs = {generate_pkce_pair() for _ in range(20)}
        assert len(pairs) == 20

    def test_pair_components_distinct(self):
        v, c = generate_pkce_pair()
        assert v != c