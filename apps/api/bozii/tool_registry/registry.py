"""Tool registry: the single place that knows which tools exist and who may run them."""

from __future__ import annotations

import logging
from typing import Any

from bozii.security.permissions import PermissionDenied, check_permission
from bozii.states import CAP_ACTIVE, EMPLOYEE_ACTIVE
from bozii.tool_registry.base import Tool, ToolContext, ToolResult, ToolValidationError

logger = logging.getLogger("bozii.tools")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: (t.category, t.name))

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        return [t.describe() for t in self.all()]

    def for_employee(self, employee, permissions: dict) -> list[Tool]:
        """Tools the employee may call under its effective permissions.

        Builtin tools are filtered by explicit allow/deny lists and by the
        permissions the tool requires. Capability tools are appended by the
        runtime after this call (they carry their own permission manifests).
        """
        allow = set(getattr(employee, "tools_allowlist", []) or [])
        deny = set(getattr(employee, "tools_denylist", []) or [])
        out: list[Tool] = []
        for tool in self.all():
            if tool.name in deny:
                continue
            if allow and tool.name not in allow:
                continue
            try:
                check_permission(permissions, tool.required_permissions, tool.name)
            except PermissionDenied:
                continue
            out.append(tool)
        return out

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        ctx: ToolContext,
        tools: list[Tool] | None = None,
        enforce_permissions: bool = True,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None and tools is not None:
            tool = next((t for t in tools if t.name == name), None)
        if tool is None:
            return ToolResult(
                ok=False,
                error=f"Unknown tool '{name}'. Available tools: {', '.join(self.names())}.",
            )
        if enforce_permissions:
            try:
                check_permission(ctx.permissions, tool.required_permissions, tool.name)
            except PermissionDenied as exc:
                return ToolResult(ok=False, error=f"Permission denied: {exc}")
        try:
            args = tool.validate(args or {})
        except ToolValidationError as exc:
            return ToolResult(ok=False, error=f"Invalid input for '{name}': {exc}")
        try:
            result = await tool.execute(args, ctx)
        except PermissionDenied as exc:
            result = ToolResult(ok=False, error=f"Permission denied: {exc}")
        except Exception as exc:  # tool bugs must not kill the task loop
            logger.exception("Tool %s crashed", name)
            result = ToolResult(ok=False, error=f"Tool '{name}' failed unexpectedly: {exc}")
        if not isinstance(result, ToolResult):
            result = ToolResult(ok=True, output=result)
        return result


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        from bozii.tool_registry.builtins import install_builtin_tools

        _registry = ToolRegistry()
        install_builtin_tools(_registry)
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


__all__ = ["ToolRegistry", "get_registry", "reset_registry"]
