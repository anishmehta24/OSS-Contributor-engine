"""Tests for signed session cookies + OAuth state cookies."""
from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from app.auth import sessions as sess_mod
from app.auth.sessions import (
    SessionError,
    read_oauth_state,
    read_session,
    sign_oauth_state,
    sign_session,
)


@pytest.fixture(autouse=True)
def _fresh_secret(monkeypatch):
    secret = Fernet.generate_key().decode()
    monkeypatch.setattr(sess_mod.settings, "session_secret", secret)
    monkeypatch.setattr(sess_mod.settings, "session_max_age_s", 60)
    yield


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_session_round_trip():
    signed = sign_session(user_id=42)
    assert isinstance(signed, str)
    payload = read_session(signed)
    assert payload == {"user_id": 42}


@pytest.mark.unit
def test_session_rejects_missing():
    with pytest.raises(SessionError, match="No session"):
        read_session(None)
    with pytest.raises(SessionError, match="No session"):
        read_session("")


@pytest.mark.unit
def test_session_rejects_tampered():
    signed = sign_session(user_id=1)
    tampered = signed[:-3] + "AAA"
    with pytest.raises(SessionError, match="Invalid session signature"):
        read_session(tampered)


@pytest.mark.unit
def test_session_rejects_wrong_secret(monkeypatch):
    signed = sign_session(user_id=1)
    # Rotate secret — old cookie should now be invalid
    monkeypatch.setattr(sess_mod.settings, "session_secret",
                        Fernet.generate_key().decode())
    with pytest.raises(SessionError):
        read_session(signed)


# ---------------------------------------------------------------------------
# OAuth state
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_oauth_state_round_trip():
    signed = sign_oauth_state("random-state-abc123")
    assert read_oauth_state(signed) == "random-state-abc123"


@pytest.mark.unit
def test_oauth_state_rejects_missing():
    with pytest.raises(SessionError, match="No OAuth state"):
        read_oauth_state(None)


@pytest.mark.unit
def test_oauth_state_rejects_tampered():
    signed = sign_oauth_state("abc")
    # Tamper with the payload portion (everything before the first dot is the
    # base64 payload; after that is the timestamp+signature).
    payload_part, _, rest = signed.partition(".")
    tampered = (payload_part[:-2] + "ZZ") + "." + rest
    with pytest.raises(SessionError, match="Invalid OAuth state"):
        read_oauth_state(tampered)


@pytest.mark.unit
def test_session_and_state_are_separate_namespaces():
    """Salts differ so a session cookie can't impersonate a state cookie."""
    sess = sign_session(user_id=1)
    with pytest.raises(SessionError):
        read_oauth_state(sess)


@pytest.mark.unit
def test_session_missing_secret_raises(monkeypatch):
    monkeypatch.setattr(sess_mod.settings, "session_secret", "")
    with pytest.raises(SessionError, match="SESSION_SECRET"):
        sign_session(user_id=1)


@pytest.mark.unit
def test_session_expiry(monkeypatch):
    """max_age check works.

    itsdangerous rounds timestamps to whole seconds, so we use a 1s window
    and wait 3s to make sure we're past the boundary regardless of jitter.
    """
    monkeypatch.setattr(sess_mod.settings, "session_max_age_s", 1)
    signed = sign_session(user_id=1)
    time.sleep(3.0)
    with pytest.raises(SessionError, match="expired"):
        read_session(signed)
