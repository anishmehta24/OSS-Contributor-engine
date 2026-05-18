"""Background-task orchestration. In-process for v1; swappable for Celery later."""
from app.jobs.runner import (
    active_jobs,
    spawn,
    wait_for,
    wait_for_all,
)

__all__ = ["active_jobs", "spawn", "wait_for", "wait_for_all"]
