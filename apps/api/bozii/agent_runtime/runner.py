"""The autonomous task execution engine.

One :class:`TaskRunner` drives a task through its real lifecycle:

    queued -> planning -> running -> (waiting_approval | recovering) ->
    completed | failed | cancelled

Every transition, tool call and error is persisted as a task event and
broadcast live. The loop is bounded by iteration limits, a wall-clock deadline,
per-tool timeouts and a cancellation flag; nothing runs forever.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bozii.agent_runtime.events import EventBus, get_bus, record_event
from bozii.agent_runtime.prompts import (
    REPORT_NUDGE,
    TOOL_FAILURE_HINT,
    build_planning_prompt,
    build_system_prompt,
    build_task_user_message,
)
from bozii.capability_engine.service import capability_tools_for_user, make_capability_builder
from bozii.config import Settings, get_settings
from bozii.model_adapters.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelError,
    ModelUnavailableError,
    ToolSpec,
)
from bozii.model_adapters.router import select_model
from bozii.models import (
    Approval,
    Artifact,
    Employee,
    EmployeeMemory,
    SubTask,
    Task,
    UsageRecord,
    new_id,
)
from bozii.security.audit import audit
from bozii.security.permissions import PermissionDenied, intersect_permissions, requires_approval
from bozii.states import (
    ALLOWED_TRANSITIONS,
    CANCELLED,
    COMPLETED,
    EMPLOYEE_ACTIVE,
    FAILED,
    PAUSED,
    PLANNING,
    QUEUED,
    RECOVERING,
    RUNNING,
    TERMINAL_STATES,
    WAITING_APPROVAL,
)
from bozii.tool_registry import ToolContext, ToolRegistry, ToolResult, get_registry

logger = logging.getLogger("bozii.engine")

MAX_TOOL_PREVIEW = 1500
MAX_MESSAGE_CHARS = 20000


def workspace_for(user_id: str, employee_id: str) -> Path:
    settings = get_settings()
    path = settings.workspace_dir / user_id / employee_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:60] or "report"


class TaskRunner:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], bus: EventBus | None = None):
        self.session_factory = session_factory
        self.bus = bus or get_bus()
        self.settings: Settings = get_settings()

    # ------------------------------------------------------------------ api
    async def run(self, task_id: str) -> None:
        async with self.session_factory() as db:
            task = await db.get(Task, task_id)
            if task is None:
                logger.warning("Task %s not found", task_id)
                return
            if task.state in TERMINAL_STATES:
                return
            employee = await db.get(Employee, task.employee_id)
            if employee is None:
                await self._fail(db, task, "The assigned employee no longer exists.")
                await db.commit()
                return
            if employee.status != EMPLOYEE_ACTIVE and task.state == QUEUED:
                await self._fail(
                    db, task, f"Employee '{employee.name}' is {employee.status}; task was not started."
                )
                await db.commit()
                return
            if task.state in (CANCELLED,):
                return
            try:
                await self._execute(db, task, employee)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Task %s crashed", task_id)
                await self._fail(db, task, f"Internal engine error: {exc}")
                await db.commit()

    # ------------------------------------------------------------ execution
    async def _execute(self, db: AsyncSession, task: Task, employee: Employee) -> None:
        settings = self.settings
        effective = dict(task.effective_permissions or employee.permissions or {})
        workspace = workspace_for(task.user_id, employee.id)

        # --- model selection (fails honestly when nothing is configured) --
        try:
            selection = await select_model(db, task.user_id, employee, require_tools=True)
        except ModelUnavailableError as exc:
            await self._fail(db, task, str(exc))
            await db.commit()
            return

        # --- tools ---------------------------------------------------------
        registry = get_registry()
        tools = registry.for_employee(employee, effective)
        allow = set(employee.tools_allowlist or [])
        deny = set(employee.tools_denylist or [])
        for cap_tool in await capability_tools_for_user(db, task.user_id):
            if cap_tool.name in deny:
                continue
            if allow and cap_tool.name not in allow:
                continue
            try:
                from bozii.security.permissions import check_permission

                check_permission(effective, cap_tool.required_permissions, cap_tool.name)
            except PermissionDenied:
                continue
            tools.append(cap_tool)
        tool_map = {t.name: t for t in tools}

        # --- conversation ---------------------------------------------------
        memories = list(
            (
                await db.execute(
                    select(EmployeeMemory)
                    .where(EmployeeMemory.employee_id == employee.id)
                    .order_by(EmployeeMemory.pinned.desc(), EmployeeMemory.updated_at.desc())
                    .limit(12)
                )
            ).scalars()
        )
        messages = [ChatMessage.from_dict(m) for m in (task.messages or [])]
        if not messages:
            skills = [
                {"name": c.name, "description": c.description}
                for c in (await capability_tools_for_user(db, task.user_id))
                if c.capability.kind == "skill"
            ]
            messages = [
                ChatMessage(
                    role="system",
                    content=build_system_prompt(employee, task, effective, memories, skills),
                ),
                ChatMessage(role="user", content=build_task_user_message(task)),
            ]
            task.messages = [m.as_dict() for m in messages]
            await db.flush()

        # --- persistent context for tools ----------------------------------
        ctx = ToolContext(
            user_id=task.user_id,
            employee_id=employee.id,
            employee_name=employee.name,
            workspace=workspace,
            session=db,
            permissions=effective,
            task_id=task.id,
            team_id=task.team_id,
            delegation_depth=task.delegation_depth,
            add_artifact=lambda path, kind, name=None: self._add_artifact(
                db, task, employee, workspace, Path(path), kind or "file", name
            ),
            emit=lambda type_, message, payload=None: self._emit(db, task, type_, message, payload),
            delegate=lambda **kw: self._delegate(db, task, employee, effective, **kw),
            send_message=lambda **kw: self._send_message(db, task, employee, **kw),
            memory=memories,
        )

        async def capability_store(**kwargs):
            builder = await make_capability_builder(
                db,
                user_id=task.user_id,
                employee=employee,
                task=task,
                adapter=selection.adapter,
                model_name=selection.model_name,
                emit=lambda type_, message, payload=None: self._emit(db, task, type_, message, payload),
            )
            return await builder(**kwargs)

        ctx.capability_store = capability_store

        # --- resume an approved/denied action ------------------------------
        if task.pending_tool:
            await self._resume_pending(db, task, employee, ctx, registry, tool_map, messages)

        # --- planning -------------------------------------------------------
        use_plan = task.input.get("plan_enabled")
        if use_plan is None:
            use_plan = settings.task_planning
        if use_plan and not task.plan and task.state not in TERMINAL_STATES:
            await self._plan(db, task, employee, selection, messages)

        if task.state in TERMINAL_STATES:
            await db.commit()
            return

        if task.state != RUNNING:
            await self._set_state(db, task, RUNNING, "Task started executing")

        await self._loop(db, task, employee, ctx, registry, selection, tools, tool_map, messages)

    # ------------------------------------------------------------- the loop
    async def _loop(self, db, task, employee, ctx, registry, selection, tools, tool_map, messages) -> None:
        settings = self.settings
        deadline = datetime.now(timezone.utc) + timedelta(seconds=task.timeout_seconds)
        model_failures = 0
        tool_failure_streak = 0
        idle_nudges = 0

        while True:
            # refresh externally mutable columns (cancel, approval, state)
            await db.refresh(task, ["cancel_requested", "state", "pending_tool", "approval_needed"])
            if task.cancel_requested:
                await self._set_state(db, task, CANCELLED, "Cancelled by user", force=True)
                await db.commit()
                return
            if task.paused:
                await self._set_state(db, task, PAUSED, "Paused by user")
                await db.commit()
                return
            if datetime.now(timezone.utc) > deadline:
                await self._fail(
                    db, task,
                    f"Time budget exhausted ({task.timeout_seconds}s). Partial results are preserved.",
                )
                await db.commit()
                return
            if task.iterations_used >= task.max_iterations:
                await self._fail(
                    db, task,
                    f"Iteration limit reached ({task.max_iterations}). "
                    "Raise max_iterations on the employee if the task legitimately needs more.",
                )
                await db.commit()
                return
            if task.pending_tool:
                await self._resume_pending(db, task, employee, ctx, registry, tool_map, messages)
                if task.state in TERMINAL_STATES:
                    await db.commit()
                    return

            # ---- model call -------------------------------------------------
            request = ChatRequest(
                model=selection.model_name,
                messages=messages,
                tools=[t.spec() for t in tools],
                temperature=employee.temperature,
                max_tokens=employee.max_tokens,
            )
            started = time.monotonic()
            try:
                response: ChatResponse = await asyncio.wait_for(
                    selection.adapter.chat(request), timeout=settings.model_timeout_seconds
                )
            except (ModelError, asyncio.TimeoutError) as exc:
                model_failures += 1
                latency = int((time.monotonic() - started) * 1000)
                await self._record_usage(db, task, selection, ok=False, error=str(exc), latency_ms=latency)
                await db.commit()
                if model_failures == 1:
                    await self._emit(db, task, "error", f"Model call failed, retrying once: {exc}", {"retry": 1})
                    await asyncio.sleep(1.0)
                    continue
                await self._fail(db, task, f"Model unavailable: {exc}")
                await db.commit()
                return
            model_failures = 0
            latency = int((time.monotonic() - started) * 1000)
            await self._record_usage(db, task, selection, ok=True, latency_ms=latency, usage=response.usage)
            task.iterations_used += 1

            # ---- tool calls --------------------------------------------------
            if response.tool_calls:
                tool_failure_streak, handled = await self._handle_tool_calls(
                    db, task, employee, ctx, registry, tools, tool_map, messages, response
                )
                if handled == "waiting":
                    await db.commit()
                    return
                if tool_failure_streak >= 5:
                    await self._fail(
                        db, task,
                        f"Aborted after {tool_failure_streak} consecutive tool failures; "
                        "the last error is preserved in the event log.",
                    )
                    await db.commit()
                    return
                if tool_failure_streak >= 3 and task.state == RUNNING:
                    await self._set_state(db, task, RECOVERING, "Repeated tool failures; recovering")
                idle_nudges = 0
                await db.commit()
                continue

            # ---- final answer -------------------------------------------------
            content = (response.content or "").strip()
            if not content:
                idle_nudges += 1
                if idle_nudges > 3:
                    await self._fail(db, task, "The model returned neither a tool call nor a report.")
                    await db.commit()
                    return
                messages.append(ChatMessage(role="user", content=REPORT_NUDGE))
                task.messages = [m.as_dict() for m in messages]
                await db.flush()
                continue

            messages.append(ChatMessage(role="assistant", content=content))
            task.messages = [m.as_dict() for m in messages]
            await self._complete(db, task, employee, ctx, content)
            await db.commit()
            return

    # ------------------------------------------------------------ tool calls
    async def _handle_tool_calls(
        self, db, task, employee, ctx, registry, tools, tool_map, messages, response: ChatResponse
    ) -> tuple[int, str]:
        from bozii.security.permissions import check_permission

        effective_perms = dict(task.effective_permissions or employee.permissions or {})
        ctx.permissions = effective_perms
        messages.append(
            ChatMessage(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            )
        )
        failure_streak = 0
        outcome = "ran"

        for call in response.tool_calls:
            tool = tool_map.get(call.name)
            args = call.arguments if isinstance(call.arguments, dict) else {}

            if tool is None:
                result = ToolResult(
                    ok=False,
                    error=f"Unknown tool '{call.name}'. Available: {', '.join(sorted(tool_map))}",
                )
            else:
                denied: PermissionDenied | None = None
                try:
                    check_permission(effective_perms, tool.required_permissions, tool.name)
                except PermissionDenied as exc:
                    denied = exc
                if denied is not None:
                    result = ToolResult(ok=False, error=f"Permission denied: {denied}")
                elif requires_approval(tool, effective_perms):
                    await self._request_approval(db, task, employee, call, tool)
                    task.messages = [m.as_dict() for m in messages]
                    await db.flush()
                    return (failure_streak, "waiting")
                else:
                    result = await self._run_tool(db, task, ctx, registry, tools, tool, args)

            messages.append(
                ChatMessage(
                    role="tool",
                    content=result.as_message()[:MAX_MESSAGE_CHARS],
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
            task.tool_calls += 1
            if result.ok:
                if failure_streak >= 3 and task.state == RECOVERING:
                    await self._set_state(db, task, RUNNING, "Tool execution recovered")
                failure_streak = 0
            else:
                failure_streak += 1
                if failure_streak >= 2:
                    messages.append(ChatMessage(role="system", content=TOOL_FAILURE_HINT))
            await db.flush()

        task.messages = [m.as_dict() for m in messages]
        await db.flush()
        return (failure_streak, outcome)

    async def _run_tool(self, db, task, ctx, registry, tools, tool, args) -> ToolResult:
        preview = str(args)[:300]
        await self._emit(
            db, task, "tool_call", f"{tool.name}({preview})", {"tool": tool.name, "arguments": _safe(args)}
        )
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                registry.execute(tool.name, args, ctx, tools=tools),
                timeout=self.settings.tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            result = ToolResult(
                ok=False,
                error=f"Tool '{tool.name}' exceeded the {self.settings.tool_timeout_seconds}s timeout.",
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        body = result.output if result.ok else (result.error or "")
        await self._emit(
            db,
            task,
            "tool_result",
            f"{tool.name} -> {'ok' if result.ok else 'error'} ({duration_ms}ms)",
            {
                "tool": tool.name,
                "ok": result.ok,
                "duration_ms": duration_ms,
                "preview": str(body)[:MAX_TOOL_PREVIEW],
                "error": (result.error or "")[:MAX_TOOL_PREVIEW] if not result.ok else "",
            },
        )
        return result

    # ------------------------------------------------------------- approvals
    async def _request_approval(self, db, task, employee, call, tool) -> None:
        """Create an approval request and suspend the task."""
        approval = Approval(
            id=new_id(),
            task_id=task.id,
            employee_id=employee.id,
            kind="tool_execution",
            title=f"{employee.name} requests approval: {tool.name}",
            description=(
                f"Action: {tool.name}\nRequested by: {employee.name}\n"
                f"Arguments: {_safe(call.arguments)}"
            ),
            payload={
                "tool": tool.name,
                "arguments": _safe(call.arguments),
                "call_id": call.id,
                "risk": tool.risk,
            },
            state="pending",
        )
        db.add(approval)
        task.pending_tool = {
            "call_id": call.id,
            "tool": tool.name,
            "arguments": _safe(call.arguments),
            "approval_id": approval.id,
        }
        task.approval_needed = True
        await self._set_state(
            db, task, WAITING_APPROVAL,
            f"Waiting for approval: {tool.name}",
            {"approval_id": approval.id, "tool": tool.name},
        )
        await db.flush()

    async def _resume_pending(self, db, task, employee, ctx, registry, tool_map, messages) -> None:
        """Execute or refuse the tool call that was suspended for approval."""
        pending = task.pending_tool or {}
        approval_id = pending.get("approval_id")
        approval = await db.get(Approval, approval_id) if approval_id else None
        if approval is None:
            # Fallback: the most recent approval row for this task.
            approval = (
                await db.execute(
                    select(Approval)
                    .where(Approval.task_id == task.id)
                    .order_by(Approval.created_at.desc())
                )
            ).scalars().first()
        tool = tool_map.get(pending.get("tool") or "")
        args = pending.get("arguments") or {}

        if approval is None or tool is None:
            reason = "The approval record or tool is no longer available."
            result = ToolResult(ok=False, error=f"Action refused: {reason}")
        elif approval.state == "approved":
            await self._set_state(db, task, RUNNING, f"Approved: executing {tool.name}")
            result = await self._run_tool(db, task, ctx, registry, [tool], tool, args)
        else:
            reason = approval.reason or "The user denied this action."
            result = ToolResult(ok=False, error=f"Action denied by the user: {reason}")
            await self._set_state(db, task, RUNNING, "Action denied by the user; continuing")

        task.pending_tool = None
        task.approval_needed = False
        messages.append(
            ChatMessage(
                role="tool",
                content=result.as_message()[:MAX_MESSAGE_CHARS],
                tool_call_id=str(pending.get("call_id") or ""),
                name=str(pending.get("tool") or ""),
            )
        )
        task.messages = [m.as_dict() for m in messages]
        await db.flush()

    # -------------------------------------------------------------- planning
    async def _plan(self, db, task, employee, selection, messages) -> None:
        await self._set_state(db, task, PLANNING, "Creating an execution plan")
        await db.flush()
        request = ChatRequest(
            model=selection.model_name,
            messages=[
                ChatMessage(role="system", content="You are a task planner for an AI workforce platform."),
                ChatMessage(role="user", content=build_planning_prompt(task.objective)),
            ],
            temperature=0.1,
            response_format="json",
        )
        try:
            response = await asyncio.wait_for(
                selection.adapter.chat(request), timeout=self.settings.model_timeout_seconds
            )
        except (ModelError, asyncio.TimeoutError) as exc:
            await self._emit(
                db, task, "message",
                f"Planning skipped: no plan could be generated ({exc}). Executing directly.",
                {"warning": True},
            )
            return
        steps = _parse_plan(response.content)
        if not steps:
            await self._emit(
                db, task, "message",
                "Planning skipped: the model did not return a usable plan. Executing directly.",
                {"warning": True},
            )
            return
        steps = steps[: self.settings.max_subtasks]
        plan = []
        for i, step in enumerate(steps):
            plan.append(
                {"index": i, "title": step.get("title", f"Step {i + 1}"),
                 "description": step.get("description", ""), "status": "pending"}
            )
            db.add(
                SubTask(
                    task_id=task.id,
                    title=step.get("title", f"Step {i + 1}")[:255],
                    description=(step.get("description") or "")[:4000],
                    order_index=i,
                )
            )
        task.plan = plan
        await db.flush()
        await self._emit(
            db, task, "planned",
            f"Plan created with {len(plan)} step(s)",
            {"steps": [{"title": s["title"]} for s in plan]},
        )

    # ------------------------------------------------------------- completion
    async def _complete(self, db, task, employee, ctx, content: str) -> None:
        task.report = content
        task.result = {"summary": content[:2000], "iterations": task.iterations_used, "tool_calls": task.tool_calls}
        task.finished_at = datetime.now(timezone.utc)
        task.approval_needed = False
        # Persist the deliverable as a downloadable artifact.
        try:
            reports_dir = ctx.workspace / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            path = reports_dir / f"{_slugify(task.title)}-{task.id[:8]}.md"
            path.write_text(content, encoding="utf-8")
            await self._add_artifact(db, task, employee, ctx.workspace, path, "report", path.name)
        except OSError as exc:
            await self._emit(db, task, "error", f"Could not persist the report artifact: {exc}", {})
        # Retain a durable, factual memory of completed work.
        if employee.memory_enabled and employee.memory_scope == "persistent":
            try:
                db.add(
                    EmployeeMemory(
                        employee_id=employee.id,
                        kind="summary",
                        key=f"task: {task.title}"[:160],
                        content=content[:1200],
                        source_task_id=task.id,
                    )
                )
            except Exception:  # memory must never break completion
                logger.exception("Failed to store memory")
        await self._set_state(db, task, COMPLETED, "Task completed")
        await audit(
            db, action="task.completed", actor=f"employee:{employee.id}",
            user_id=task.user_id, resource_type="task", resource_id=task.id,
            detail={"iterations": task.iterations_used, "tool_calls": task.tool_calls},
        )
        await db.flush()

    async def _fail(self, db, task, error: str) -> None:
        task.error = error
        task.finished_at = datetime.now(timezone.utc)
        task.approval_needed = False
        task.pending_tool = None
        await self._set_state(db, task, FAILED, error[:500], {"error": error[:4000]}, force=True)
        await audit(
            db, action="task.failed", actor="system", user_id=task.user_id,
            resource_type="task", resource_id=task.id, detail={"error": error[:500]},
        )
        await db.flush()

    # ---------------------------------------------------------------- helpers
    async def _set_state(self, db, task, new_state: str, message: str, payload: dict | None = None, force: bool = False):
        old = task.state
        if old == new_state:
            return
        allowed = ALLOWED_TRANSITIONS.get(old, set())
        if new_state not in allowed and not force:
            logger.warning("Illegal transition %s -> %s for task %s", old, new_state, task.id)
        task.state = new_state
        await record_event(
            db, task.id, "state_change", message or f"{old} -> {new_state}",
            {"from": old, "to": new_state, **(payload or {})},
            user_id=task.user_id,
        )

    async def _emit(self, db, task, type_: str, message: str, payload: dict | None = None) -> None:
        await record_event(db, task.id, type_, message, payload, user_id=task.user_id)

    async def _record_usage(self, db, task, selection, ok: bool, latency_ms: int, error: str | None = None, usage=None) -> None:
        db.add(
            UsageRecord(
                user_id=task.user_id,
                employee_id=task.employee_id,
                task_id=task.id,
                provider_id=getattr(selection.provider, "id", None),
                provider_kind=getattr(selection.provider, "kind", ""),
                model=selection.model_name,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                latency_ms=latency_ms,
                ok=ok,
                error=(error or "")[:1000] or None,
            )
        )
        await db.flush()

    async def _add_artifact(self, db, task, employee, workspace: Path, path: Path, kind: str, name: str | None):
        try:
            resolved = path.resolve()
            resolved.relative_to(Path(workspace).resolve())
        except (ValueError, OSError):
            logger.warning("Refusing artifact outside workspace: %s", path)
            return None
        if not resolved.exists() or not resolved.is_file():
            return None
        data = resolved.read_bytes()
        artifact = Artifact(
            user_id=task.user_id,
            task_id=task.id,
            employee_id=employee.id,
            name=name or resolved.name,
            kind=kind,
            relative_path=str(resolved.relative_to(Path(workspace).resolve())),
            mime_type=mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        db.add(artifact)
        await db.flush()
        await record_event(
            db, task.id, "artifact", f"Artifact created: {artifact.name}",
            {"artifact_id": artifact.id, "kind": kind, "size": artifact.size},
            user_id=task.user_id,
        )
        return artifact

    # ------------------------------------------------------------- delegation
    async def _delegate(
        self,
        db,
        task,
        employee,
        effective: dict,
        *,
        target_employee_id: str,
        objective: str,
        title: str = "Delegated subtask",
        wait: bool = True,
        timeout_seconds: int = 300,
    ) -> Any:
        settings = self.settings
        if task.delegation_depth >= settings.max_delegation_depth:
            return ToolResult(
                ok=False,
                error=f"Maximum delegation depth ({settings.max_delegation_depth}) reached.",
            )
        target = await db.get(Employee, target_employee_id)
        if target is None or target.user_id != task.user_id:
            return ToolResult(ok=False, error="Target employee not found.")
        if target.status != EMPLOYEE_ACTIVE:
            return ToolResult(ok=False, error=f"Employee '{target.name}' is {target.status}.")
        if target.id == employee.id:
            return ToolResult(ok=False, error="An employee cannot delegate to itself.")

        child_permissions = intersect_permissions(effective, dict(target.permissions or {}))
        child = Task(
            user_id=task.user_id,
            employee_id=target.id,
            team_id=task.team_id,
            parent_task_id=task.id,
            title=title[:255],
            objective=objective,
            state=QUEUED,
            effective_permissions=child_permissions,
            delegation_depth=task.delegation_depth + 1,
            max_iterations=min(target.max_iterations, settings.max_iterations),
            timeout_seconds=min(target.timeout_seconds, settings.task_timeout_seconds),
            priority=task.priority,
        )
        db.add(child)
        await db.flush()
        await record_event(
            db, task.id, "delegated",
            f"Delegated to {target.name}: {title[:120]}",
            {"child_task_id": child.id, "employee_id": target.id},
            user_id=task.user_id,
        )
        await db.commit()

        from bozii.engine.queue import get_queue

        queue = get_queue()
        await queue.enqueue(child.id)

        if not wait:
            return {
                "child_task_id": child.id,
                "employee": target.name,
                "state": "queued",
                "note": "Not waiting; poll with get_task_status.",
            }

        timeout = max(10, min(timeout_seconds, 1200))
        await queue.wait_for([child.id], timeout=timeout)
        async with self.session_factory() as fresh:
            await fresh.rollback()
            child = await fresh.get(Task, child.id)
            state = child.state if child else "unknown"
            if child is None:
                return ToolResult(ok=False, error="Delegated task vanished.")
            payload = {
                "child_task_id": child.id,
                "employee": target.name,
                "state": state,
                "iterations": child.iterations_used,
                "report": (child.report or "")[:6000],
                "error": child.error,
            }
            if state == COMPLETED:
                return payload
            if state in (FAILED, CANCELLED):
                return ToolResult(
                    ok=False,
                    error=f"Delegated task {state}: {child.error or 'no detail'}. Adapt or try another approach.",
                )
            return ToolResult(
                ok=False,
                error=(
                    f"Delegated task did not finish within {timeout}s (state: {state}). "
                    "Continue with what you can verify, or poll get_task_status later."
                ),
            )

    async def _send_message(self, db, task, employee, *, content: str, to_employee_id: str | None = None):
        from bozii.models import TeamMessage

        message = TeamMessage(
            team_id=task.team_id,
            from_employee_id=employee.id,
            to_employee_id=to_employee_id,
            task_id=task.id,
            content=content[:4000],
        )
        db.add(message)
        await db.flush()
        await record_event(
            db, task.id, "message",
            f"Message from {employee.name}: {content[:200]}",
            {"message_id": message.id, "to": to_employee_id},
            user_id=task.user_id,
        )
        return message


# ----------------------------------------------------------------- utilities
def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_safe(v) for v in value[:40]]
    if isinstance(value, str):
        return value[:4000]
    return value


def _parse_plan(content: str) -> list[dict]:
    import json

    if not content:
        return []
    text = content.strip()
    candidates = []
    if text.startswith("{"):
        candidates.append(text)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        steps = data.get("steps") if isinstance(data, dict) else None
        if isinstance(steps, list) and steps:
            out = []
            for step in steps:
                if isinstance(step, str):
                    out.append({"title": step, "description": ""})
                elif isinstance(step, dict):
                    out.append(
                        {
                            "title": str(step.get("title") or step.get("name") or "Step")[:255],
                            "description": str(step.get("description") or step.get("detail") or ""),
                        }
                    )
            return out
    return []


__all__ = ["TaskRunner", "workspace_for"]
