"""Pilot Coordinator (v3 — Autonomous Contribution Pilot).

Public surface:
    from app.pilot import run_pilot, PilotConfig, PilotRunRow
"""
from app.pilot.pilot import reconcile_orphaned_pilots, run_pilot
from app.pilot.pr_opener import PROpenerError, open_pilot_pr
from app.pilot.pusher import PusherError, push_pilot_branch
from app.pilot.safety import cost_cap_exceeded, is_repo_refused
from app.pilot.schemas import (
    CreatePilotResponse,
    OpenPRResponse,
    PilotConfig,
    PilotRunRow,
    PilotStatus,
    PushPilotResponse,
)

__all__ = [
    "CreatePilotResponse",
    "OpenPRResponse",
    "PROpenerError",
    "PilotConfig",
    "PilotRunRow",
    "PilotStatus",
    "PushPilotResponse",
    "PusherError",
    "cost_cap_exceeded",
    "is_repo_refused",
    "open_pilot_pr",
    "push_pilot_branch",
    "reconcile_orphaned_pilots",
    "run_pilot",
]
