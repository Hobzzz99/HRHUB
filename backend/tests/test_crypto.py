"""Tests for Fernet credential encryption."""

from __future__ import annotations

import pytest

from app.core.crypto import CryptoError, decrypt, encrypt


def test_roundtrip():
    secret = "s3cr3t-password"
    token = encrypt(secret)
    assert token != secret
    assert decrypt(token) == secret


def test_tampered_token_raises():
    token = encrypt("hello")
    # Corrupt a leading character so the decoded bytes (and HMAC) change.
    corrupted = ("A" if token[0] != "A" else "B") + token[1:]
    with pytest.raises(CryptoError):
        decrypt(corrupted)


def test_malformed_token_raises():
    with pytest.raises(CryptoError):
        decrypt("not-a-valid-fernet-token")
