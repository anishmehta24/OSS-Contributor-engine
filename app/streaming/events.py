"""In-process pub/sub keyed by investigation_id.

Each subscriber gets its own asyncio.Queue. Publishers fan-out to every
subscriber for that key. Slow subscribers (queue full) silently drop the
event — we don't want one stuck consumer to back up the publisher.

Lifecycle:
    sub = subscribe(inv_id)        # registers and returns a queue
    ...                            # consumer loops on sub.get()
    unsubscribe(inv_id, sub)       # cleans up when consumer leaves

Producers must NOT hold references after the investigation completes.
The terminal events ("investigation_completed" / "investigation_failed")
signal consumers to break their loops.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from typing import Any

# investigation_id -> list of subscriber queues
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

DEFAULT_QUEUE_SIZE = 100


def subscribe(investigation_id: str, *, maxsize: int = DEFAULT_QUEUE_SIZE) -> asyncio.Queue:
    """Register a new subscriber and return its queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _subscribers[investigation_id].append(q)
    return q


def unsubscribe(investigation_id: str, queue: asyncio.Queue) -> None:
    """Remove a subscriber. Idempotent."""
    subs = _subscribers.get(investigation_id)
    if subs is None:
        return
    with contextlib.suppress(ValueError):
        subs.remove(queue)
    if not subs:
        _subscribers.pop(investigation_id, None)


def publish(investigation_id: str, event: dict[str, Any]) -> int:
    """Fan-out an event to all current subscribers.

    Returns the number of subscribers that received the event.
    Slow subscribers (queue full) are skipped — we don't want one stuck
    consumer to block the producer.
    """
    subs = _subscribers.get(investigation_id)
    if not subs:
        return 0
    delivered = 0
    for q in subs:
        try:
            q.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            # Drop the event for this subscriber; they're too slow.
            continue
    return delivered


def subscriber_count(investigation_id: str) -> int:
    return len(_subscribers.get(investigation_id, []))


def clear_all() -> None:
    """Test-only: wipe all subscriptions."""
    _subscribers.clear()
