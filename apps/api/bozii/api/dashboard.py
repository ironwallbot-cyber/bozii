"""Dashboard and activity feeds - every number comes from real rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from bozii.api.deps import CurrentUser, DbSession
from bozii.models import (
    Artifact,
    AuditEvent,
    Capability,
    Employee,
    Provider,
    Task,
    TaskEvent,
    UsageRecord,
)
from bozii.schemas import ActivityOut, DashboardStats
from bozii.states import ALL_STATES, ACTIVE_STATES, CANCELLED, COMPLETED, FAILED

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(user: CurrentUser, db: DbSession) -> DashboardStats:
    def count_model(model, *where):
        stmt = select(func.count(model.id)).where(model.user_id == user.id if hasattr(model, "user_id") else True)
        if where:
            stmt = stmt.where(*where)
        return stmt

    employees = (
        await db.execute(select(func.count(Employee.id)).where(Employee.user_id == user.id))
    ).scalar() or 0

    state_rows = (
        await db.execute(
            select(Task.state, func.count(Task.id)).where(Task.user_id == user.id).group_by(Task.state)
        )
    ).all()
    by_state = {row[0]: row[1] for row in state_rows}

    artifacts = (
        await db.execute(select(func.count(Artifact.id)).where(Artifact.user_id == user.id))
    ).scalar() or 0

    capabilities_total = (
        await db.execute(
            select(func.count(Capability.id)).where(
                (Capability.created_by_user_id == user.id) | (Capability.visibility == "public")
            )
        )
    ).scalar() or 0
    capabilities_public = (
        await db.execute(
            select(func.count(Capability.id)).where(Capability.visibility == "public")
        )
    ).scalar() or 0

    tools_count = 0
    from bozii.tool_registry import get_registry

    tools_count = len(get_registry().names())

    provider_rows = (
        await db.execute(select(Provider.last_health_ok).where(Provider.user_id == user.id))
    ).scalars().all()
    providers_ok = sum(1 for row in provider_rows if row is True)

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    tasks_last_7d = (
        await db.execute(
            select(func.count(Task.id)).where(Task.user_id == user.id, Task.created_at >= week_ago)
        )
    ).scalar() or 0

    tokens = (
        await db.execute(
            select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
                UsageRecord.user_id == user.id
            )
        )
    ).scalar() or 0

    return DashboardStats(
        employees=employees,
        active_tasks=sum(by_state.get(s, 0) for s in ACTIVE_STATES),
        queued_tasks=by_state.get("queued", 0),
        completed_tasks=by_state.get(COMPLETED, 0),
        failed_tasks=by_state.get(FAILED, 0),
        cancelled_tasks=by_state.get(CANCELLED, 0),
        waiting_approval=by_state.get("waiting_approval", 0),
        artifacts=artifacts,
        capabilities=capabilities_total,
        public_capabilities=capabilities_public,
        tools=tools_count,
        providers_ok=providers_ok,
        providers_total=len(provider_rows),
        tokens_used=int(tokens),
        tasks_last_7d=tasks_last_7d,
    )


@router.get("/activity", response_model=list[ActivityOut])
async def activity(
    user: CurrentUser, db: DbSession, limit: int = Query(80, le=300), task_id: str = Query("")
) -> list[ActivityOut]:
    audit_rows = (
        await db.execute(
            select(AuditEvent)
            .where(AuditEvent.user_id == user.id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    events_stmt = (
        select(TaskEvent)
        .join(Task, Task.id == TaskEvent.task_id)
        .where(Task.user_id == user.id)
        .order_by(TaskEvent.created_at.desc())
        .limit(limit)
    )
    if task_id:
        events_stmt = events_stmt.where(TaskEvent.task_id == task_id)
    event_rows = (await db.execute(events_stmt)).scalars()

    out: list[ActivityOut] = []
    for row in audit_rows:
        out.append(
            ActivityOut(
                id=row.id,
                source="audit",
                actor=row.actor,
                action=row.action,
                message=_audit_message(row.action, row.detail),
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                detail=row.detail or {},
                created_at=row.created_at,
            )
        )
    for row in event_rows:
        out.append(
            ActivityOut(
                id=row.id,
                source="task_event",
                actor=f"task:{row.task_id[:8]}",
                action=row.type,
                message=row.message,
                resource_type="task",
                resource_id=row.task_id,
                detail=row.payload or {},
                created_at=row.created_at,
            )
        )
    out.sort(key=lambda item: item.created_at, reverse=True)
    return out[:limit]


def _audit_message(action: str, detail: dict) -> str:
    labels = {
        "task.created": "Task created",
        "task.completed": "Task completed",
        "task.failed": "Task failed",
        "task.cancelled": "Task cancelled",
        "task.retried": "Task retried",
        "employee.created": "Employee created",
        "employee.updated": "Employee updated",
        "employee.deleted": "Employee deleted",
        "employee.archived": "Employee archived",
        "memory.created": "Memory stored",
        "memory.deleted": "Memory deleted",
        "capability.created": "Capability created",
        "capability.imported": "Capability imported",
        "capability.activated": "Capability activated",
        "capability.disabled": "Capability disabled",
        "capability.published": "Capability published",
        "capability.installed": "Capability installed",
        "capability.deleted": "Capability deleted",
        "approval.approved": "Approval granted",
        "approval.denied": "Approval denied",
        "auth.login": "Signed in",
        "provider.created": "Model provider added",
        "provider.checked": "Provider health check",
        "settings.updated": "Settings updated",
    }
    label = labels.get(action, action.replace(".", " "))
    name = (detail or {}).get("name") or (detail or {}).get("slug") or ""
    return f"{label}{f': {name}' if name else ''}"


__all__ = ["router"]
