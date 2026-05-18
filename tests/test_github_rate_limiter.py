"""Token-bucket sanity tests."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.tools.github.rate_limiter import TokenBucket


@pytest.mark.unit
async def test_burst_within_capacity_is_instant():
    bucket = TokenBucket(rate=10, period=1.0)  # 10/sec
    start = time.monotonic()
    for _ in range(10):
        await bucket.acquire()
    assert (time.monotonic() - start) < 0.1


@pytest.mark.unit
async def test_acquire_beyond_capacity_blocks_until_refill():
    bucket = TokenBucket(rate=10, period=0.5)  # 10 per 0.5s = 20/sec
    # drain
    for _ in range(10):
        await bucket.acquire()
    # next acquire must wait for at least one token to refill
    start = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - start
    # one token at 20/sec = ~0.05s minimum (allow generous slack)
    assert elapsed >= 0.04


@pytest.mark.unit
async def test_concurrent_acquires_do_not_overspend():
    bucket = TokenBucket(rate=5, period=1.0)
    results = await asyncio.gather(*(bucket.acquire() for _ in range(5)))
    assert results == [None] * 5
    assert bucket.available < 1.0


@pytest.mark.unit
async def test_cannot_acquire_more_than_capacity():
    bucket = TokenBucket(rate=5, period=1.0)
    with pytest.raises(ValueError):
        await bucket.acquire(tokens=999)
