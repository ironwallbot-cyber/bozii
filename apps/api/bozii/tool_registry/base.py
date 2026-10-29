"""Common execution contract shared by every tool (builtin or generated)."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from bozii.model_adapters.base import ToolSpec
from bozii.states import TOOL_RISK_SAFE


class ToolError(Exception):
    """Raised when a tool cannot complete; the message is safe to show the model."""


class ToolValidationError(ToolError):
    pass


@dataclass
class ToolContext:
    """Everything a tool is allowed to touch during one execution."""

    user_id: str
    employee_id: str
    employee_name: str
    workspace: Path
    session: AsyncSession
    permissions: dict
    task_id: str | None = None
    team_id: str | None = None
    delegation_depth: int = 0
    add_artifact: Callable[[Path, str, str | None], Awaitable[Any]] | None = None
    emit: Callable[..., Awaitable[None]] | None = None
    delegate: Callable[..., Awaitable[Any]] | None = None
    send_message: Callable[..., Awaitable[Any]] | None = None
    memory: list[dict] = field(default_factory=list)
    capability_store: Callable[..., Awaitable[Any]] | None = None

    async def record_artifact(self, path: Path, kind: str = "file", name: str | None = None) -> Any:
        if self.add_artifact is None:
            return None
        return await self.add_artifact(path, kind, name)

    async def emit_event(self, type_: str, message: str, payload: dict | None = None) -> None:
        if self.emit is not None:
            await self.emit(type_, message, payload or {})


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> str:
        """Render the result as text for the model conversation."""
        if self.ok:
            body = json.dumps(self.output, ensure_ascii=False, default=str) if not isinstance(self.output, str) else self.output
            prefix = "Result"
        else:
            body = self.error or "Unknown error"
            prefix = "Error"
        if len(body) > 20000:
            body = body[:20000] + "\n...[truncated]"
        lines = [f"{prefix} from tool:", body]
        if self.artifacts:
            lines.append("Artifacts: " + ", ".join(self.artifacts))
        return "\n".join(lines)


# ------------------------------------------------------------------ validation
def _check_type(value: Any, expected: str, path: str, errors: list[str]) -> None:
    mapping = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    py = mapping.get(expected)
    if py is None:
        return
    if expected in {"integer", "number"} and isinstance(value, bool):
        errors.append(f"{path}: expected {expected}, got boolean")
        return
    if not isinstance(value, py):
        errors.append(f"{path}: expected {expected}, got {type(value).__name__}")


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Minimal JSON-schema subset validator (required, types, enums, nesting)."""
    if not isinstance(args, dict):
        raise ToolValidationError("Tool arguments must be a JSON object")
    errors: list[str] = []
    props: dict = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    for key in required:
        if key not in args or args[key] is None:
            errors.append(f"Missing required field: {key}")
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{key}: must be one of {spec['enum']}")
            continue
        if "type" in spec:
            _check_type(value, spec["type"], key, errors)
        if spec.get("type") == "array" and isinstance(value, list):
            item_spec = spec.get("items") or {}
            for i, item in enumerate(value[:20]):
                if "type" in item_spec:
                    _check_type(item, item_spec["type"], f"{key}[{i}]", errors)
        if spec.get("type") == "object" and isinstance(value, dict) and "properties" in spec:
            try:
                validate_args(spec, value)
            except ToolValidationError as exc:
                errors.append(f"{key}: {exc}")
    if errors:
        raise ToolValidationError("; ".join(errors))
    return args


class Tool(ABC):
    """Base class for every Bozii tool."""

    name: str = ""
    title: str = ""
    description: str = ""
    category: str = "utility"
    risk: str = TOOL_RISK_SAFE
    required_permissions: dict[str, Any] = {}
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    version: str = "1.0.0"

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "category": self.category,
            "kind": "builtin",
            "risk": self.risk,
            "required_permissions": self.required_permissions,
            "parameters": self.parameters,
            "version": self.version,
        }

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        return validate_args(self.parameters, args or {})

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolResult",
    "ToolValidationError",
    "validate_args",
]
