"""Symmetric encryption for OAuth access tokens at rest.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before
hitting the DB and decrypted only when we need to call GitHub on behalf
of the user. Key comes from SESSION_SECRET — same key reused for both
session signing and token encryption to keep the user setup story to
one variable.

If SESSION_SECRET is missing or invalid, encryption functions raise.
This is intentional — we never want to silently fall back to storing
plaintext tokens.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TokenCryptoError(Exception):
    """Raised when encryption or decryption fails."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    secret = settings.session_secret
    if not secret:
        raise TokenCryptoError(
            "SESSION_SECRET is not set — generate with "
            "`uv run python scripts/gen_session_secret.py` and add to .env"
        )
    try:
        return Fernet(secret.encode() if isinstance(secret, str) else secret)
    except (ValueError, TypeError) as e:
        raise TokenCryptoError(
            f"SESSION_SECRET is not a valid Fernet key (must be 32 url-safe "
            f"base64 bytes): {e}"
        ) from e


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token; returns base64 ciphertext as a string."""
    if not plaintext:
        raise TokenCryptoError("Refusing to encrypt empty token")
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token previously produced by encrypt_token."""
    if not ciphertext:
        raise TokenCryptoError("Refusing to decrypt empty ciphertext")
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise TokenCryptoError(
            "Token decrypt failed — SESSION_SECRET may have changed "
            "(stored tokens are now unreadable; users will need to re-auth)"
        ) from e
