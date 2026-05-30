"""Safety rails for the autonomous pilot (Batch 37).

Two independent guards, both pure/cheap so they can run on the hot path:

  - `is_repo_refused(repo)` — is this repo on the configured opt-out list?
    Maintainers who don't want AI-generated PRs go here. Blocks fork +
    push + PR. Checked at pilot-create time (fail early, before spending
    LLM budget) AND again in the pusher (defense in depth).

  - `cost_cap_exceeded(session, user_id)` — has this user blown their
    lifetime LLM-spend ceiling? The pilot is the most expensive op, so we
    gate it here. 0 cap = unlimited.

Refuse-list matching:
  - case-insensitive
  - an entry of "owner" blocks every repo under that owner
  - an entry of "owner/repo" blocks just that repo
"""
from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from app.core.config import settings
from app.telemetry import user_cost_usd

log = structlog.get_logger(__name__)


def _parse_refuse_list(raw: str) -> set[str]:
    """Comma-separated env value → lowercased set of entries."""
    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def is_repo_refused(repo_full_name: str, *, refuse_list: str | None = None) -> bool:
    """True if `owner/repo` (or its owner) is on the refuse-list.

    `refuse_list` overrides the configured value (for tests). Pass the
    raw comma-separated string, same shape as the env var.
    """
    raw = settings.pilot_refuse_list if refuse_list is None else refuse_list
    entries = _parse_refuse_list(raw)
    if not entries:
        return False

    full = repo_full_name.strip().lower()
    if "/" not in full:
        # Bare owner passed in — treat as owner match only.
        return full in entries
    owner = full.split("/", 1)[0]
    return full in entries or owner in entries


def cost_cap_exceeded(session: Session, user_id: int) -> tuple[bool, float, float]:
    """Returns (exceeded, spent_usd, cap_usd).

    `exceeded` is False when the cap is 0 (unlimited) regardless of spend.
    """
    cap = settings.max_user_cost_usd
    if cap <= 0:
        return False, 0.0, 0.0
    spent = user_cost_usd(session, user_id)
    return spent >= cap, spent, cap


__all__ = ["cost_cap_exceeded", "is_repo_refused"]
