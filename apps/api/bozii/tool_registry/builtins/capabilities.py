"""Capability tools: discover, inspect and create tools/skills at runtime."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from bozii.models import Capability
from bozii.states import CAP_ACTIVE, TOOL_RISK_CONSEQUENTIAL
from bozii.tool_registry.base import Tool, ToolContext, ToolResult


class ListCapabilitiesTool(Tool):
    name = "list_capabilities"
    title = "Search capabilities"
    description = (
        "Search your installed capabilities plus available public ones. Always check here "
        "before building something new: an existing tool may already solve the problem."
    )
    category = "capabilities"
    required_permissions = {}
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text search over name, description and tags"},
            "kind": {"type": "string", "enum": ["tool", "skill"], "description": "Filter by capability kind"},
            "include_public": {"type": "boolean", "description": "Include published public capabilities (default true)"},
            "limit": {"type": "integer", "description": "Maximum results (default 20)"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        limit = max(1, min(int(args.get("limit") or 20), 100))
        stmt = select(Capability).where(Capability.is_active.is_(True))
        include_public = args.get("include_public", True)
        if not include_public:
            stmt = stmt.where(Capability.visibility == "private")
        stmt = stmt.where(
            or_(Capability.created_by_user_id == ctx.user_id, Capability.visibility == "public")
        )
        if args.get("kind"):
            stmt = stmt.where(Capability.kind == args["kind"])
        if args.get("query"):
            q = f"%{args['query']}%"
            stmt = stmt.where(
                or_(
                    Capability.name.ilike(q),
                    Capability.description.ilike(q),
                    Capability.slug.ilike(q),
                    Capability.category.ilike(q),
                )
            )
        rows = (await ctx.session.execute(stmt.order_by(Capability.downloads.desc()).limit(limit))).scalars()
        items = [
            {
                "slug": c.slug,
                "name": c.name,
                "kind": c.kind,
                "version": c.version,
                "category": c.category,
                "description": c.description,
                "visibility": c.visibility,
                "permissions": c.permissions,
                "self_built": c.created_by_user_id == ctx.user_id,
            }
            for c in rows
        ]
        return ToolResult(
            ok=True,
            output={"capabilities": items, "count": len(items)},
        )


class GetCapabilityTool(Tool):
    name = "get_capability"
    title = "Inspect capability"
    description="Return the manifest, permissions, schema and test results of one capability."
    category = "capabilities"
    required_permissions = {}
    parameters = {
        "type": "object",
        "properties": {"slug": {"type": "string", "description": "Capability slug"}},
        "required": ["slug"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        row = await ctx.session.execute(
            select(Capability)
            .where(Capability.slug == args["slug"], Capability.is_active.is_(True))
            .order_by(Capability.version.desc())
        )
        cap = row.scalars().first()
        if cap is None:
            return ToolResult(ok=False, error=f"Capability '{args['slug']}' not found")
        if cap.visibility != "public" and cap.created_by_user_id != ctx.user_id:
            return ToolResult(ok=False, error=f"Capability '{args['slug']}' is not available to you")
        return ToolResult(
            ok=True,
            output={
                "slug": cap.slug,
                "name": cap.name,
                "kind": cap.kind,
                "version": cap.version,
                "description": cap.description,
                "category": cap.category,
                "input_schema": cap.input_schema,
                "permissions": cap.permissions,
                "dependencies": cap.dependencies,
                "files": sorted(cap.files.keys()),
                "test_results": cap.test_results,
                "scan_results": cap.scan_results,
            },
        )


class CreateCapabilityTool(Tool):
    name = "create_capability"
    title = "Create capability"
    description=(
        "Build a missing capability: the engine generates the implementation, validates it, "
        "runs its tests in an isolated sandbox and registers it as a reusable, versioned "
        "capability. Fails honestly if validation does not pass."
    )
    category = "capabilities"
    risk = TOOL_RISK_CONSEQUENTIAL
    required_permissions = {"capability_create": True}
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Capability name, e.g. 'weather_lookup'"},
            "kind": {"type": "string", "enum": ["tool", "skill"], "description": "Default 'tool'"},
            "description": {"type": "string", "description": "What it does and when to use it"},
            "requirements": {"type": "string", "description": "Detailed functional requirements and acceptance criteria"},
            "category": {"type": "string", "description": "Category, e.g. 'data', 'web', 'dev'"},
            "permissions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Permissions the capability requests: fs_read, fs_write, net_search, net_fetch, exec",
            },
            "test_hint": {"type": "string", "description": "Extra guidance for the generated tests"},
            "activate": {"type": "boolean", "description": "Activate immediately after validation (default true)"},
        },
        "required": ["name", "description", "requirements"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if ctx.capability_store is None:
            return ToolResult(ok=False, error="The capability engine is not available in this context.")
        if not (ctx.permissions or {}).get("capability_create"):
            return ToolResult(ok=False, error="This employee is not allowed to create capabilities.")
        result = await ctx.capability_store(
            name=args["name"],
            kind=args.get("kind") or "tool",
            description=args.get("description") or "",
            requirements=args.get("requirements") or "",
            category=args.get("category") or "general",
            permissions=list(args.get("permissions") or []),
            test_hint=args.get("test_hint") or "",
            activate=bool(args.get("activate", True)),
        )
        if isinstance(result, ToolResult):
            return result
        return ToolResult(ok=True, output=result)


TOOLS: list[Tool] = [ListCapabilitiesTool(), GetCapabilityTool(), CreateCapabilityTool()]
