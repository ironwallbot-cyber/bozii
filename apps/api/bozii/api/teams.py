"""Team routes: teams, membership, messages and team task assignment."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from bozii.api.deps import ApiError, CurrentUser, DbSession, not_found
from bozii.engine.queue import get_queue
from bozii.models import Employee, Task, Team, TeamMember, TeamMessage
from bozii.schemas import (
    TeamCreate,
    TeamMemberOut,
    TeamMessageIn,
    TeamMessageOut,
    TeamOut,
    TeamUpdate,
)
from bozii.security.audit import audit
from bozii.states import QUEUED

router = APIRouter(prefix="/api/teams", tags=["teams"])


class MemberIn(BaseModel):
    employee_id: str
    role: str = Field(default="member", max_length=80)


class AssignIn(BaseModel):
    objective: str = Field(min_length=1)
    employee_id: str | None = None
    title: str = ""


def _members_stmt(team_id: str):
    return select(TeamMember).where(TeamMember.team_id == team_id).order_by(TeamMember.created_at.asc())


async def _members_for(db, team_id: str) -> list[TeamMemberOut]:
    members = (await db.execute(_members_stmt(team_id))).scalars().all()
    out: list[TeamMemberOut] = []
    for member in members:
        item = TeamMemberOut.model_validate(member)
        employee = await db.get(Employee, member.employee_id)
        item.employee_name = employee.name if employee else "(removed)"
        out.append(item)
    return out


async def _team_out(db, team: Team) -> TeamOut:
    out = TeamOut.model_validate(team)
    out.members = await _members_for(db, team.id)
    out.task_count = (
        await db.execute(select(func.count(Task.id)).where(Task.team_id == team.id))
    ).scalar() or 0
    return out


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(payload: TeamCreate, user: CurrentUser, db: DbSession) -> TeamOut:
    team = Team(
        user_id=user.id,
        name=payload.name.strip(),
        description=payload.description,
        objective=payload.objective,
        lead_employee_id=payload.lead_employee_id,
    )
    db.add(team)
    await db.flush()
    for employee_id in payload.member_ids:
        employee = await db.get(Employee, employee_id)
        if employee is None or employee.user_id != user.id:
            raise not_found("Employee")
        role = "lead" if employee_id == payload.lead_employee_id else "member"
        db.add(TeamMember(team_id=team.id, employee_id=employee_id, role=role))
    await audit(
        db, action="team.created", actor=f"user:{user.id}", user_id=user.id,
        resource_type="team", resource_id=team.id, detail={"name": team.name},
    )
    await db.commit()
    return await _team_out(db, team)


@router.get("", response_model=list[TeamOut])
async def list_teams(user: CurrentUser, db: DbSession) -> list[TeamOut]:
    rows = (await db.execute(select(Team).where(Team.user_id == user.id).order_by(Team.created_at.asc()))).scalars()
    return [await _team_out(db, t) for t in rows]


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(team_id: str, user: CurrentUser, db: DbSession) -> TeamOut:
    return await _team_out(db, await _get(db, user.id, team_id))


@router.patch("/{team_id}", response_model=TeamOut)
async def update_team(team_id: str, payload: TeamUpdate, user: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get(db, user.id, team_id)
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "description", "objective", "lead_employee_id"):
        if data.get(field) is not None:
            setattr(team, field, data[field])
    await db.commit()
    return await _team_out(db, team)


@router.delete("/{team_id}")
async def delete_team(team_id: str, user: CurrentUser, db: DbSession) -> dict:
    team = await _get(db, user.id, team_id)
    for member in (await db.execute(_members_stmt(team.id))).scalars().all():
        await db.delete(member)
    for message in (
        await db.execute(select(TeamMessage).where(TeamMessage.team_id == team.id))
    ).scalars().all():
        await db.delete(message)
    await db.delete(team)
    await audit(
        db, action="team.deleted", actor=f"user:{user.id}", user_id=user.id,
        resource_type="team", resource_id=team_id,
    )
    await db.commit()
    return {"deleted": True}


@router.post("/{team_id}/members", response_model=TeamOut, status_code=201)
async def add_member(team_id: str, payload: MemberIn, user: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get(db, user.id, team_id)
    employee = await db.get(Employee, payload.employee_id)
    if employee is None or employee.user_id != user.id:
        raise not_found("Employee")
    existing = (
        await db.execute(
            select(TeamMember).where(
                TeamMember.team_id == team.id, TeamMember.employee_id == employee.id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(TeamMember(team_id=team.id, employee_id=employee.id, role=payload.role))
        await db.flush()
    await db.commit()
    return await _team_out(db, team)


@router.delete("/{team_id}/members/{employee_id}", response_model=TeamOut)
async def remove_member(team_id: str, employee_id: str, user: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get(db, user.id, team_id)
    member = (
        await db.execute(
            select(TeamMember).where(
                TeamMember.team_id == team.id, TeamMember.employee_id == employee_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise not_found("Team member")
    await db.delete(member)
    if team.lead_employee_id == employee_id:
        team.lead_employee_id = None
    await db.commit()
    return await _team_out(db, team)


@router.get("/{team_id}/messages", response_model=list[TeamMessageOut])
async def list_messages(
    team_id: str, user: CurrentUser, db: DbSession, limit: int = Query(200, le=500)
) -> list[TeamMessageOut]:
    await _get(db, user.id, team_id)
    rows = (
        await db.execute(
            select(TeamMessage)
            .where(TeamMessage.team_id == team_id)
            .order_by(TeamMessage.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [TeamMessageOut.model_validate(m) for m in reversed(list(rows))]


@router.post("/{team_id}/messages", response_model=TeamMessageOut, status_code=201)
async def post_message(team_id: str, payload: TeamMessageIn, user: CurrentUser, db: DbSession) -> TeamMessageOut:
    await _get(db, user.id, team_id)
    message = TeamMessage(
        team_id=team_id,
        content=payload.content,
        to_employee_id=payload.to_employee_id,
        task_id=payload.task_id,
        kind="message",
    )
    db.add(message)
    await db.commit()
    return TeamMessageOut.model_validate(message)


@router.post("/{team_id}/tasks", status_code=201)
async def assign_team_task(team_id: str, payload: AssignIn, user: CurrentUser, db: DbSession) -> dict:
    """Assign an objective to a team: creates a task for the lead (or a named member)."""
    team = await _get(db, user.id, team_id)
    employee_id = payload.employee_id or team.lead_employee_id
    if not employee_id:
        members = (await db.execute(_members_stmt(team.id))).scalars().all()
        employee_id = members[0].employee_id if members else None
    if not employee_id:
        raise ApiError(400, "This team has no members to assign work to", code="no_members")
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.user_id != user.id:
        raise not_found("Employee")
    title = payload.title.strip() or payload.objective.splitlines()[0][:120]
    task = Task(
        user_id=user.id,
        employee_id=employee.id,
        team_id=team.id,
        title=title[:255],
        objective=payload.objective,
        state=QUEUED,
        input={"team_objective": team.objective} if team.objective else {},
        effective_permissions=dict(employee.permissions or {}),
        max_iterations=employee.max_iterations,
        timeout_seconds=employee.timeout_seconds,
    )
    db.add(task)
    await db.flush()
    await audit(
        db, action="team.task_assigned", actor=f"user:{user.id}", user_id=user.id,
        resource_type="task", resource_id=task.id, detail={"team_id": team.id},
    )
    await db.commit()
    await get_queue().enqueue(task.id)
    return {"task_id": task.id, "employee_id": employee.id, "state": task.state}


async def _get(db, user_id: str, team_id: str) -> Team:
    team = await db.get(Team, team_id)
    if team is None or team.user_id != user_id:
        raise not_found("Team")
    return team


__all__ = ["router"]
