"""Fire-and-forget task runner.

Use `spawn(coro)` instead of `asyncio.create_task(coro)` directly so we
keep a strong reference (otherwise the GC can collect the task mid-run)
and so tests can `await wait_for_all()` to drain background work
before assertions.

This is in-process only — restart the FastAPI worker and queued tasks
are lost. Acceptable for single-tenant v1; swap for Celery + Redis once
multi-worker becomes real.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any

log = logging.getLogger(__name__)

# Strong references so tasks aren't GC'd. Auto-pruned on completion.
_tasks: set[asyncio.Task] = set()


def spawn(coro: Awaitable[Any], *, name: str | None = None) -> asyncio.Task:
    """Schedule `coro` on the current event loop, retain a strong ref."""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("background_task_failed: %s — %r", task.get_name(), exc)


def active_jobs() -> int:
    return len(_tasks)


async def wait_for_all(timeout: float | None = None) -> None:
    """Block until all currently-active background tasks finish.

    Mostly for tests — production code should rely on per-investigation
    state in the DB instead.
    """
    if not _tasks:
        return
    pending = list(_tasks)
    if timeout is None:
        await asyncio.gather(*pending, return_exceptions=True)
    else:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )


async def wait_for(task: asyncio.Task, timeout: float | None = None) -> Any:
    """Await a single spawned task, optionally with a timeout."""
    if timeout is None:
        return await task
    return await asyncio.wait_for(task, timeout=timeout)


def cancel_all() -> None:
    """Test-only: cancel anything still in flight."""
    for t in list(_tasks):
        t.cancel()
    _tasks.clear()
