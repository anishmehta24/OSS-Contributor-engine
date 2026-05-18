"""Thin httpx wrapper around the FastAPI service.

Kept separate from `app.py` so it can be unit-tested with respx (Streamlit
itself is hard to test mechanically — this isolates the side-effecty bits).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

DEFAULT_TIMEOUT = 600.0  # 10 minutes — profiling can be slow


class ApiError(Exception):
    """Raised when the API returns a non-2xx response."""
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.message = message


def _raise(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        body = response.json()
        msg = body.get("detail") or body.get("error") or response.text[:300]
    except Exception:
        msg = response.text[:300]
    raise ApiError(response.status_code, str(msg))


SESSION_COOKIE_NAME = "oss_engine_session"


class ApiClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = DEFAULT_TIMEOUT,
        session_cookie: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        if session_cookie:
            self.set_session(session_cookie)

    def set_session(self, signed_value: str) -> None:
        """Attach a session cookie that gets sent on every subsequent request."""
        self._client.cookies.set(SESSION_COOKIE_NAME, signed_value)

    def clear_session(self) -> None:
        self._client.cookies.delete(SESSION_COOKIE_NAME)

    @property
    def has_session(self) -> bool:
        return SESSION_COOKIE_NAME in self._client.cookies

    def close(self) -> None:
        self._client.close()

    # -----------------------------
    # Health / status
    # -----------------------------

    def health(self) -> dict[str, Any]:
        r = self._client.get("/health")
        _raise(r)
        return r.json()

    # -----------------------------
    # Auth (v2)
    # -----------------------------

    def me(self) -> dict[str, Any] | None:
        """Return the logged-in user's basic info, or None if not logged in."""
        r = self._client.get("/auth/me")
        if r.status_code == 401:
            return None
        _raise(r)
        return r.json()

    def logout(self) -> None:
        r = self._client.post("/auth/logout")
        _raise(r)

    # -----------------------------
    # Users (self-only in v2)
    # -----------------------------

    def profile_me(self) -> dict[str, Any]:
        """Blocks for ~30-90s while the Skill Profiler runs on the logged-in user."""
        r = self._client.post("/users/me/profile")
        _raise(r)
        return r.json()["profile"]

    def get_my_profile(self) -> dict[str, Any] | None:
        r = self._client.get("/users/me")
        if r.status_code in (404, 409):
            return None
        _raise(r)
        return r.json()["profile"]

    # -----------------------------
    # Matches
    # -----------------------------

    def get_my_matches(
        self,
        *,
        top: int = 10,
        difficulty: str = "any",
        explain: bool = True,
        mode: str = "general",
    ) -> list[dict[str, Any]]:
        r = self._client.get(
            "/users/me/matches",
            params={
                "top": top,
                "difficulty": difficulty,
                "explain": str(explain).lower(),
                "mode": mode,
            },
        )
        _raise(r)
        return r.json()["matches"]

    # -----------------------------
    # Investigations
    # -----------------------------

    def create_investigation(
        self,
        *,
        repo: str,
        issue_number: int,
    ) -> str:
        """Logged-in user implicit — the API uses your session."""
        r = self._client.post("/investigations", json={
            "repo": repo,
            "issue_number": issue_number,
        })
        _raise(r)
        return r.json()["job_id"]

    def get_investigation(self, investigation_id: str) -> dict[str, Any]:
        r = self._client.get(f"/investigations/{investigation_id}")
        _raise(r)
        return r.json()

    def stream_investigation(self, investigation_id: str) -> Iterator[dict[str, Any]]:
        """Yield parsed SSE events as dicts until a terminal event arrives.

        Uses self._client.stream so the session cookie is sent — a raw
        httpx.stream() call would lose it.
        """
        path = f"/investigations/{investigation_id}/stream"
        with self._client.stream("GET", path, timeout=DEFAULT_TIMEOUT) as r:
            r.raise_for_status()
            for raw_line in r.iter_lines():
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode().strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    payload = line[6:]
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    yield event
                    if event.get("type") in {"investigation_completed", "investigation_failed"}:
                        return

    def draft_pitch(self, investigation_id: str, *, force: bool = False) -> dict[str, Any]:
        r = self._client.post(
            f"/investigations/{investigation_id}/pitch",
            params={"force": str(force).lower()} if force else None,
        )
        _raise(r)
        return r.json()

    def investigation_cost(self, investigation_id: str) -> dict[str, Any]:
        r = self._client.get(f"/investigations/{investigation_id}/cost")
        _raise(r)
        return r.json()

    # -----------------------------
    # Admin
    # -----------------------------

    def global_cost(self) -> dict[str, Any]:
        r = self._client.get("/admin/cost")
        _raise(r)
        return r.json()

    def db_stats(self) -> dict[str, Any]:
        r = self._client.get("/admin/stats")
        _raise(r)
        return r.json()
