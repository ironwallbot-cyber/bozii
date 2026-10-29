"""Task routes: create, inspect, control (pause/resume/cancel/retry/approve)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from bozii.api.deps import ApiError, CurrentUser, DbSession, not_found
from bozii.engine.queue import get_queue
from bozii.models import Approval, Artifact, Employee, SubTask, Task, TaskEvent, Team
from bozii.schemas import (
    ApprovalDecision,
    ApprovalOut,
    ArtifactOut,
    SubTaskOut,
    TaskActionOut,
    TaskCreate,
    TaskDetailOut,
    TaskEventOut,
    TaskOut,
)
from bozii.security.audit import audit
from bozii.states import (
    ACTIVE_STATES,
    ALL_STATES,
    CANCELLED,
    COMPLETED,
    FAILED,
    PAUSED,
    QUEUED,
    TERMINAL_STATES,
    WAITING_APPROVAL,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(payload: TaskCreate, user: CurrentUser, db: DbSession) -> TaskOut:
    employee = await db.get(Employee, payload.employee_id)
    if employee is None or employee.user_id != user.id:
        raise not_found("Employee")
    if employee.status != "active":
        raise ApiError(400, f"Employee '{employee.name}' is {employee.status}", code="employee_inactive")

    title = (payload.title or "").strip() or _title_from(payload.objective)
    task = Task(
        user_id=user.id,
        employee_id=employee.id,
        team_id=payload.team_id,
        title=title[:255],
        objective=payload.objective,
        state=QUEUED,
        priority=payload.priority,
        input={k: v for k, v in payload.input.items() if v is not None},
        effective_permissions=dict(employee.permissions or {}),
        max_iterations=payload.max_iterations or employee.max_iterations,
        timeout_seconds=payload.timeout_seconds or employee.timeout_seconds,
        attempt=1,
    )
    if payload.plan_enabled is not None:
        task.input["plan_enabled"] = payload.plan_enabled
    if payload.team_id:
        team_exists = await db.get(Team, payload.team_id)
        if team_exists is None or team_exists.user_id != user.id:
            raise not_found("Team")
    db.add(task)
    await db.flush()
    await audit(
        db, action="task.created", actor=f"user:{user.id}", user_id=user.id,
        resource_type="task", resource_id=task.id,
        detail={"employee_id": employee.id, "title": task.title},
    )
    await db.commit()
    await get_queue().enqueue(task.id)
    return TaskOut.model_validate(task)


def _title_from(objective: str) -> str:
    first_line = objective.strip().splitlines()[0] if objective.strip() else "Task"
    return first_line[:120]


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    user: CurrentUser,
    db: DbSession,
    state: str = Query(""),
    employee_id: str = Query(""),
    team_id: str = Query(""),
    q: str = Query(""),
    limit: int = Query(200, le=500),
) -> list[TaskOut]:
    stmt = select(Task).where(Task.user_id == user.id)
    if state:
        wanted = [s for s in state.split(",") if s in ALL_STATES]
        if wanted:
            stmt = stmt.where(Task.state.in_(wanted))
    if employee_id:
        stmt = stmt.where(Task.employee_id == employee_id)
    if team_id:
        stmt = stmt.where(Task.team_id == team_id)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(Task.title.ilike(pattern) | Task.objective.ilike(pattern))
    rows = (await db.execute(stmt.order_by(Task.created_at.desc()).limit(limit))).scalars()
    return [TaskOut.model_validate(t) for t in rows]


@router.get("/{task_id}", response_model=TaskDetailOut)
async def get_task(task_id: str, user: CurrentUser, db: DbSession) -> TaskDetailOut:
    task = await _get(db, user.id, task_id)
    employee = await db.get(Employee, task.employee_id)
    subtasks = (
        await db.execute(
            select(SubTask).where(SubTask.task_id == task.id).order_by(SubTask.order_index.asc())
        )
    ).scalars()
    events = (
        await db.execute(
            select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.seq.asc()).limit(1000)
        )
    ).scalars()
    approvals = (
        await db.execute(
            select(Approval).where(Approval.task_id == task.id).order_by(Approval.created_at.desc())
        )
    ).scalars()
    artifacts = (
        await db.execute(
            select(Artifact).where(Artifact.task_id == task.id).order_by(Artifact.created_at.desc())
        )
    ).scalars()
    detail = TaskDetailOut.model_validate(task)
    detail.subtasks = [SubTaskOut.model_validate(s) for s in subtasks]
    detail.events = [TaskEventOut.model_validate(e) for e in events]
    detail.approvals = [ApprovalOut.model_validate(a) for a in approvals]
    detail.artifacts = [ArtifactOut.model_validate(a) for a in artifacts]
    detail.employee_name = employee.name if employee else ""
    detail.messages = task.messages or []
    return detail


@router.post("/{task_id}/cancel", response_model=TaskActionOut)
async def cancel_task(task_id: str, user: CurrentUser, db: DbSession) -> TaskActionOut:
    task = await _get(db, user.id, task_id)
    if task.state in TERMINAL_STATES:
        raise ApiError(400, f"Task is already {task.state}", code="already_terminal")
    task.cancel_requested = True
    if task.state in (QUEUED, PAUSED, WAITING_APPROVAL):
        # Not actively running: cancel immediately.
        task.state = CANCELLED
        task.finished_at = datetime.now(timezone.utc)
        task.error = "Cancelled before completion"
        if task.pending_tool:
            approval = await db.get(Approval, task.pending_tool.get("approval_id") or "")
            if approval and approval.state == "pending":
                approval.state = "denied"
                approval.reason = "Task cancelled"
                approval.decided_at = datetime.now(timezone.utc)
        task.pending_tool = None
        task.approval_needed = False
    await audit(
        db, action="task.cancelled", actor=f"user:{user.id}", user_id=user.id,
        resource_type="task", resource_id=task.id,
    )
    await db.commit()
    return TaskActionOut(ok=True, state=task.state, detail="Cancellation requested")


@router.post("/{task_id}/pause", response_model=TaskActionOut)
async def pause_task(task_id: str, user: CurrentUser, db: DbSession) -> TaskActionOut:
    task = await _get(db, user.id, task_id)
    if task.state not in ACTIVE_STATES:
        raise ApiError(400, f"Only active tasks can be paused (state: {task.state})", code="invalid_state")
    if task.state in (QUEUED,):
        task.state = PAUSED
    else:
        task.paused = True
    await db.commit()
    return TaskActionOut(ok=True, state=task.state if task.state != QUEUED else PAUSED, detail="Pause requested")


@router.post("/{task_id}/resume", response_model=TaskActionOut)
async def resume_task(task_id: str, user: CurrentUser, db: DbSession) -> TaskActionOut:
    task = await _get(db, user.id, task_id)
    if task.state not in (PAUSED, QUEUED):
        raise ApiError(400, f"Only paused tasks can be resumed (state: {task.state})", code="invalid_state")
    task.paused = False
    task.cancel_requested = False
    task.state = QUEUED
    await db.commit()
    await get_queue().enqueue(task.id)
    return TaskActionOut(ok=True, state=QUEUED, detail="Task queued for execution")


@router.post("/{task_id}/retry", response_model=TaskActionOut)
async def retry_task(task_id: str, user: CurrentUser, db: DbSession) -> TaskActionOut:
    task = await _get(db, user.id, task_id)
    if task.state not in TERMINAL_STATES:
        raise ApiError(400, f"Only finished tasks can be retried (state: {task.state})", code="invalid_state")
    # Fresh attempt: clear the previous conversation and results, keep history in events.
    for subtask in (
        await db.execute(select(SubTask).where(SubTask.task_id == task.id))
    ).scalars():
        await db.delete(subtask)
    task.state = QUEUED
    task.paused = False
    task.cancel_requested = False
    task.attempt += 1
    task.plan = []
    task.messages = []
    task.report = ""
    task.result = {}
    task.error = None
    task.pending_tool = None
    task.approval_needed = False
    task.iterations_used = 0
    task.tool_calls = 0
    task.started_at = None
    task.finished_at = None
    await audit(
        db, action="task.retried", actor=f"user:{user.id}", user_id=user.id,
        resource_type="task", resource_id=task.id, detail={"attempt": task.attempt},
    )
    await db.commit()
    await get_queue().enqueue(task.id)
    return TaskActionOut(ok=True, state=QUEUED, detail=f"Retry attempt {task.attempt} queued")


@router.post("/{task_id}/approve", response_model=TaskActionOut)
async def decide_approval(
    task_id: str, payload: ApprovalDecision, user: CurrentUser, db: DbSession
) -> TaskActionOut:
    task = await _get(db, user.id, task_id)
    pending_id = (task.pending_tool or {}).get("approval_id")
    approval = await db.get(Approval, pending_id) if pending_id else None
    if approval is None:
        approval = (
            await db.execute(
                select(Approval)
                .where(Approval.task_id == task.id, Approval.state == "pending")
                .order_by(Approval.created_at.desc())
            )
        ).scalars().first()
    if approval is None or approval.state != "pending":
        raise ApiError(400, "There is no pending approval for this task", code="no_pending_approval")

    approval.state = "approved" if payload.approve else "denied"
    approval.reason = payload.reason or None
    approval.decided_at = datetime.now(timezone.utc)
    task.approval_needed = False
    task.paused = False
    task.state = QUEUED
    await audit(
        db,
        action="approval.approved" if payload.approve else "approval.denied",
        actor=f"user:{user.id}", user_id=user.id,
        resource_type="approval", resource_id=approval.id,
        detail={"task_id": task.id, "tool": (task.pending_tool or {}).get("tool")},
    )
    await db.commit()
    await get_queue().enqueue(task.id)
    return TaskActionOut(
        ok=True,
        state=QUEUED,
        detail="Approved; execution resumed" if payload.approve else "Denied; execution continues without the action",
    )


@router.get("/{task_id}/events", response_model=list[TaskEventOut])
async def task_events(task_id: str, user: CurrentUser, db: DbSession, since: int = Query(0)) -> list[TaskEventOut]:
    await _get(db, user.id, task_id)
    rows = (
        await db.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.seq > since)
            .order_by(TaskEvent.seq.asc())
            .limit(500)
        )
    ).scalars()
    return [TaskEventOut.model_validate(e) for e in rows]


@router.get("/{task_id}/children", response_model=list[TaskOut])
async def task_children(task_id: str, user: CurrentUser, db: DbSession) -> list[TaskOut]:
    await _get(db, user.id, task_id)
    rows = (
        await db.execute(
            select(Task).where(Task.parent_task_id == task_id).order_by(Task.created_at.asc())
        )
    ).scalars()
    return [TaskOut.model_validate(t) for t in rows]


async def _get(db, user_id: str, task_id: str) -> Task:
    task = await db.get(Task, task_id)
    if task is None or task.user_id != user_id:
        raise not_found("Task")
    return task


__all__ = ["router"]
