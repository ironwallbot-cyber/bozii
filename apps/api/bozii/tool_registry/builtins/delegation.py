"""Delegation tools: assign work to other employees and exchange messages."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from bozii.models import Employee, Task
from bozii.states import TOOL_RISK_CONSEQUENTIAL
from bozii.tool_registry.base import Tool, ToolContext, ToolResult


class DelegateTaskTool(Tool):
    name = "delegate_task"
    title = "Delegate task"
    description = (
        "Assign a subtask to another employee. The child task runs with the INTERSECTION of "
        "your permissions and the delegate's permissions, so delegation can never widen access. "
        "Set wait=true to block until the delegate reports back."
    )
    category = "collaboration"
    risk = TOOL_RISK_CONSEQUENTIAL
    required_permissions = {"delegation": True}
    parameters = {
        "type": "object",
        "properties": {
            "objective": {"type": "string", "description": "What the delegate must accomplish"},
            "employee_id": {"type": "string", "description": "Target employee id"},
            "employee_name": {"type": "string", "description": "Target employee name (if id is unknown)"},
            "title": {"type": "string", "description": "Short task title"},
            "wait": {"type": "boolean", "description": "Wait for completion and return the report (default true)"},
            "timeout_seconds": {"type": "integer", "description": "Max seconds to wait (default 300, max 1200)"},
        },
        "required": ["objective"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if ctx.delegate is None:
            return ToolResult(ok=False, error="Delegation is not available in this execution context.")
        target_id = args.get("employee_id")
        if not target_id and args.get("employee_name"):
            row = await ctx.session.execute(
                select(Employee).where(
                    Employee.user_id == ctx.user_id,
                    Employee.name.ilike(f"%{args['employee_name']}%"),
                )
            )
            target = row.scalars().first()
            if target is None:
                return ToolResult(ok=False, error=f"No employee named '{args['employee_name']}'")
            target_id = target.id
        if not target_id:
            row = await ctx.session.execute(
                select(Employee).where(Employee.user_id == ctx.user_id, Employee.status == "active")
            )
            candidates = [e for e in row.scalars().all() if e.id != ctx.employee_id]
            if not candidates:
                return ToolResult(ok=False, error="No other active employee to delegate to.")
            target_id = candidates[0].id
        if target_id == ctx.employee_id:
            return ToolResult(ok=False, error="An employee cannot delegate to itself.")

        result = await ctx.delegate(
            target_employee_id=target_id,
            objective=args["objective"],
            title=args.get("title") or "Delegated subtask",
            wait=bool(args.get("wait", True)),
            timeout_seconds=int(args.get("timeout_seconds") or 300),
        )
        if isinstance(result, ToolResult):
            return result
        return ToolResult(ok=True, output=result)


class GetTaskStatusTool(Tool):
    name = "get_task_status"
    title = "Check task status"
    description = "Inspect the current state, progress and report of any task you own, including delegated ones."
    category = "collaboration"
    required_permissions = {}
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "Task id"}},
        "required": ["task_id"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        task = await ctx.session.get(Task, args["task_id"])
        if task is None or task.user_id != ctx.user_id:
            return ToolResult(ok=False, error="Task not found")
        return ToolResult(
            ok=True,
            output={
                "id": task.id,
                "title": task.title,
                "state": task.state,
                "iterations_used": task.iterations_used,
                "error": task.error,
                "finished": task.finished_at.isoformat() if task.finished_at else None,
                "report": (task.report or "")[:4000],
                "plan": task.plan,
            },
        )


class SendMessageTool(Tool):
    name = "send_team_message"
    title = "Send message"
    description = "Send a message to another employee (or the whole team) for coordination."
    category = "collaboration"
    required_permissions = {"delegation": True}
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Message content"},
            "to_employee_id": {"type": "string", "description": "Recipient employee id (omit for team broadcast)"},
        },
        "required": ["content"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if ctx.send_message is None:
            return ToolResult(ok=False, error="Messaging is not available in this context.")
        message = await ctx.send_message(content=args["content"], to_employee_id=args.get("to_employee_id"))
        return ToolResult(
            ok=True,
            output={"message_id": getattr(message, "id", None), "delivered": True},
        )


TOOLS: list[Tool] = [DelegateTaskTool(), GetTaskStatusTool(), SendMessageTool()]
