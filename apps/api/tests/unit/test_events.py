"""Unit tests: the in-memory event bus that powers live updates."""

from __future__ import annotations

import asyncio

import pytest

from bozii.agent_runtime.events import EventBus


@pytest.mark.asyncio
async def test_bus_fans_out_to_subscribers():
    bus = EventBus()
    queue_a = bus.subscribe("task:1")
    queue_b = bus.subscribe("activity")
    await bus.publish("task:1", {"type": "task_event", "seq": 1})
    await bus.publish("activity", {"type": "task_event", "seq": 1})

    first = await asyncio.wait_for(queue_a.get(), timeout=1)
    second = await asyncio.wait_for(queue_b.get(), timeout=1)
    assert first["seq"] == 1 and second["seq"] == 1

    # An unrelated channel must not receive it.
    await bus.publish("task:2", {"type": "task_event", "seq": 99})
    assert queue_a.empty() and queue_b.empty()

    bus.unsubscribe("task:1", queue_a)
    await bus.publish("task:1", {"type": "task_event", "seq": 2})
    assert queue_a.empty()


@pytest.mark.asyncio
async def test_stream_emits_hello_then_events():
    bus = EventBus()

    async def consume():
        seen = []
        async for event in bus.stream(["activity"], heartbeat_seconds=0.2):
            seen.append(event)
            if len(seen) >= 3:
                break
        return seen

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await bus.publish("activity", {"type": "task_event", "seq": 7})
    seen = await asyncio.wait_for(consumer, timeout=5)
    assert seen[0]["type"] == "hello"
    kinds = {e["type"] for e in seen}
    assert "task_event" in kinds
    # A heartbeat is produced when nothing happens (0.2s in this test).
    assert any(e["type"] == "heartbeat" for e in seen)


@pytest.mark.asyncio
async def test_slow_subscriber_does_not_crash_the_bus():
    bus = EventBus()
    queue = bus.subscribe("activity")
    for i in range(600):  # exceeds maxsize=500
        await bus.publish("activity", {"type": "task_event", "seq": i})
    assert queue.full()
    # Publishing beyond capacity must not raise.
    await bus.publish("activity", {"type": "task_event", "seq": 999})
    bus.unsubscribe("activity", queue)
