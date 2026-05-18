"""Async token bucket for GitHub Search API (30 req/min hard ceiling).

Used so the Search API path can't accidentally exceed the bucket. The core API
has a much higher ceiling (5000/hr) and is governed by the response-header-based
limiter inside the client, not this token bucket.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """Simple async token bucket. Refills continuously at `rate / period` tokens/sec.

    Usage:
        bucket = TokenBucket(rate=30, period=60)  # 30 per minute
        await bucket.acquire()                    # blocks until a token is free
    """

    rate: float           # tokens per period
    period: float         # period in seconds
    capacity: float | None = None  # max stored tokens; defaults to rate

    def __post_init__(self) -> None:
        self._capacity = self.capacity if self.capacity is not None else self.rate
        self._tokens = float(self._capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * (self.rate / self.period))
        self._last_refill = now

    async def acquire(self, tokens: float = 1.0) -> None:
        if tokens > self._capacity:
            raise ValueError(f"Cannot acquire {tokens} from a bucket with capacity {self._capacity}")
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / (self.rate / self.period)
            await asyncio.sleep(wait)

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens
