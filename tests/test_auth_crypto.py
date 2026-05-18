"""Tests for token encryption helpers."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.auth import crypto as crypto_mod
from app.auth.crypto import TokenCryptoError, decrypt_token, encrypt_token


@pytest.fixture(autouse=True)
def _real_fernet(monkeypatch):
    """Every test gets a real key + clears the lru_cache."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto_mod.settings, "session_secret", key)
    crypto_mod._get_fernet.cache_clear()
    yield
    crypto_mod._get_fernet.cache_clear()


@pytest.mark.unit
def test_round_trip():
    enc = encrypt_token("gho_my_token_123")
    assert enc != "gho_my_token_123"  # actually encrypted
    assert decrypt_token(enc) == "gho_my_token_123"


@pytest.mark.unit
def test_encrypt_empty_raises():
    with pytest.raises(TokenCryptoError):
        encrypt_token("")


@pytest.mark.unit
def test_decrypt_empty_raises():
    with pytest.raises(TokenCryptoError):
        decrypt_token("")


@pytest.mark.unit
def test_decrypt_garbage_raises():
    with pytest.raises(TokenCryptoError):
        decrypt_token("not-a-valid-fernet-token")


@pytest.mark.unit
def test_missing_secret_raises(monkeypatch):
    monkeypatch.setattr(crypto_mod.settings, "session_secret", "")
    crypto_mod._get_fernet.cache_clear()
    with pytest.raises(TokenCryptoError, match="SESSION_SECRET"):
        encrypt_token("anything")


@pytest.mark.unit
def test_invalid_key_format_raises(monkeypatch):
    monkeypatch.setattr(crypto_mod.settings, "session_secret", "not-a-real-fernet-key")
    crypto_mod._get_fernet.cache_clear()
    with pytest.raises(TokenCryptoError, match="not a valid Fernet key"):
        encrypt_token("anything")


@pytest.mark.unit
def test_two_secrets_cannot_decrypt_each_others_tokens(monkeypatch):
    key1 = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto_mod.settings, "session_secret", key1)
    crypto_mod._get_fernet.cache_clear()
    enc = encrypt_token("hi")

    key2 = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto_mod.settings, "session_secret", key2)
    crypto_mod._get_fernet.cache_clear()
    with pytest.raises(TokenCryptoError):
        decrypt_token(enc)
