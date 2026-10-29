"""In-process task queue and worker pool.

Single-process queue by design: Bozii is self-hostable and starts with zero
external dependencies. Workers pull queued tasks and run them through
:class:`~bozii.agent_runtime.runner.TaskRunner`.

Delegating tasks wait for their children by *pumping the queue themselves*
instead of idling, which makes parent/child waiting deadlock-free even when all
workers are busy.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bozii.config import get_settings
from bozii.models import Task

logger = logging.getLogger("bozii.queue")

TERMINAL = {"completed", "failed", "cancelled"}


class TaskQueue:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], concurrency: int | None = None):
        settings = get_settings()
        self.session_factory = session_factory
        self.concurrency = concurrency or settings.task_workers
        self.max_concurrent = max(self.concurrency, settings.max_concurrent_tasks)
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._pending_set: set[str] = set()
        self._running: set[str] = set()
        self._workers: list[asyncio.Task] = []
        self._wait_depth = 0
        self.stopped = asyncio.Event()

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._workers:
            return
        self.stopped.clear()
        for i in range(self.concurrency):
            self._workers.append(asyncio.create_task(self._worker(i), name=f"bozii-worker-{i}"))
        logger.info("Task queue started with %d workers", self.concurrency)

    async def stop(self) -> None:
        self.stopped.set()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def _worker(self, index: int) -> None:
        while not self.stopped.is_set():
            try:
                worked = await self.process_one(timeout=0.5)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.exception("Worker %s error", index)
                await asyncio.sleep(0.5)
            if not worked:
                await asyncio.sleep(0.05)

    # ----------------------------------------------------------------- queue
    async def enqueue(self, task_id: str) -> bool:
        if task_id in self._pending_set or task_id in self._running:
            return False
        self._pending_set.add(task_id)
        await self._pending.put(task_id)
        return True

    async def process_one(self, timeout: float = 0.2) -> bool:
        """Run exactly one queued task. Returns True when work was done."""
        if len(self._running) >= self.max_concurrent:
            return False
        try:
            task_id = await asyncio.wait_for(self._pending.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        self._pending_set.discard(task_id)
        if task_id in self._running:
            return False
        self._running.add(task_id)
        try:
            from bozii.agent_runtime.runner import TaskRunner

            runner = TaskRunner(self.session_factory)
            await runner.run(task_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task %s raised while running", task_id)
            await self._mark_crashed(task_id)
        finally:
            self._running.discard(task_id)
        return True

    async def _mark_crashed(self, task_id: str) -> None:
        async with self.session_factory() as db:
            task = await db.get(Task, task_id)
            if task is not None and task.state not in TERMINAL:
                task.state = "failed"
                task.error = "The execution engine crashed while running this task; see server logs."
                task.finished_at = datetime.now(timezone.utc)
                await db.commit()

    # -------------------------------------------------------------- waiting
    async def wait_for(self, task_ids: Iterable[str], timeout: int = 300) -> dict[str, str]:
        """Wait until every task reaches a terminal state, pumping the queue meanwhile."""
        targets = [t for t in dict.fromkeys(task_ids) if t]
        if not targets:
            return {}
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max(1, timeout)
        self._wait_depth += 1
        try:
            while loop.time() < deadline:
                states = await self._states(targets)
                if all(state in TERMINAL for state in states.values()):
                    return states
                pumped = False
                if self._wait_depth <= 6:
                    pumped = await self.process_one(timeout=0.05)
                if not pumped:
                    await asyncio.sleep(0.15)
            return await self._states(targets)
        finally:
            self._wait_depth -= 1

    async def _states(self, task_ids: list[str]) -> dict[str, str]:
        async with self.session_factory() as db:
            await db.rollback()
            rows = (
                await db.execute(select(Task.id, Task.state).where(Task.id.in_(task_ids)))
            ).all()
        return {row.id: row.state for row in rows}

    async def pending_count(self) -> dict[str, int]:
        return {
            "queued": len(self._pending_set),
            "running": len(self._running),
            "workers": self.concurrency,
        }

    # -------------------------------------------------------------- recovery
    async def recover_interrupted(self) -> int:
        """Re-queue tasks that were alive when the process stopped."""
        settings = get_settings()
        if not settings.restart_interrupted_tasks:
            return 0
        recovered = 0
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(Task).where(Task.state.in_(["queued", "planning", "running", "waiting_approval", "recovering"]))
                )
            ).scalars().all()
            for task in rows:
                if task.attempt >= settings.max_task_attempts + 1:
                    task.state = "failed"
                    task.error = (
                        "Bozii restarted while this task was executing and it exceeded the "
                        "restart budget; use Retry to run it again."
                    )
                    task.finished_at = datetime.now(timezone.utc)
                    continue
                task.attempt += 1
                task.state = "queued"
                task.pending_tool = None
                task.approval_needed = False
                task.cancel_requested = False
                recovered += 1
                await db.commit()
                await self.enqueue(task.id)
            await db.commit()
        if recovered:
            logger.info("Recovered %d interrupted task(s)", recovered)
        return recovered


_queue: TaskQueue | None = None


def get_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        from bozii.db import get_session_factory

        _queue = TaskQueue(get_session_factory())
    return _queue


def set_queue(queue: TaskQueue | None) -> None:
    global _queue
    _queue = queue


__all__ = ["TaskQueue", "get_queue", "set_queue"]
