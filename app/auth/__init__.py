"""Authentication: GitHub OAuth + signed sessions + token encryption.

Public API:
    from app.auth import current_user, optional_current_user
    from app.auth.oauth import build_authorize_url, exchange_code, fetch_github_user
    from app.auth.sessions import sign_session, read_session
    from app.auth.crypto import encrypt_token, decrypt_token
"""
from app.auth.dependencies import current_user, optional_current_user

__all__ = ["current_user", "optional_current_user"]
