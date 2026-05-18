"""In-process pub/sub for streaming investigation progress to SSE clients.

Single-process only. If we ever scale to multiple workers, swap the backing
store for Redis pub/sub — the public API (publish/subscribe) stays the same.
"""
from app.streaming.events import publish, subscribe, unsubscribe

__all__ = ["publish", "subscribe", "unsubscribe"]
