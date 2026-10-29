"""Development tools: sandboxed command execution and project archives."""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Any

from bozii.config import get_settings
from bozii.sandbox import CommandNotAllowed, check_command, run_sandboxed
from bozii.security.permissions import PathEscapeError, safe_path
from bozii.states import TOOL_RISK_MUTATING
from bozii.tool_registry.base import Tool, ToolContext, ToolResult, ToolError


class RunCommandTool(Tool):
    name = "run_command"
    title = "Run command"
    description = (
        "Run an allow-listed command inside the workspace sandbox (tests, linters, type "
        "checkers, builds, git). Executes with CPU/memory limits, a timeout and, when the "
        "host supports it, no network access. Returns exit code, stdout and stderr."
    )
    category = "development"
    risk = TOOL_RISK_MUTATING
    required_permissions = {"exec": "sandbox"}
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command line to run, e.g. 'python3 -m pytest -q'"},
            "cwd": {"type": "string", "description": "Working sub-directory inside the workspace"},
            "timeout": {"type": "integer", "description": "Seconds before the command is killed (default 60, max 300)"},
            "network": {"type": "boolean", "description": "Allow network access (requires the network permission)"},
        },
        "required": ["command"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        allow_network = bool(args.get("network"))
        if allow_network:
            net = (ctx.permissions or {}).get("net", "none")
            if net in (None, "none", False):
                return ToolResult(
                    ok=False,
                    error="This employee does not have the network permission, so commands must run offline.",
                )
        try:
            argv = check_command(args["command"])
        except CommandNotAllowed as exc:
            return ToolResult(ok=False, error=str(exc))
        try:
            cwd = safe_path(ctx.workspace, args.get("cwd") or "") if args.get("cwd") else Path(ctx.workspace)
        except PathEscapeError as exc:
            return ToolResult(ok=False, error=str(exc))
        if not cwd.exists():
            return ToolResult(ok=False, error=f"Working directory not found: {args.get('cwd')}")

        settings = get_settings()
        timeout = max(5, min(int(args.get("timeout") or settings.sandbox_timeout_seconds), 300))
        result = await run_sandboxed(argv, cwd=cwd, timeout=timeout, network=allow_network)
        payload = {
            "command": args["command"],
            "success": result.ok,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "isolation": result.isolation,
        }
        if result.timed_out:
            payload["success"] = False
        return ToolResult(ok=True, output=payload)


class CreateArchiveTool(Tool):
    name = "create_archive"
    title = "Create archive"
    description = "Create a .tar.gz archive of workspace files and register it as a downloadable artifact."
    category = "development"
    risk = TOOL_RISK_MUTATING
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Workspace-relative paths to include",
            },
            "archive_name": {"type": "string", "description": "Archive file name, e.g. 'project.tar.gz'"},
        },
        "required": ["paths", "archive_name"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = args["archive_name"]
        if not name.endswith((".tar.gz", ".tgz")):
            name = f"{name}.tar.gz"
        try:
            archive_path = safe_path(ctx.workspace, name)
        except PathEscapeError as exc:
            return ToolResult(ok=False, error=str(exc))
        members: list[Path] = []
        for rel in args["paths"]:
            try:
                target = safe_path(ctx.workspace, rel)
            except PathEscapeError as exc:
                return ToolResult(ok=False, error=str(exc))
            if not target.exists():
                return ToolResult(ok=False, error=f"Path not found: {rel}")
            members.append(target)
        if not members:
            return ToolResult(ok=False, error="No paths given")

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            for member in members:
                tar.add(member, arcname=str(Path(member).relative_to(ctx.workspace)))
        artifact = await ctx.record_artifact(archive_path, kind="archive", name=archive_path.name)
        return ToolResult(
            ok=True,
            output={
                "archive": archive_path.name,
                "size": archive_path.stat().st_size,
                "files": len(members),
                "artifact_id": getattr(artifact, "id", None),
            },
        )


TOOLS: list[Tool] = [RunCommandTool(), CreateArchiveTool()]
