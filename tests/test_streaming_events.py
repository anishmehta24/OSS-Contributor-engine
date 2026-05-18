"""Tests for the in-process pub/sub used for SSE streaming."""
from __future__ import annotations

import asyncio

import pytest

from app.streaming.events import (
    clear_all,
    publish,
    subscribe,
    subscriber_count,
    unsubscribe,
)


@pytest.fixture(autouse=True)
def _wipe():
    clear_all()
    yield
    clear_all()


@pytest.mark.unit
async def test_publish_without_subscribers_returns_zero():
    delivered = publish("nobody", {"type": "x"})
    assert delivered == 0


@pytest.mark.unit
async def test_subscribe_then_publish_delivers():
    q = subscribe("inv1")
    delivered = publish("inv1", {"type": "ping"})
    assert delivered == 1
    event = await q.get()
    assert event == {"type": "ping"}


@pytest.mark.unit
async def test_multiple_subscribers_all_receive():
    q1 = subscribe("inv1")
    q2 = subscribe("inv1")
    delivered = publish("inv1", {"type": "ping"})
    assert delivered == 2
    assert (await q1.get()) == {"type": "ping"}
    assert (await q2.get()) == {"type": "ping"}


@pytest.mark.unit
async def test_keys_are_isolated():
    q_a = subscribe("A")
    q_b = subscribe("B")
    publish("A", {"k": "a"})
    publish("B", {"k": "b"})
    assert (await q_a.get()) == {"k": "a"}
    assert (await q_b.get()) == {"k": "b"}


@pytest.mark.unit
async def test_unsubscribe_stops_delivery():
    q = subscribe("inv1")
    unsubscribe("inv1", q)
    delivered = publish("inv1", {"type": "x"})
    assert delivered == 0
    assert subscriber_count("inv1") == 0


@pytest.mark.unit
async def test_unsubscribe_unknown_queue_is_noop():
    other = asyncio.Queue()
    unsubscribe("inv1", other)  # should not raise


@pytest.mark.unit
async def test_full_queue_drops_event_silently():
    q = subscribe("inv1", maxsize=2)
    publish("inv1", {"n": 1})
    publish("inv1", {"n": 2})
    delivered = publish("inv1", {"n": 3})  # queue is full
    assert delivered == 0
    # The two queued events are still there
    assert (await q.get())["n"] == 1
    assert (await q.get())["n"] == 2


@pytest.mark.unit
async def test_publish_to_one_full_one_open_subscriber():
    q_full = subscribe("inv1", maxsize=1)
    q_open = subscribe("inv1", maxsize=10)
    publish("inv1", {"n": 1})  # both receive (fills q_full)
    delivered = publish("inv1", {"n": 2})  # only q_open receives
    assert delivered == 1
    assert q_full.qsize() == 1
    assert q_open.qsize() == 2
