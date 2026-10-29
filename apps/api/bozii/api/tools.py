"""Tool routes: browse builtin + capability tools and toggle them per user."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from bozii.api.deps import ApiError, CurrentUser, DbSession, not_found
from bozii.capability_engine.service import capability_tools_for_user
from bozii.models import ToolRegistration
from bozii.schemas import ToolOut, ToolToggle
from bozii.security.audit import audit
from bozii.tool_registry import get_registry

router = APIRouter(prefix="/api/tools", tags=["tools"])


async def _registrations(db, user_id: str) -> dict[str, ToolRegistration]:
    rows = (
        await db.execute(select(ToolRegistration).where(ToolRegistration.user_id == user_id))
    ).scalars().all()
    return {row.tool_name: row for row in rows}


async def _ensure_registrations(db, user_id: str, names: list[str]) -> dict[str, ToolRegistration]:
    existing = await _registrations(db, user_id)
    created = False
    for name in names:
        if name not in existing:
            row = ToolRegistration(user_id=user_id, tool_name=name, enabled=True)
            db.add(row)
            existing[name] = row
            created = True
    if created:
        await db.commit()
    return existing


@router.get("")
async def list_tools(user: CurrentUser, db: DbSession) -> list[ToolOut]:
    registry = get_registry()
    builtin = registry.describe()
    cap_tools = await capability_tools_for_user(db, user.id)
    registrations = await _ensure_registrations(db, user.id, [t["name"] for t in builtin])
    for tool in cap_tools:
        registrations.setdefault(tool.name, ToolRegistration(user_id=user.id, tool_name=tool.name, enabled=True))

    out: list[ToolOut] = []
    for item in builtin:
        out.append(
            ToolOut(
                **item,
                enabled=(registrations.get(item["name"]) or ToolRegistration(enabled=True)).enabled,
            )
        )
    for tool in cap_tools:
        described = tool.describe()
        out.append(
            ToolOut(
                name=tool.name,
                title=described["title"],
                description=tool.description,
                category=tool.category,
                kind="capability",
                risk=tool.risk,
                required_permissions=tool.required_permissions,
                parameters=tool.parameters,
                enabled=True,
                version=tool.version,
                capability_id=described.get("capability_id"),
            )
        )
    return out


@router.post("/{tool_name}/toggle", response_model=ToolOut)
async def toggle_tool(tool_name: str, payload: ToolToggle, user: CurrentUser, db: DbSession) -> ToolOut:
    registry = get_registry()
    tool = registry.get(tool_name)
    if tool is None:
        cap_tools = await capability_tools_for_user(db, user.id)
        cap = next((t for t in cap_tools if t.name == tool_name), None)
        if cap is None:
            raise not_found("Tool")
    row = (
        await db.execute(
            select(ToolRegistration).where(
                ToolRegistration.user_id == user.id, ToolRegistration.tool_name == tool_name
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ToolRegistration(user_id=user.id, tool_name=tool_name, enabled=payload.enabled)
        db.add(row)
    else:
        row.enabled = payload.enabled
    await audit(
        db, action="tool.toggled", actor=f"user:{user.id}", user_id=user.id,
        resource_type="tool", resource_id=tool_name, detail={"enabled": payload.enabled},
    )
    await db.commit()
    if tool is None:
        described = cap.describe()
        return ToolOut(
            name=tool_name,
            title=described["title"],
            description=cap.description,
            category=cap.category,
            kind="capability",
            risk=cap.risk,
            required_permissions=cap.required_permissions,
            parameters=cap.parameters,
            enabled=row.enabled,
            version=cap.version,
            capability_id=cap.capability.id,
        )
    return ToolOut(**tool.describe(), enabled=row.enabled)


@router.get("/{tool_name}/schema")
async def tool_schema(tool_name: str, user: CurrentUser, db: DbSession) -> dict:
    tool = get_registry().get(tool_name)
    if tool is not None:
        return tool.describe()
    cap_tools = await capability_tools_for_user(db, user.id)
    match = next((t for t in cap_tools if t.name == tool_name), None)
    if match is None:
        raise not_found("Tool")
    return match.describe()


__all__ = ["router"]
