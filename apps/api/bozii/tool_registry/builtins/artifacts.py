"""Artifact tools: register deliverables and list them."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from bozii.models import Artifact
from bozii.security.permissions import PathEscapeError, safe_path
from bozii.states import TOOL_RISK_MUTATING
from bozii.tool_registry.base import Tool, ToolContext, ToolResult


class ListArtifactsTool(Tool):
    name = "list_artifacts"
    title = "List artifacts"
    description = "List deliverables produced so far in this task (reports, data files, archives)."
    category = "artifacts"
    required_permissions = {}
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = (
            select(Artifact)
            .where(Artifact.user_id == ctx.user_id)
            .order_by(Artifact.created_at.desc())
            .limit(50)
        )
        if ctx.task_id:
            query = (
                select(Artifact)
                .where(Artifact.user_id == ctx.user_id, Artifact.task_id == ctx.task_id)
                .order_by(Artifact.created_at.desc())
                .limit(50)
            )
        rows = (await ctx.session.execute(query)).scalars().all()
        return ToolResult(
            ok=True,
            output={
                "artifacts": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "kind": a.kind,
                        "size": a.size,
                        "mime_type": a.mime_type,
                        "created_at": a.created_at.isoformat(),
                    }
                    for a in rows
                ],
                "count": len(rows),
            },
        )


class CreateArtifactTool(Tool):
    name = "create_artifact"
    title = "Register artifact"
    description = (
        "Register an existing workspace file as a deliverable so the user can download it, "
        "optionally writing new content at the same time."
    )
    category = "artifacts"
    risk = TOOL_RISK_MUTATING
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path"},
            "kind": {
                "type": "string",
                "enum": ["file", "report", "dataset", "archive"],
                "description": "Artifact category (default 'file')",
            },
            "name": {"type": "string", "description": "Display name (defaults to the file name)"},
            "content": {"type": "string", "description": "Optional content to write before registering"},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = safe_path(ctx.workspace, args["path"])
        except PathEscapeError as exc:
            return ToolResult(ok=False, error=str(exc))
        if args.get("content") is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
        if not path.exists() or not path.is_file():
            return ToolResult(ok=False, error=f"File not found: {args['path']}")
        artifact = await ctx.record_artifact(
            path, kind=args.get("kind") or "file", name=args.get("name") or path.name
        )
        if artifact is None:
            return ToolResult(ok=True, output={"path": args["path"], "registered": False})
        return ToolResult(
            ok=True,
            output={
                "artifact_id": artifact.id,
                "name": artifact.name,
                "path": artifact.relative_path,
                "size": artifact.size,
                "sha256": artifact.sha256,
            },
            artifacts=[artifact.id],
        )


TOOLS: list[Tool] = [ListArtifactsTool(), CreateArtifactTool()]
