"""Employee routes: CRUD, templates, memory, timeline."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from bozii.api.deps import ApiError, CurrentUser, DbSession, not_found
from bozii.models import (
    Artifact,
    Capability,
    Employee,
    EmployeeMemory,
    Task,
    TaskEvent,
)
from bozii.schemas import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    MemoryCreate,
    MemoryOut,
    TaskEventOut,
    TaskOut,
)
from bozii.security.audit import audit
from bozii.states import DEFAULT_PERMISSIONS, TERMINAL_STATES
from bozii.templates import list_templates, template_for

router = APIRouter(prefix="/api/employees", tags=["employees"])


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:100] or "employee"


async def _stats(db, user_id: str) -> dict[str, dict[str, int]]:
    rows = (
        await db.execute(
            select(Task.employee_id, Task.state, func.count(Task.id))
            .where(Task.user_id == user_id)
            .group_by(Task.employee_id, Task.state)
        )
    ).all()
    out: dict[str, dict[str, int]] = {}
    for employee_id, state, count in rows:
        bucket = out.setdefault(employee_id, {"active": 0, "completed": 0, "failed": 0})
        if state in {"queued", "planning", "running", "waiting_approval", "recovering"}:
            bucket["active"] += count
        elif state == "completed":
            bucket["completed"] += count
        elif state == "failed":
            bucket["failed"] += count
    return out


def _to_out(employee: Employee, stats: dict[str, int] | None = None) -> EmployeeOut:
    out = EmployeeOut.model_validate(employee)
    stats = stats or {}
    out.active_tasks = stats.get("active", 0)
    out.completed_tasks = stats.get("completed", 0)
    out.failed_tasks = stats.get("failed", 0)
    return out


@router.get("/templates")
async def templates(user: CurrentUser) -> list[dict[str, Any]]:
    return list_templates()


@router.get("")
async def list_employees(user: CurrentUser, db: DbSession, q: str = Query("")) -> list[EmployeeOut]:
    stmt = select(Employee).where(Employee.user_id == user.id)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(Employee.name.ilike(pattern) | Employee.role.ilike(pattern))
    rows = (await db.execute(stmt.order_by(Employee.created_at.asc()))).scalars()
    stats = await _stats(db, user.id)
    return [_to_out(e, stats.get(e.id)) for e in rows]


@router.post("", response_model=EmployeeOut, status_code=201)
async def create_employee(payload: EmployeeCreate, user: CurrentUser, db: DbSession) -> EmployeeOut:
    template = template_for(payload.template)
    name = payload.name.strip()
    role = payload.role or (template["role"] if template else "General Assistant")
    description = payload.description or (template["description"] if template else "")
    system_prompt = payload.system_prompt or (template["system_prompt"] if template else "")
    permissions = payload.permissions or (
        deepcopy_permissions(template["permissions"]) if template else dict(DEFAULT_PERMISSIONS)
    )
    slug = slugify(name)
    existing = (
        await db.execute(select(Employee).where(Employee.user_id == user.id, Employee.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    employee = Employee(
        user_id=user.id,
        name=name,
        slug=slug,
        role=role,
        description=description,
        system_prompt=system_prompt,
        template_key=payload.template,
        avatar_seed=uuid.uuid4().hex[:12],
        avatar_color=(template or {}).get("avatar_color", "#3f3f46"),
        model_id=payload.model_id,
        temperature=payload.temperature,
        permissions=permissions,
        memory_enabled=payload.memory_enabled,
        max_iterations=payload.max_iterations,
        timeout_seconds=payload.timeout_seconds,
    )
    db.add(employee)
    await db.flush()
    await audit(
        db, action="employee.created", actor=f"user:{user.id}", user_id=user.id,
        resource_type="employee", resource_id=employee.id, detail={"name": name, "template": payload.template},
    )
    await db.commit()
    return _to_out(employee)


def deepcopy_permissions(value: dict[str, Any]) -> dict[str, Any]:
    return {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in value.items()}


@router.get("/{employee_id}", response_model=EmployeeOut)
async def get_employee(employee_id: str, user: CurrentUser, db: DbSession) -> EmployeeOut:
    employee = await _get(db, user.id, employee_id)
    stats = await _stats(db, user.id)
    return _to_out(employee, stats.get(employee.id))


@router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: str, payload: EmployeeUpdate, user: CurrentUser, db: DbSession
) -> EmployeeOut:
    employee = await _get(db, user.id, employee_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        employee.name = data.pop("name").strip()
    for field in ("role", "description", "system_prompt", "status", "temperature"):
        if field in data and data[field] is not None:
            setattr(employee, field, data[field])
    if data.get("model_id"):
        employee.model_id = data["model_id"]
    if data.get("permissions") is not None:
        employee.permissions = data["permissions"]
    if data.get("tools_allowlist") is not None:
        employee.tools_allowlist = data["tools_allowlist"]
    if data.get("tools_denylist") is not None:
        employee.tools_denylist = data["tools_denylist"]
    if data.get("memory_enabled") is not None:
        employee.memory_enabled = data["memory_enabled"]
    if data.get("max_iterations") is not None:
        employee.max_iterations = data["max_iterations"]
    if data.get("timeout_seconds") is not None:
        employee.timeout_seconds = data["timeout_seconds"]
    await audit(
        db, action="employee.updated", actor=f"user:{user.id}", user_id=user.id,
        resource_type="employee", resource_id=employee.id, detail={"fields": sorted(data)},
    )
    await db.commit()
    stats = await _stats(db, user.id)
    return _to_out(employee, stats.get(employee.id))


@router.delete("/{employee_id}")
async def delete_employee(employee_id: str, user: CurrentUser, db: DbSession) -> dict:
    employee = await _get(db, user.id, employee_id)
    task_count = (
        await db.execute(select(func.count(Task.id)).where(Task.employee_id == employee.id))
    ).scalar() or 0
    if task_count:
        employee.status = "archived"
        await audit(
            db, action="employee.archived", actor=f"user:{user.id}", user_id=user.id,
            resource_type="employee", resource_id=employee.id, detail={"tasks": task_count},
        )
        await db.commit()
        return {"deleted": False, "status": "archived", "detail": f"Employee has {task_count} task(s) and was archived instead of deleted."}
    await db.delete(employee)
    await audit(
        db, action="employee.deleted", actor=f"user:{user.id}", user_id=user.id,
        resource_type="employee", resource_id=employee_id,
    )
    await db.commit()
    return {"deleted": True, "status": "deleted"}


@router.get("/{employee_id}/tasks", response_model=list[TaskOut])
async def employee_tasks(employee_id: str, user: CurrentUser, db: DbSession) -> list[TaskOut]:
    await _get(db, user.id, employee_id)
    rows = (
        await db.execute(
            select(Task)
            .where(Task.user_id == user.id, Task.employee_id == employee_id)
            .order_by(Task.created_at.desc())
            .limit(200)
        )
    ).scalars()
    return [TaskOut.model_validate(t) for t in rows]


@router.get("/{employee_id}/timeline", response_model=list[TaskEventOut])
async def employee_timeline(employee_id: str, user: CurrentUser, db: DbSession) -> list[TaskEventOut]:
    await _get(db, user.id, employee_id)
    rows = (
        await db.execute(
            select(TaskEvent)
            .join(Task, Task.id == TaskEvent.task_id)
            .where(Task.user_id == user.id, Task.employee_id == employee_id)
            .order_by(TaskEvent.created_at.desc())
            .limit(150)
        )
    ).scalars()
    return [TaskEventOut.model_validate(e) for e in rows]


# -------------------------------------------------------------------- memory
@router.get("/{employee_id}/memory", response_model=list[MemoryOut])
async def list_memory(employee_id: str, user: CurrentUser, db: DbSession) -> list[MemoryOut]:
    await _get(db, user.id, employee_id)
    rows = (
        await db.execute(
            select(EmployeeMemory)
            .where(EmployeeMemory.employee_id == employee_id)
            .order_by(EmployeeMemory.pinned.desc(), EmployeeMemory.updated_at.desc())
            .limit(300)
        )
    ).scalars()
    return [MemoryOut.model_validate(m) for m in rows]


@router.post("/{employee_id}/memory", response_model=MemoryOut, status_code=201)
async def add_memory(
    employee_id: str, payload: MemoryCreate, user: CurrentUser, db: DbSession
) -> MemoryOut:
    employee = await _get(db, user.id, employee_id)
    if not employee.memory_enabled:
        raise ApiError(400, "Memory is disabled for this employee", code="memory_disabled")
    lowered = (payload.key + " " + payload.content).lower()
    for token in ("password", "secret", "api key", "api_key", "bearer "):
        if token in lowered:
            raise ApiError(400, "Refusing to store anything that looks like a credential", code="unsafe_memory")
    memory = EmployeeMemory(
        employee_id=employee.id,
        kind=payload.kind,
        key=payload.key[:160],
        content=payload.content,
        pinned=payload.pinned,
    )
    db.add(memory)
    await db.flush()
    await audit(
        db, action="memory.created", actor=f"user:{user.id}", user_id=user.id,
        resource_type="memory", resource_id=memory.id, detail={"key": memory.key},
    )
    await db.commit()
    return MemoryOut.model_validate(memory)


@router.delete("/{employee_id}/memory/{memory_id}")
async def delete_memory(employee_id: str, memory_id: str, user: CurrentUser, db: DbSession) -> dict:
    await _get(db, user.id, employee_id)
    memory = await db.get(EmployeeMemory, memory_id)
    if memory is None or memory.employee_id != employee_id:
        raise not_found("Memory entry")
    await db.delete(memory)
    await audit(
        db, action="memory.deleted", actor=f"user:{user.id}", user_id=user.id,
        resource_type="memory", resource_id=memory_id,
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/{employee_id}/memory")
async def clear_memory(employee_id: str, user: CurrentUser, db: DbSession) -> dict:
    await _get(db, user.id, employee_id)
    rows = (
        await db.execute(select(EmployeeMemory).where(EmployeeMemory.employee_id == employee_id))
    ).scalars().all()
    for row in rows:
        await db.delete(row)
    await audit(
        db, action="memory.cleared", actor=f"user:{user.id}", user_id=user.id,
        resource_type="memory", resource_id=employee_id, detail={"count": len(rows)},
    )
    await db.commit()
    return {"deleted": len(rows)}


# ------------------------------------------------------------ capabilities
@router.get("/{employee_id}/capabilities")
async def employee_capabilities(employee_id: str, user: CurrentUser, db: DbSession) -> list[dict]:
    await _get(db, user.id, employee_id)
    rows = (
        await db.execute(
            select(Capability)
            .where(Capability.created_by_employee_id == employee_id)
            .order_by(Capability.created_at.desc())
            .limit(100)
        )
    ).scalars()
    return [
        {
            "id": c.id,
            "slug": c.slug,
            "name": c.name,
            "kind": c.kind,
            "version": c.version,
            "status": c.status,
            "description": c.description,
            "created_at": c.created_at.isoformat(),
            "tests_passed": bool((c.test_results or {}).get("passed")),
        }
        for c in rows
    ]


async def _get(db, user_id: str, employee_id: str) -> Employee:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.user_id != user_id:
        raise not_found("Employee")
    return employee


__all__ = ["router"]
