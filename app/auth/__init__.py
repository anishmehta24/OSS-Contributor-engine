"""Authentication: GitHub OAuth + signed sessions + token encryption.

This package intentionally does NOT eagerly import its submodules — that
caused a circular import once `app.auth.dependencies` started depending
on `app.api.dependencies` (which depends back on `app.auth.dependencies`).
Always import from the submodule directly:

    from app.auth.dependencies import current_user, optional_current_user
    from app.auth.oauth import build_authorize_url, exchange_code, fetch_github_user
    from app.auth.sessions import sign_session, read_session
    from app.auth.crypto import encrypt_token, decrypt_token
"""
