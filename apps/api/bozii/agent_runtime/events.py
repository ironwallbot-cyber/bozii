"""Event bus + persisted task events.

Every state change, tool call and approval request is written to the
`task_events` table (the source of truth) and simultaneously broadcast on an
in-memory bus that powers the SSE stream.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bozii.models import TaskEvent

logger = logging.getLogger("bozii.events")


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[channel].add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        self._subs[channel].discard(queue)
        if not self._subs[channel]:
            self._subs.pop(channel, None)

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        for queue in list(self._subs.get(channel, ())):
            try:
                queue.put_nowait({"channel": channel, **event})
            except asyncio.QueueFull:
                logger.warning("SSE subscriber for %s is too slow; dropping event", channel)

    async def stream(self, channels: list[str], heartbeat_seconds: float = 15.0) -> AsyncIterator[dict]:
        queues = [self.subscribe(channel) for channel in channels]
        try:
            yield {"type": "hello", "channels": channels, "ts": datetime.now(timezone.utc).isoformat()}
            while True:
                try:
                    event = await asyncio.wait_for(
                        _first(queues), timeout=heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat", "ts": datetime.now(timezone.utc).isoformat()}
                    continue
                if event is not None:
                    yield event
        finally:
            for channel, queue in zip(channels, queues):
                self.unsubscribe(channel, queue)


async def _first(queues: list[asyncio.Queue]) -> dict | None:
    """Wait until any subscriber queue yields an event."""
    pending = [asyncio.create_task(q.get()) for q in queues]
    try:
        done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            return task.result()
        return None
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus


async def record_event(
    db: AsyncSession,
    task_id: str | None,
    type_: str,
    message: str,
    payload: dict[str, Any] | None = None,
    *,
    publish: bool = True,
    user_id: str | None = None,
) -> TaskEvent | None:
    """Persist a task event and broadcast it."""
    if task_id is None:
        return None
    current = (
        await db.execute(select(func.max(TaskEvent.seq)).where(TaskEvent.task_id == task_id))
    ).scalar()
    event = TaskEvent(
        task_id=task_id,
        seq=int(current or 0) + 1,
        type=type_,
        message=message[:4000],
        payload=payload or {},
    )
    db.add(event)
    await db.flush()
    if publish:
        data = {
            "type": "task_event",
            "task_id": task_id,
            "seq": event.seq,
            "event_type": type_,
            "message": event.message,
            "payload": event.payload,
            "ts": event.created_at.isoformat() if event.created_at else None,
            "user_id": user_id,
        }
        await _bus.publish(f"task:{task_id}", data)
        await _bus.publish("activity", data)
    return event


__all__ = ["EventBus", "get_bus", "record_event"]
