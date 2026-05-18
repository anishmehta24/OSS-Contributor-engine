"""Tests for the in-process background job runner."""
from __future__ import annotations

import asyncio

import pytest

from app.jobs.runner import (
    active_jobs,
    cancel_all,
    spawn,
    wait_for,
    wait_for_all,
)


@pytest.fixture(autouse=True)
def _drain():
    cancel_all()
    yield
    cancel_all()


@pytest.mark.unit
async def test_spawn_runs_coroutine_to_completion():
    result = {"n": 0}

    async def increment():
        result["n"] += 1

    task = spawn(increment())
    await task
    assert result["n"] == 1


@pytest.mark.unit
async def test_spawn_holds_strong_reference_so_gc_doesnt_kill_it():
    result: list[str] = []

    async def slow():
        await asyncio.sleep(0.05)
        result.append("done")

    spawn(slow())  # we deliberately drop the return value
    assert active_jobs() == 1
    await wait_for_all()
    assert result == ["done"]
    assert active_jobs() == 0


@pytest.mark.unit
async def test_wait_for_all_drains_multiple_tasks():
    results: list[int] = []

    async def add(n: int):
        await asyncio.sleep(0.01 * n)
        results.append(n)

    spawn(add(1))
    spawn(add(2))
    spawn(add(3))
    await wait_for_all()
    assert sorted(results) == [1, 2, 3]
    assert active_jobs() == 0


@pytest.mark.unit
async def test_wait_for_single_task():
    async def value():
        return 42

    task = spawn(value())
    result = await wait_for(task)
    assert result == 42


@pytest.mark.unit
async def test_wait_for_all_with_no_tasks_is_noop():
    await wait_for_all()  # should not hang
    assert active_jobs() == 0


@pytest.mark.unit
async def test_failed_task_is_removed_from_active_set():
    async def boom():
        raise RuntimeError("expected")

    spawn(boom())
    await wait_for_all()  # gathers with return_exceptions
    assert active_jobs() == 0


@pytest.mark.unit
async def test_task_name_is_preserved():
    async def noop():
        pass

    task = spawn(noop(), name="my-task")
    assert task.get_name() == "my-task"
    await task
