"""Server-sent events stream for live task updates."""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from bozii.agent_runtime.events import get_bus
from bozii.agent_runtime.events import get_bus
from bozii.api.deps import ApiError, DbSession, get_current_user
from bozii.models import Task, User

router = APIRouter(prefix="/api", tags=["stream"])

HEARTBEAT_SECONDS = 15.0


@router.get("/stream")
async def stream(
    request: Request,
    db: DbSession,
    channels: str = Query("activity", description="Comma separated: activity, task:<id>"),
):
    """SSE stream. Authentication uses the session cookie (same-origin EventSource)."""
    user: User = await get_current_user(request, db)
    requested = [c.strip() for c in channels.split(",") if c.strip()]
    allowed: list[str] = []
    for channel in requested:
        if channel == "activity":
            allowed.append(channel)
        elif channel.startswith("task:"):
            task_id = channel.split(":", 1)[1]
            task = await db.get(Task, task_id)
            if task is not None and task.user_id == user.id:
                allowed.append(channel)
    if not allowed:
        raise ApiError(403, "No valid channels requested", code="forbidden_channel")

    async def event_source() -> AsyncIterator[str]:
        bus = get_bus()
        async for event in bus.stream(allowed, heartbeat_seconds=HEARTBEAT_SECONDS):
            event_type = str(event.get("type", "message"))
            if event_type == "heartbeat":
                yield ": heartbeat\n\n"
                continue
            payload = {k: v for k, v in event.items() if k != "type"}
            yield f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
