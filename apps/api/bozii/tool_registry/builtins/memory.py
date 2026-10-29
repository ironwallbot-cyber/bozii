"""Memory and plan-progress tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from bozii.models import Employee, EmployeeMemory, SubTask
from bozii.states import TOOL_RISK_MUTATING
from bozii.tool_registry.base import Tool, ToolContext, ToolResult

ALLOWED_KINDS = {"fact", "preference", "summary", "skill"}


class SaveMemoryTool(Tool):
    name = "save_memory"
    title = "Save to memory"
    description = (
        "Persist a durable fact, preference or reusable note about how you work. "
        "Only save information worth retaining between sessions; never store secrets."
    )
    category = "memory"
    risk = TOOL_RISK_MUTATING
    required_permissions = {}
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Short label, e.g. 'preferred report format'"},
            "content": {"type": "string", "description": "The fact or preference to remember"},
            "kind": {"type": "string", "enum": sorted(ALLOWED_KINDS), "description": "Default 'fact'"},
            "pinned": {"type": "boolean", "description": "Always surface this memory (default false)"},
        },
        "required": ["key", "content"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        employee = await ctx.session.get(Employee, ctx.employee_id)
        if employee is not None and not employee.memory_enabled:
            return ToolResult(ok=False, error="Memory is disabled for this employee.")
        lowered = (args["key"] + " " + args["content"]).lower()
        for token in ("password", "secret", "api key", "api_key", "token=", "bearer "):
            if token in lowered:
                return ToolResult(
                    ok=False,
                    error="Refusing to store anything that looks like a credential.",
                )
        row = await ctx.session.execute(
            select(EmployeeMemory).where(
                EmployeeMemory.employee_id == ctx.employee_id,
                EmployeeMemory.key == args["key"],
            )
        )
        existing = row.scalar_one_or_none()
        if existing:
            existing.content = args["content"]
            existing.kind = args.get("kind") or existing.kind
            existing.pinned = bool(args.get("pinned", existing.pinned))
            memory = existing
        else:
            memory = EmployeeMemory(
                employee_id=ctx.employee_id,
                kind=args.get("kind") or "fact",
                key=args["key"][:160],
                content=args["content"],
                pinned=bool(args.get("pinned", False)),
            )
            ctx.session.add(memory)
        await ctx.session.flush()
        return ToolResult(ok=True, output={"memory_id": memory.id, "key": memory.key, "stored": True})


class UpdatePlanTool(Tool):
    name = "update_plan"
    title="Update plan progress"
    description=(
        "Report the real status of a plan step you just worked on: pending, running, done or "
        "failed, with an evidence note describing what you actually observed."
    )
    category = "collaboration"
    required_permissions = {}
    parameters = {
        "type": "object",
        "properties": {
            "step_index": {"type": "integer", "description": "0-based index of the plan step"},
            "status": {"type": "string", "enum": ["pending", "running", "done", "failed"]},
            "note": {"type": "string", "description": "Evidence: what you ran and what happened"},
        },
        "required": ["step_index", "status"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        index = int(args["step_index"])
        row = await ctx.session.execute(
            select(SubTask).where(SubTask.task_id == ctx.task_id).order_by(SubTask.order_index.asc())
        )
        subtasks = list(row.scalars())
        if not subtasks:
            return ToolResult(ok=False, error="This task has no plan to update.")
        if index < 0 or index >= len(subtasks):
            return ToolResult(ok=False, error=f"step_index out of range (0..{len(subtasks) - 1})")
        subtask = subtasks[index]
        subtask.status = args["status"]
        if args.get("note"):
            subtask.output = str(args["note"])[:4000]
        await ctx.session.flush()
        return ToolResult(
            ok=True,
            output={"step_index": index, "title": subtask.title, "status": args["status"]},
        )


TOOLS: list[Tool] = [SaveMemoryTool(), UpdatePlanTool()]
