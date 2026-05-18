"""Generate a fresh SESSION_SECRET for .env.

Usage:
    uv run python scripts/gen_session_secret.py

The key works for both:
    - itsdangerous session cookie signing
    - Fernet token encryption (must be 32 url-safe base64 bytes)

Rotating this key invalidates all existing sessions AND makes stored
OAuth tokens unreadable (users will have to log in again).
"""
from cryptography.fernet import Fernet


def main() -> None:
    key = Fernet.generate_key().decode("ascii")
    print(key)
    print()
    print("Copy the line above and add to .env as:")
    print(f"SESSION_SECRET={key}")


if __name__ == "__main__":
    main()
