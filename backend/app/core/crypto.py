"""Symmetric encryption for provider credentials and browser session state.

Uses Fernet (AES-128-CBC + HMAC). The key comes from `CREDENTIAL_ENC_KEY` and
must never be logged or committed. Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class CryptoError(RuntimeError):
    """Raised when encryption/decryption cannot be performed."""


@lru_cache
def _fernet() -> Fernet:
    key = settings.credential_enc_key
    if not key:
        raise CryptoError(
            "CREDENTIAL_ENC_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"`.'
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:  # malformed key
        raise CryptoError("CREDENTIAL_ENC_KEY is not a valid Fernet key.") from exc


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string, returning a URL-safe token."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError("Failed to decrypt: invalid token or wrong key.") from exc
